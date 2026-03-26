"""
Tests for BodyModule.post_ingest() derived metrics.

Derived metrics tested:
  - body.derived/daily_step_total: SUM of step_count events
  - body.derived/caffeine_level: pharmacokinetic decay (half-life model)
  - body.derived/sleep_duration: from sleep_start/sleep_end pairs
"""

import json
import math

import pytest

from core.event import Event
from modules.body import create_module

DATE = "2026-03-20"
DAY_TS = f"{DATE}T23:59:00+00:00"

CONFIG = {
    "lifedata": {
        "modules": {
            "body": {
                "enabled": True,
                "step_goal": 8000,
                "caffeine_half_life_hours": 5.0,
                "sleep_target_hours": 7.5,
            }
        }
    }
}


def _body_config() -> dict:
    return CONFIG["lifedata"]["modules"]["body"]


def _make_event(
    source_module: str,
    event_type: str,
    timestamp_utc: str = f"{DATE}T12:00:00+00:00",
    timestamp_local: str = f"{DATE}T07:00:00-05:00",
    value_numeric: float | None = None,
    value_text: str | None = None,
    value_json: str | None = None,
) -> Event:
    return Event(
        timestamp_utc=timestamp_utc,
        timestamp_local=timestamp_local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        value_json=value_json,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _query_derived(db, event_type: str):
    """Return all derived events of a given type for the test date."""
    rows = db.execute(
        """
        SELECT value_numeric, value_json FROM events
        WHERE source_module = 'body.derived'
          AND event_type = ?
          AND timestamp_utc = ?
        """,
        (event_type, DAY_TS),
    ).fetchall()
    return rows


# ──────────────────────────────────────────────────────────────
# TestDailyStepTotal
# ──────────────────────────────────────────────────────────────


class TestDailyStepTotal:
    """Tests for body.derived/daily_step_total."""

    def test_sum_correct(self, db):
        """Two step events on the same day should produce a summed total."""
        events = [
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=3000.0,
            ),
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                value_numeric=5000.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 1
        assert rows[0][0] == 8000.0

        meta = json.loads(rows[0][1])
        assert meta["readings"] == 2
        assert meta["goal"] == 8000
        assert meta["goal_pct"] == 100.0

    def test_zero_steps_no_event(self, db):
        """No step events should produce no derived step total event."""
        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 0

    def test_single_step_event(self, db):
        """A single step event should produce a total equal to that event."""
        events = [
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T15:00:00+00:00",
                value_numeric=4200.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 1
        assert rows[0][0] == 4200.0

        meta = json.loads(rows[0][1])
        assert meta["readings"] == 1
        assert meta["goal_pct"] == pytest.approx(4200.0 / 8000 * 100, abs=0.1)

    def test_value_json_contains_required_fields(self, db):
        """Verify value_json contains total_steps (via value_numeric), goal_pct, and goal."""
        events = [
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T09:00:00+00:00",
                value_numeric=2000.0,
            ),
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T16:00:00+00:00",
                value_numeric=6000.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 1

        meta = json.loads(rows[0][1])
        assert "readings" in meta
        assert "goal" in meta
        assert "goal_pct" in meta
        assert meta["goal"] == 8000
        assert meta["goal_pct"] == 100.0
        # value_numeric holds the total
        assert rows[0][0] == 8000.0

    def test_null_value_numeric_ignored(self, db):
        """Step events with NULL value_numeric should be excluded from SUM."""
        events = [
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=3000.0,
            ),
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                value_numeric=None,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 1
        assert rows[0][0] == 3000.0

    def test_custom_step_goal(self, db):
        """Custom step_goal should affect goal_pct calculation."""
        events = [
            _make_event(
                "body.steps",
                "step_count",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                value_numeric=5000.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        config = _body_config().copy()
        config["step_goal"] = 10000
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "daily_step_total")
        assert len(rows) == 1
        meta = json.loads(rows[0][1])
        assert meta["goal"] == 10000
        assert meta["goal_pct"] == 50.0


# ──────────────────────────────────────────────────────────────
# TestCaffeineLevel
# ──────────────────────────────────────────────────────────────


class TestCaffeineLevel:
    """Tests for body.derived/caffeine_level."""

    def test_single_intake_decay(self, db):
        """A single 200mg intake in the morning should decay by end-of-day."""
        # Intake at 08:00 UTC on the test date
        events = [
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T08:00:00+00:00",
                value_numeric=200.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "caffeine_level")
        assert len(rows) == 1

        # Hours from 08:00 to 23:59 = ~15.98 hours
        # remaining = 200 * 0.5^(15.98/5.0)
        hours_elapsed = (23 * 60 + 59 - 8 * 60) / 60.0  # 15.983...
        expected = 200.0 * (0.5 ** (hours_elapsed / 5.0))
        expected = round(expected, 1)

        assert rows[0][0] == pytest.approx(expected, abs=0.2)

        meta = json.loads(rows[0][1])
        assert meta["intakes_today"] == 1
        assert meta["total_ingested_mg"] == 200.0
        assert meta["half_life_hours"] == 5.0

    def test_no_caffeine_no_event(self, db):
        """No caffeine intake events should produce no derived caffeine event."""
        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "caffeine_level")
        assert len(rows) == 0

    def test_multiple_doses_additive_decay(self, db):
        """Multiple caffeine intakes should produce additive remaining amounts."""
        events = [
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T08:00:00+00:00",
                value_numeric=100.0,
            ),
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                value_numeric=150.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "caffeine_level")
        assert len(rows) == 1

        half_life = 5.0
        # 08:00 -> 23:59 = 15.9833h
        hours1 = (23 * 60 + 59 - 8 * 60) / 60.0
        remaining1 = 100.0 * (0.5 ** (hours1 / half_life))
        # 14:00 -> 23:59 = 9.9833h
        hours2 = (23 * 60 + 59 - 14 * 60) / 60.0
        remaining2 = 150.0 * (0.5 ** (hours2 / half_life))
        expected = round(remaining1 + remaining2, 1)

        assert rows[0][0] == pytest.approx(expected, abs=0.2)

        meta = json.loads(rows[0][1])
        assert meta["intakes_today"] == 2
        assert meta["total_ingested_mg"] == 250.0

    def test_custom_half_life(self, db):
        """Custom caffeine_half_life_hours from config should be used."""
        events = [
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                value_numeric=200.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        config = _body_config().copy()
        config["caffeine_half_life_hours"] = 3.0
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "caffeine_level")
        assert len(rows) == 1

        # 12:00 -> 23:59 = 11.9833h elapsed, half-life=3.0
        hours_elapsed = (23 * 60 + 59 - 12 * 60) / 60.0
        expected = round(200.0 * (0.5 ** (hours_elapsed / 3.0)), 1)
        assert rows[0][0] == pytest.approx(expected, abs=0.2)

        meta = json.loads(rows[0][1])
        assert meta["half_life_hours"] == 3.0

    def test_caffeine_value_json_fields(self, db):
        """Verify value_json contains intakes_today, total_ingested_mg, half_life_hours."""
        events = [
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T09:00:00+00:00",
                value_numeric=80.0,
            ),
            _make_event(
                "body.caffeine",
                "intake",
                timestamp_utc=f"{DATE}T15:00:00+00:00",
                value_numeric=120.0,
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "caffeine_level")
        assert len(rows) == 1
        meta = json.loads(rows[0][1])
        assert "intakes_today" in meta
        assert "total_ingested_mg" in meta
        assert "half_life_hours" in meta
        assert meta["intakes_today"] == 2
        assert meta["total_ingested_mg"] == 200.0
        assert meta["half_life_hours"] == 5.0


# ──────────────────────────────────────────────────────────────
# TestSleepDuration
# ──────────────────────────────────────────────────────────────


class TestSleepDuration:
    """Tests for body.derived/sleep_duration."""

    def test_normal_8h_sleep(self, db):
        """A sleep_start at 23:00 day-1 and sleep_end at 07:00 today yields 8h."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"2026-03-19T23:00:00+00:00",
                timestamp_local=f"2026-03-19T18:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T07:00:00+00:00",
                timestamp_local=f"{DATE}T02:00:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        assert len(rows) == 1
        assert rows[0][0] == 8.0

        meta = json.loads(rows[0][1])
        assert meta["duration_min"] == 480.0
        assert meta["target_hours"] == 7.5
        assert meta["delta_hours"] == 0.5

    def test_unpaired_start_no_event(self, db):
        """A sleep_start without a matching sleep_end should not produce a duration."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"2026-03-19T23:00:00+00:00",
                timestamp_local=f"2026-03-19T18:00:00-05:00",
                value_text="sleep_start",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        assert len(rows) == 0

    def test_sanity_reject_over_24h(self, db):
        """A sleep pair spanning >24h should be rejected by the sanity check."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"2026-03-19T00:00:00+00:00",
                timestamp_local=f"2026-03-18T19:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T06:00:00+00:00",
                timestamp_local=f"{DATE}T01:00:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        # 30 hours > 24, so should be rejected
        assert len(rows) == 0

    def test_short_nap_duration(self, db):
        """A 1.5h nap within the same day should produce a valid duration."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T14:30:00+00:00",
                timestamp_local=f"{DATE}T09:30:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        assert len(rows) == 1
        assert rows[0][0] == 1.5

    def test_sleep_value_json_contains_duration_hours(self, db):
        """Verify value_json contains duration_min, target_hours, delta_hours."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"2026-03-19T22:00:00+00:00",
                timestamp_local=f"2026-03-19T17:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T05:00:00+00:00",
                timestamp_local=f"{DATE}T00:00:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        assert len(rows) == 1
        # 7 hours sleep
        assert rows[0][0] == 7.0

        meta = json.loads(rows[0][1])
        assert "duration_min" in meta
        assert "target_hours" in meta
        assert "delta_hours" in meta
        assert meta["duration_min"] == 420.0
        assert meta["target_hours"] == 7.5
        assert meta["delta_hours"] == -0.5

    def test_multiple_sleep_periods_last_pair(self, db):
        """Multiple start/end pairs: the algorithm pairs each start with next end, resetting."""
        # Two separate sleep periods: a nap and overnight sleep
        events = [
            # Nap: previous day 14:00-15:30 (won't be included - outside date range)
            # Overnight: start 2026-03-19T23:00, end 2026-03-20T06:00 = 7h
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"2026-03-19T23:00:00+00:00",
                timestamp_local=f"2026-03-19T18:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T06:00:00+00:00",
                timestamp_local=f"{DATE}T01:00:00-05:00",
                value_text="sleep_end",
            ),
            # Afternoon nap on the same day: 13:00-14:00 = 1h
            _make_event(
                "body.sleep",
                "sleep_start",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_text="sleep_start",
            ),
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T14:00:00+00:00",
                timestamp_local=f"{DATE}T09:00:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        # The algorithm pairs each start->end, resetting after each pair
        # So we should get two sleep_duration events (but both have same
        # timestamp_utc=DAY_TS so INSERT OR REPLACE keeps only the last one)
        # Actually, both events have the same event_id hash since they share
        # source_module, event_type, and timestamp_utc. The second overwrites the first.
        assert len(rows) >= 1

    def test_sleep_end_without_start_ignored(self, db):
        """A sleep_end event without a preceding sleep_start should produce no duration."""
        events = [
            _make_event(
                "body.sleep",
                "sleep_end",
                timestamp_utc=f"{DATE}T07:00:00+00:00",
                timestamp_local=f"{DATE}T02:00:00-05:00",
                value_text="sleep_end",
            ),
        ]
        db.insert_events_for_module("body", events)

        mod = create_module(_body_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "sleep_duration")
        assert len(rows) == 0
