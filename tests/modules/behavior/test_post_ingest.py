"""
Tests for modules/behavior/module.py — post_ingest() derived metrics.

Exercises the 11 derived metric computations using a real SQLite database.
Each test class covers one metric family with edge cases.
"""

import json

import pytest

from core.event import Event
from modules.behavior import create_module

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

DATE = "2026-03-20"
DAY_TS_PREFIX = f"{DATE}T23:59:00"

CONFIG = {
    "lifedata": {
        "modules": {
            "behavior": {
                "enabled": True,
                "baseline_window_days": 14,
                "fragmentation_ceiling": 60,
                "step_goal": 8000,
                "restlessness_threshold": 2.0,
                "sedentary_threshold": 50,
                "sedentary_min_bout_hours": 2,
            }
        }
    }
}


def _make_module():
    """Create a BehaviorModule with test config."""
    cfg = CONFIG["lifedata"]["modules"]["behavior"]
    return create_module(cfg)


def _utc(hour: int, minute: int = 0) -> str:
    return f"{DATE}T{hour:02d}:{minute:02d}:00+00:00"


def _local(hour: int, minute: int = 0) -> str:
    return f"{DATE}T{hour:02d}:{minute:02d}:00-05:00"


def _app_transition(hour: int, minute: int, from_app: str, to_app: str, dwell_sec: int) -> Event:
    """Create an app transition event."""
    return Event(
        timestamp_utc=_utc(hour, minute),
        timestamp_local=_local(hour, minute),
        timezone_offset="-0500",
        source_module="behavior.app_switch",
        event_type="transition",
        value_json=json.dumps({
            "from_app": from_app,
            "to_app": to_app,
            "dwell_sec": dwell_sec,
        }),
        confidence=1.0,
        parser_version="1.0.0",
    )


def _step_event(hour: int, steps: int) -> Event:
    """Create an hourly step count event."""
    return Event(
        timestamp_utc=_utc(hour),
        timestamp_local=_local(hour),
        timezone_offset="-0500",
        source_module="behavior.steps",
        event_type="hourly_count",
        value_numeric=float(steps),
        value_json=json.dumps({"hour": hour}),
        confidence=1.0,
        parser_version="1.0.0",
    )


def _screen_on(hour: int, minute: int = 0) -> Event:
    """Create a screen_on event."""
    return Event(
        timestamp_utc=_utc(hour, minute),
        timestamp_local=_local(hour, minute),
        timezone_offset="-0500",
        source_module="device.screen",
        event_type="screen_on",
        value_text="on",
        confidence=1.0,
        parser_version="1.0.0",
    )


def _query_derived(db, source_module_like, event_type=None):
    """Query derived events for the test date."""
    if event_type:
        rows = db.conn.execute(
            "SELECT * FROM events WHERE source_module LIKE ? AND event_type = ? AND date(timestamp_utc) = ?",
            (source_module_like, event_type, DATE),
        ).fetchall()
    else:
        rows = db.conn.execute(
            "SELECT * FROM events WHERE source_module LIKE ? AND date(timestamp_utc) = ?",
            (source_module_like, DATE),
        ).fetchall()
    return rows


def _get_column_names(db):
    """Get column names from the events table."""
    cursor = db.conn.execute("SELECT * FROM events LIMIT 0")
    return [desc[0] for desc in cursor.description]


def _row_to_dict(db, row):
    """Convert a row tuple to a dict using column names."""
    cols = _get_column_names(db)
    return dict(zip(cols, row))


# ──────────────────────────────────────────────────────────────
# TestFragmentationIndex
# ──────────────────────────────────────────────────────────────


class TestFragmentationIndex:
    """Tests for behavior.app_switch.derived / fragmentation_index."""

    def test_high_fragmentation(self, db):
        """Many short-dwell switches across many apps yield high fragmentation."""
        mod = _make_module()
        events = []
        apps = [f"com.app{i}" for i in range(20)]
        for i in range(40):
            events.append(_app_transition(
                hour=9 + (i * 5) // 60,
                minute=(i * 5) % 60,
                from_app=apps[i % 20],
                to_app=apps[(i + 1) % 20],
                dwell_sec=15,  # very short dwells
            ))

        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.app_switch.derived", "fragmentation_index")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        frag_score = r["value_numeric"]
        # Short dwells + many apps + high rate = high score
        assert frag_score > 50, f"Expected high fragmentation, got {frag_score}"

    def test_zero_switches_no_event(self, db):
        """No app transitions => no fragmentation event emitted."""
        mod = _make_module()
        # Insert one step event so there's something in the DB for this date
        db.insert_events_for_module("behavior", [_step_event(10, 500)])
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.app_switch.derived", "fragmentation_index")
        assert len(rows) == 0

    def test_single_app_low_frag(self, db):
        """Long dwells in a single app = low fragmentation score."""
        mod = _make_module()
        events = []
        # 10 transitions, all between same two apps, long dwells
        for i in range(10):
            events.append(_app_transition(
                hour=9 + i,
                minute=0,
                from_app="com.browser",
                to_app="com.editor",
                dwell_sec=600,  # 10-minute dwells
            ))

        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.app_switch.derived", "fragmentation_index")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        frag_score = r["value_numeric"]
        # Long dwells + single app pair + low rate = low score
        assert frag_score < 40, f"Expected low fragmentation, got {frag_score}"


# ──────────────────────────────────────────────────────────────
# TestMovementEntropy
# ──────────────────────────────────────────────────────────────


class TestMovementEntropy:
    """Tests for behavior.steps.derived / movement_entropy."""

    def test_even_distribution_high_entropy(self, db):
        """Steps spread evenly across many hours => high normalized entropy."""
        mod = _make_module()
        events = [_step_event(h, 500) for h in range(6, 18)]  # 12 hours, 500 each
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "movement_entropy")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        entropy = r["value_numeric"]
        # Perfectly even across 12 hours => normalized entropy = 1.0
        assert entropy > 0.95, f"Expected high entropy, got {entropy}"

    def test_concentrated_low_entropy(self, db):
        """Steps in only two hours with unequal distribution => low entropy."""
        mod = _make_module()
        events = [
            _step_event(10, 9000),
            _step_event(11, 100),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "movement_entropy")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        entropy = r["value_numeric"]
        assert entropy < 0.3, f"Expected low entropy, got {entropy}"

    def test_zero_steps_no_event(self, db):
        """Zero steps everywhere => no entropy event."""
        mod = _make_module()
        events = [_step_event(10, 0)]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "movement_entropy")
        assert len(rows) == 0

    def test_single_hour_no_event(self, db):
        """Steps in only one hour => no entropy event (needs >= 2 nonzero hours)."""
        mod = _make_module()
        events = [_step_event(10, 5000)]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "movement_entropy")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestDailyStepTotal
# ──────────────────────────────────────────────────────────────


class TestDailyStepTotal:
    """Tests for behavior.steps / daily_total."""

    def test_correct_sum(self, db):
        """Sum of hourly counts matches daily total."""
        mod = _make_module()
        events = [
            _step_event(8, 1200),
            _step_event(9, 800),
            _step_event(10, 1500),
            _step_event(14, 2000),
            _step_event(17, 500),
        ]
        expected_total = 6000
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps", "daily_total")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] == expected_total
        data = json.loads(r["value_json"])
        assert data["total_steps"] == expected_total
        assert data["hours_recorded"] == 5
        # Goal percentage: 6000 / 8000 * 100 = 75.0
        assert data["goal_pct"] == 75.0

    def test_zero_steps_no_event(self, db):
        """All zeroes => no daily total event (sum == 0)."""
        mod = _make_module()
        events = [_step_event(10, 0), _step_event(11, 0)]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps", "daily_total")
        assert len(rows) == 0

    def test_no_step_events_no_total(self, db):
        """No step events at all => no daily total."""
        mod = _make_module()
        # Insert a non-step event so we have a date to process
        db.insert_events_for_module("behavior", [
            _app_transition(10, 0, "com.a", "com.b", 120)
        ])
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps", "daily_total")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestSedentaryBouts
# ──────────────────────────────────────────────────────────────


class TestSedentaryBouts:
    """Tests for behavior.steps.derived / sedentary_bouts."""

    def test_long_sedentary_detected(self, db):
        """Hours 8-12 with <50 steps => one bout of 5 hours (8,9,10,11,12 waking, starting at 8)."""
        mod = _make_module()
        events = []
        for h in range(6, 22):
            if 8 <= h <= 12:
                events.append(_step_event(h, 10))  # sedentary
            else:
                events.append(_step_event(h, 500))  # active
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "sedentary_bouts")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] >= 1  # at least one bout
        data = json.loads(r["value_json"])
        assert data["longest_bout_hours"] >= 2

    def test_active_day_no_bouts(self, db):
        """Every waking hour (6-23) has 500+ steps => no sedentary bouts."""
        mod = _make_module()
        # Must cover ALL waking hours 6-23 so none default to 0
        events = [_step_event(h, 500) for h in range(6, 24)]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "sedentary_bouts")
        assert len(rows) == 0

    def test_short_sedentary_not_counted(self, db):
        """A single sedentary hour (< min_bout_hours=2) is not counted as a bout."""
        mod = _make_module()
        events = []
        # Cover all waking hours 6-23 so gaps don't create false sedentary spans
        for h in range(6, 24):
            if h == 10:
                events.append(_step_event(h, 10))  # one sedentary hour
            else:
                events.append(_step_event(h, 500))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.steps.derived", "sedentary_bouts")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestAttentionSpan
# ──────────────────────────────────────────────────────────────


class TestAttentionSpan:
    """Tests for behavior.derived / attention_span_estimate."""

    def test_long_dwells(self, db):
        """Long dwell times => high attention span estimate."""
        mod = _make_module()
        events = []
        for i in range(10):
            events.append(_app_transition(
                hour=9 + i // 4,
                minute=(i * 10) % 60,
                from_app=f"com.app{i}",
                to_app=f"com.prod{i}",  # not in excluded list
                dwell_sec=300,  # 5-minute dwells
            ))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "attention_span_estimate")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] == pytest.approx(300.0, abs=1.0)

    def test_short_dwells(self, db):
        """Short dwell times => low attention span estimate."""
        mod = _make_module()
        events = []
        for i in range(10):
            events.append(_app_transition(
                hour=9 + i // 4,
                minute=(i * 5) % 60,
                from_app=f"com.app{i}",
                to_app=f"com.work{i}",
                dwell_sec=20,  # 20-second dwells
            ))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "attention_span_estimate")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] == pytest.approx(20.0, abs=1.0)

    def test_too_few_transitions_no_event(self, db):
        """Fewer than 5 valid dwells => no attention span event."""
        mod = _make_module()
        events = []
        for i in range(3):
            events.append(_app_transition(
                hour=9,
                minute=i * 10,
                from_app=f"com.app{i}",
                to_app=f"com.prod{i}",
                dwell_sec=120,
            ))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "attention_span_estimate")
        assert len(rows) == 0

    def test_excluded_apps_filtered(self, db):
        """Transitions to excluded apps (launcher, dialer) are not counted."""
        mod = _make_module()
        events = []
        excluded_apps = ["com.launcher", "com.dialer", "com.music", "com.spotify.player"]
        # 4 excluded + 3 valid = only 3 valid, below threshold
        for i, app in enumerate(excluded_apps):
            events.append(_app_transition(9, i * 5, "com.prev", app, 120))
        for i in range(3):
            events.append(_app_transition(10, i * 5, "com.prev", f"com.valid{i}", 120))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "attention_span_estimate")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestMorningInertia
# ──────────────────────────────────────────────────────────────


class TestMorningInertia:
    """Tests for behavior.derived / morning_inertia_score."""

    def test_quick_start(self, db):
        """Screen on at 7:00, productive app at 7:10 => ~10 min inertia."""
        mod = _make_module()
        events = [
            _screen_on(7, 0),
            _app_transition(7, 10, "com.launcher", "com.code.editor", 300),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "morning_inertia_score")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] == pytest.approx(10.0, abs=1.0)

    def test_slow_start(self, db):
        """Screen on at 7:00, productive app at 8:00 => ~60 min inertia."""
        mod = _make_module()
        events = [
            _screen_on(7, 0),
            # Unproductive browsing first
            _app_transition(7, 5, "com.launcher", "com.social.twitter", 300),
            _app_transition(7, 30, "com.social.twitter", "com.game.puzzle", 300),
            # Productive app at 8:00
            _app_transition(8, 0, "com.game.puzzle", "com.email.client", 300),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "morning_inertia_score")
        assert len(rows) == 1
        r = _row_to_dict(db, rows[0])
        assert r["value_numeric"] == pytest.approx(60.0, abs=1.0)

    def test_no_productive_app(self, db):
        """Screen on but no productive app all morning => no inertia event."""
        mod = _make_module()
        events = [
            _screen_on(7, 0),
            _app_transition(7, 5, "com.launcher", "com.social.twitter", 300),
            _app_transition(7, 30, "com.social.twitter", "com.game.puzzle", 300),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "morning_inertia_score")
        assert len(rows) == 0

    def test_no_screen_on(self, db):
        """No screen_on event => no morning inertia event."""
        mod = _make_module()
        events = [
            _app_transition(7, 10, "com.launcher", "com.code.editor", 300),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "morning_inertia_score")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestDigitalRestlessness — baseline-dependent
# ──────────────────────────────────────────────────────────────


class TestDigitalRestlessness:
    """Tests for behavior.derived / digital_restlessness.

    Requires 7+ days of baseline data. We test that with insufficient
    baseline (<7 days), no event is emitted.
    """

    def test_insufficient_baseline_no_event(self, db):
        """Fewer than 7 baseline days => no restlessness event."""
        mod = _make_module()

        # Insert only 3 days of baseline fragmentation data
        baseline_events = []
        for day_offset in range(1, 4):
            d = f"2026-03-{20 - day_offset:02d}"
            baseline_events.append(Event(
                timestamp_utc=f"{d}T23:59:00+00:00",
                timestamp_local=f"{d}T18:59:00-05:00",
                timezone_offset="-0500",
                source_module="behavior.app_switch.derived",
                event_type="fragmentation_index",
                value_numeric=50.0,
                confidence=0.8,
                parser_version="1.0.0",
            ))

        # Today's fragmentation value
        today_events = [
            Event(
                timestamp_utc=f"{DATE}T23:59:00+00:00",
                timestamp_local=f"{DATE}T18:59:00-05:00",
                timezone_offset="-0500",
                source_module="behavior.app_switch.derived",
                event_type="fragmentation_index",
                value_numeric=70.0,
                confidence=0.8,
                parser_version="1.0.0",
            ),
        ]

        db.insert_events_for_module("behavior", baseline_events + today_events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "digital_restlessness")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestBehavioralConsistency — baseline-dependent
# ──────────────────────────────────────────────────────────────


class TestBehavioralConsistency:
    """Tests for behavior.derived / behavioral_consistency.

    Requires baseline hourly profiles from past N days.
    We test that with no baseline data, no event is emitted.
    """

    def test_insufficient_baseline_no_event(self, db):
        """No baseline app switch data => no consistency event."""
        mod = _make_module()

        # Only today's transitions, no prior days
        events = []
        for i in range(5):
            events.append(_app_transition(
                hour=9 + i,
                minute=0,
                from_app="com.a",
                to_app="com.b",
                dwell_sec=120,
            ))
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.derived", "behavioral_consistency")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestHourlyRate
# ──────────────────────────────────────────────────────────────


class TestHourlyRate:
    """Tests for behavior.app_switch / hourly_rate."""

    def test_hourly_rate_computed(self, db):
        """Multiple transitions in one hour => one hourly_rate event."""
        mod = _make_module()
        events = [
            _app_transition(10, 0, "com.a", "com.b", 60),
            _app_transition(10, 5, "com.b", "com.c", 60),
            _app_transition(10, 10, "com.c", "com.d", 60),
            _app_transition(14, 0, "com.a", "com.b", 60),
        ]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "behavior.app_switch", "hourly_rate")
        assert len(rows) == 2  # hour 10 and hour 14

        # Find the hour-10 row
        for row in rows:
            r = _row_to_dict(db, row)
            data = json.loads(r["value_json"])
            if data["hour"] == 10:
                assert r["value_numeric"] == 3.0
                assert data["switches"] == 3
                break
        else:
            pytest.fail("Hour 10 rate not found")


# ──────────────────────────────────────────────────────────────
# TestPostIngestIntegration
# ──────────────────────────────────────────────────────────────


class TestPostIngestIntegration:
    """Integration test: verify post_ingest produces multiple derived metrics."""

    def test_multiple_metrics_from_mixed_events(self, db):
        """A realistic day with mixed events produces multiple derived metrics."""
        mod = _make_module()
        events = []

        # App transitions (enough for fragmentation + attention span + hourly rate)
        apps = ["com.browser", "com.editor", "com.slack", "com.terminal", "com.notes"]
        for i in range(15):
            events.append(_app_transition(
                hour=9 + (i * 20) // 60,
                minute=(i * 20) % 60,
                from_app=apps[i % 5],
                to_app=apps[(i + 1) % 5],
                dwell_sec=120,
            ))

        # Steps (enough for daily_total + entropy + sedentary bouts)
        for h in range(6, 22):
            events.append(_step_event(h, 300 if h >= 10 else 20))

        # Screen on for morning inertia
        events.append(_screen_on(7, 0))

        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates={DATE})

        # Check that multiple metric types were produced
        all_derived = db.conn.execute(
            """SELECT DISTINCT source_module, event_type FROM events
               WHERE (source_module LIKE 'behavior.%derived%'
                      OR (source_module = 'behavior.app_switch' AND event_type = 'hourly_rate')
                      OR (source_module = 'behavior.steps' AND event_type = 'daily_total'))
                 AND date(timestamp_utc) = ?""",
            (DATE,),
        ).fetchall()

        derived_types = {(r[0], r[1]) for r in all_derived}
        # Should have at least these metrics
        assert ("behavior.app_switch.derived", "fragmentation_index") in derived_types
        assert ("behavior.steps", "daily_total") in derived_types
        assert ("behavior.steps.derived", "movement_entropy") in derived_types

    def test_no_affected_dates_returns_early(self, db):
        """Empty affected_dates set => no derived events computed."""
        mod = _make_module()
        events = [_step_event(10, 500)]
        db.insert_events_for_module("behavior", events)
        mod.post_ingest(db, affected_dates=set())

        all_derived = db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'behavior.%derived%'"
        ).fetchone()
        assert all_derived[0] == 0

    def test_idempotent_rerun(self, db):
        """Running post_ingest twice produces the same results (INSERT OR REPLACE)."""
        mod = _make_module()
        events = [_step_event(h, 500) for h in range(6, 18)]
        db.insert_events_for_module("behavior", events)

        mod.post_ingest(db, affected_dates={DATE})
        count_1 = db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'behavior.%derived%' AND date(timestamp_utc) = ?",
            (DATE,),
        ).fetchone()[0]

        mod.post_ingest(db, affected_dates={DATE})
        count_2 = db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'behavior.%derived%' AND date(timestamp_utc) = ?",
            (DATE,),
        ).fetchone()[0]

        assert count_1 == count_2
        assert count_1 > 0
