"""
Tests for modules/cognition/module.py — post_ingest() derived cognitive metrics.

Covers all 5 derived metrics:
  1. cognition.reaction.derived / daily_baseline
  2. cognition.derived / cognitive_load_index
  3. cognition.derived / impairment_flag
  4. cognition.derived / peak_cognition_hour
  5. cognition.derived / subjective_objective_gap
"""

import json

from core.event import Event
from modules.cognition import create_module


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

TARGET_DATE = "2026-03-20"
DERIVED_TS = f"{TARGET_DATE}T23:59:00+00:00"

MODULE_CONFIG = {
    "enabled": True,
    "baseline_window_days": 14,
    "impairment_zscore_threshold": 2.0,
}


def _make_rt_event(date_str: str, rt_ms: float, hour: int = 13) -> Event:
    """Create a simple_rt event on the given date at the given hour (UTC)."""
    ts = f"{date_str}T{hour:02d}:00:00+00:00"
    return Event(
        timestamp_utc=ts,
        timestamp_local=ts,
        timezone_offset="-0500",
        source_module="cognition.reaction",
        event_type="simple_rt",
        value_numeric=rt_ms,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _make_digit_span_event(date_str: str, span: float) -> Event:
    ts = f"{date_str}T13:00:00+00:00"
    return Event(
        timestamp_utc=ts,
        timestamp_local=ts,
        timezone_offset="-0500",
        source_module="cognition.memory",
        event_type="digit_span",
        value_numeric=span,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _make_time_production_event(date_str: str, produced: float, target: float = 5.0) -> Event:
    error_pct = ((produced - target) / target) * 100
    ts = f"{date_str}T13:00:00+00:00"
    return Event(
        timestamp_utc=ts,
        timestamp_local=ts,
        timezone_offset="-0500",
        source_module="cognition.time",
        event_type="production",
        value_numeric=produced,
        value_json=json.dumps({
            "target_seconds": target,
            "produced_seconds": produced,
            "error_pct": error_pct,
        }),
        confidence=1.0,
        parser_version="1.0.0",
    )


def _make_typing_event(date_str: str, wpm: float) -> Event:
    ts = f"{date_str}T13:00:00+00:00"
    return Event(
        timestamp_utc=ts,
        timestamp_local=ts,
        timezone_offset="-0500",
        source_module="cognition.typing",
        event_type="speed_test",
        value_numeric=wpm,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _make_energy_event(date_str: str, value: float) -> Event:
    ts = f"{date_str}T13:00:00+00:00"
    return Event(
        timestamp_utc=ts,
        timestamp_local=ts,
        timezone_offset="-0500",
        source_module="mind.energy",
        event_type="energy",
        value_numeric=value,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _insert_baseline_rt(db, days: int = 14, base_rt: float = 250.0, spread: float = 10.0):
    """Insert 14 days of RT data before TARGET_DATE for baseline computation."""
    events = []
    for day_offset in range(1, days + 1):
        # date goes backwards from target
        from datetime import date, timedelta
        d = date(2026, 3, 20) - timedelta(days=day_offset)
        date_str = d.isoformat()
        # Insert 3 trials per day with some variation
        for trial in range(3):
            rt = base_rt + (trial - 1) * spread + (day_offset % 3) * 5
            events.append(_make_rt_event(date_str, rt))
    db.insert_events_for_module("cognition", events)
    return events


def _insert_baseline_all_components(db, days: int = 14):
    """Insert baseline data for all 4 cognitive components."""
    from datetime import date, timedelta
    events = []
    for day_offset in range(1, days + 1):
        d = date(2026, 3, 20) - timedelta(days=day_offset)
        date_str = d.isoformat()
        # RT: ~250ms
        for trial in range(3):
            events.append(_make_rt_event(date_str, 250.0 + (trial - 1) * 10))
        # Digit span: ~7
        events.append(_make_digit_span_event(date_str, 7.0 + (day_offset % 3) - 1))
        # Time production: ~5.2s target 5s
        events.append(_make_time_production_event(date_str, 5.0 + (day_offset % 3) * 0.1))
        # Typing: ~65 WPM
        events.append(_make_typing_event(date_str, 65.0 + (day_offset % 3) * 2))
    db.insert_events_for_module("cognition", events)
    return events


def _query_derived(db, source_module: str, event_type: str, date_str: str = TARGET_DATE):
    """Query derived events from the database."""
    rows = db.execute(
        """
        SELECT value_numeric, value_json
        FROM events
        WHERE source_module = ?
          AND event_type = ?
          AND date(timestamp_utc) = ?
        """,
        (source_module, event_type, date_str),
    )
    result = rows.fetchall() if hasattr(rows, "fetchall") else list(rows)
    return result


# ──────────────────────────────────────────────────────────────
# 1. TestDailyBaseline
# ──────────────────────────────────────────────────────────────


class TestDailyBaseline:
    """cognition.reaction.derived / daily_baseline — median RT per day + trend."""

    def test_baseline_from_multiple_trials(self, db):
        """Multiple RT events on TARGET_DATE produce a baseline with correct median."""
        events = [
            _make_rt_event(TARGET_DATE, 240.0),
            _make_rt_event(TARGET_DATE, 260.0),
            _make_rt_event(TARGET_DATE, 250.0),
        ]
        db.insert_events_for_module("cognition", events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.reaction.derived", "daily_baseline")
        assert len(rows) == 1
        value_numeric = rows[0][0]
        # Median of [240, 250, 260] = 250
        assert value_numeric == 250.0

    def test_baseline_contains_trend(self, db):
        """Baseline value_json includes trend_7d and n_trials."""
        # Insert 7 days of data for trend calculation
        _insert_baseline_rt(db, days=7, base_rt=250.0)
        # Target day
        events = [
            _make_rt_event(TARGET_DATE, 245.0),
            _make_rt_event(TARGET_DATE, 255.0),
        ]
        db.insert_events_for_module("cognition", events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.reaction.derived", "daily_baseline")
        assert len(rows) == 1
        payload = json.loads(rows[0][1])
        assert "trend_7d" in payload
        assert "n_trials" in payload
        assert payload["n_trials"] == 2
        assert isinstance(payload["trend_7d"], list)
        assert len(payload["trend_7d"]) > 0

    def test_no_rt_events_produces_no_baseline(self, db):
        """No RT events on the target date means no daily_baseline derived event."""
        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.reaction.derived", "daily_baseline")
        assert len(rows) == 0

    def test_single_trial_uses_value_as_median(self, db):
        """A single RT trial should produce a baseline with that trial as median."""
        db.insert_events_for_module("cognition", [_make_rt_event(TARGET_DATE, 300.0)])

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.reaction.derived", "daily_baseline")
        assert len(rows) == 1
        assert rows[0][0] == 300.0


# ──────────────────────────────────────────────────────────────
# 2. TestCognitiveLoadIndex
# ──────────────────────────────────────────────────────────────


class TestCognitiveLoadIndex:
    """cognition.derived / cognitive_load_index — weighted z-score composite."""

    def test_all_four_components(self, db):
        """CLI computed with all 4 components: RT, memory, time, typing."""
        _insert_baseline_all_components(db, days=14)

        # Target day: all components present
        target_events = [
            _make_rt_event(TARGET_DATE, 260.0),
            _make_rt_event(TARGET_DATE, 270.0),
            _make_rt_event(TARGET_DATE, 265.0),
            _make_digit_span_event(TARGET_DATE, 7.0),
            _make_time_production_event(TARGET_DATE, 5.2),
            _make_typing_event(TARGET_DATE, 65.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "cognitive_load_index")
        assert len(rows) == 1
        cli_value = rows[0][0]
        assert isinstance(cli_value, float)

        payload = json.loads(rows[0][1])
        assert payload["n_components"] == 4
        assert "rt" in payload["components"]
        assert "memory" in payload["components"]
        assert "time" in payload["components"]
        assert "typing" in payload["components"]

    def test_single_component_only(self, db):
        """CLI should still compute with just one component (RT only)."""
        _insert_baseline_rt(db, days=14, base_rt=250.0)

        # Target day: only RT
        target_events = [
            _make_rt_event(TARGET_DATE, 280.0),
            _make_rt_event(TARGET_DATE, 290.0),
            _make_rt_event(TARGET_DATE, 285.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "cognitive_load_index")
        assert len(rows) == 1
        payload = json.loads(rows[0][1])
        assert payload["n_components"] == 1
        assert "rt" in payload["components"]

    def test_no_data_returns_no_event(self, db):
        """No cognitive data at all means no CLI event."""
        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "cognitive_load_index")
        assert len(rows) == 0

    def test_weights_present_in_payload(self, db):
        """CLI payload includes correct weights for each component."""
        _insert_baseline_all_components(db, days=14)
        target_events = [
            _make_rt_event(TARGET_DATE, 250.0),
            _make_rt_event(TARGET_DATE, 250.0),
            _make_rt_event(TARGET_DATE, 250.0),
            _make_digit_span_event(TARGET_DATE, 7.0),
            _make_time_production_event(TARGET_DATE, 5.1),
            _make_typing_event(TARGET_DATE, 65.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "cognitive_load_index")
        payload = json.loads(rows[0][1])
        assert payload["weights"]["rt"] == 0.3
        assert payload["weights"]["memory"] == 0.3
        assert payload["weights"]["time"] == 0.2
        assert payload["weights"]["typing"] == 0.2


# ──────────────────────────────────────────────────────────────
# 3. TestImpairmentFlag
# ──────────────────────────────────────────────────────────────


class TestImpairmentFlag:
    """cognition.derived / impairment_flag — 1 if CLI z-score > threshold."""

    def test_impaired_day(self, db):
        """Extremely high RT on target day produces impairment_flag=1."""
        _insert_baseline_all_components(db, days=14)

        # Also need prior CLI values as baseline for impairment.
        # Run post_ingest for prior dates to create CLI history.
        from datetime import date, timedelta
        prior_dates = set()
        for day_offset in range(1, 15):
            d = date(2026, 3, 20) - timedelta(days=day_offset)
            prior_dates.add(d.isoformat())

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates=prior_dates)

        # Now insert impaired target-day data: very slow RT, low memory, bad timing, slow typing
        target_events = [
            _make_rt_event(TARGET_DATE, 500.0),
            _make_rt_event(TARGET_DATE, 520.0),
            _make_rt_event(TARGET_DATE, 510.0),
            _make_digit_span_event(TARGET_DATE, 3.0),
            _make_time_production_event(TARGET_DATE, 8.0),  # 60% error from target 5
            _make_typing_event(TARGET_DATE, 35.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "impairment_flag", TARGET_DATE)
        assert len(rows) == 1
        assert rows[0][0] == 1.0
        payload = json.loads(rows[0][1])
        assert payload["cli_zscore"] > 2.0
        assert payload["threshold"] == 2.0

    def test_normal_day(self, db):
        """Normal performance on target day produces impairment_flag=0."""
        _insert_baseline_all_components(db, days=14)

        from datetime import date, timedelta
        prior_dates = set()
        for day_offset in range(1, 15):
            d = date(2026, 3, 20) - timedelta(days=day_offset)
            prior_dates.add(d.isoformat())

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates=prior_dates)

        # Normal target-day data, close to baseline
        target_events = [
            _make_rt_event(TARGET_DATE, 252.0),
            _make_rt_event(TARGET_DATE, 248.0),
            _make_rt_event(TARGET_DATE, 250.0),
            _make_digit_span_event(TARGET_DATE, 7.0),
            _make_time_production_event(TARGET_DATE, 5.1),
            _make_typing_event(TARGET_DATE, 66.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "impairment_flag", TARGET_DATE)
        assert len(rows) == 1
        assert rows[0][0] == 0.0

    def test_insufficient_baseline_no_flag(self, db):
        """Fewer than 3 days of CLI history means no impairment_flag event."""
        # Only 2 days of baseline
        _insert_baseline_all_components(db, days=2)

        from datetime import date, timedelta
        prior_dates = set()
        for day_offset in range(1, 3):
            d = date(2026, 3, 20) - timedelta(days=day_offset)
            prior_dates.add(d.isoformat())

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates=prior_dates)

        # Target day
        target_events = [
            _make_rt_event(TARGET_DATE, 500.0),
            _make_rt_event(TARGET_DATE, 520.0),
            _make_rt_event(TARGET_DATE, 510.0),
            _make_digit_span_event(TARGET_DATE, 3.0),
            _make_time_production_event(TARGET_DATE, 8.0),
            _make_typing_event(TARGET_DATE, 35.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "impairment_flag", TARGET_DATE)
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# 4. TestPeakCognitionHour
# ──────────────────────────────────────────────────────────────


class TestPeakCognitionHour:
    """cognition.derived / peak_cognition_hour — hour with lowest avg RT."""

    def test_morning_lowest_rt(self, db):
        """Morning hours (09:xx UTC) with lowest RT should be identified as peak."""
        from datetime import date, timedelta
        events = []
        for day_offset in range(0, 14):
            d = date(2026, 3, 20) - timedelta(days=day_offset)
            date_str = d.isoformat()
            # Morning (hour 9): fast RT
            for _ in range(3):
                events.append(_make_rt_event(date_str, 220.0, hour=9))
            # Afternoon (hour 15): slower RT
            for _ in range(3):
                events.append(_make_rt_event(date_str, 320.0, hour=15))

        db.insert_events_for_module("cognition", events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "peak_cognition_hour")
        assert len(rows) == 1
        assert rows[0][0] == 9.0  # hour 9 has lowest avg RT

        payload = json.loads(rows[0][1])
        assert payload["best_avg_rt_ms"] == 220.0
        assert payload["window_days"] == 14

    def test_insufficient_trials_no_peak(self, db):
        """Fewer than 3 trials per hour means no peak_cognition_hour event."""
        # Only 2 trials at one hour — below the HAVING COUNT(*) >= 3 threshold
        events = [
            _make_rt_event(TARGET_DATE, 220.0, hour=9),
            _make_rt_event(TARGET_DATE, 230.0, hour=9),
        ]
        db.insert_events_for_module("cognition", events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "peak_cognition_hour")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# 5. TestSubjectiveObjectiveGap
# ──────────────────────────────────────────────────────────────


class TestSubjectiveObjectiveGap:
    """cognition.derived / subjective_objective_gap — self-report vs probes."""

    def test_aligned_high_energy_fast_rt(self, db):
        """High subjective energy + fast RT produces a gap event."""
        # Baseline RT for comparison
        _insert_baseline_rt(db, days=14, base_rt=250.0)

        # Target day: high energy + fast RT
        target_events = [
            _make_energy_event(TARGET_DATE, 8.0),
            _make_rt_event(TARGET_DATE, 230.0),
            _make_rt_event(TARGET_DATE, 225.0),
            _make_rt_event(TARGET_DATE, 228.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "subjective_objective_gap")
        assert len(rows) == 1

        gap_value = rows[0][0]
        assert isinstance(gap_value, float)

        payload = json.loads(rows[0][1])
        assert "subjective_mean" in payload
        assert "subjective_z" in payload
        assert "objective_z" in payload
        # High energy (8/10) -> positive subjective_z
        assert payload["subjective_z"] > 0
        # Fast RT (below baseline) -> positive objective_z (inverted)
        assert payload["objective_z"] > 0

    def test_no_subjective_data_no_gap(self, db):
        """Without mind/energy events, no gap event is produced."""
        _insert_baseline_rt(db, days=14, base_rt=250.0)

        # Only RT on target day, no mind.energy
        target_events = [
            _make_rt_event(TARGET_DATE, 240.0),
            _make_rt_event(TARGET_DATE, 245.0),
            _make_rt_event(TARGET_DATE, 242.0),
        ]
        db.insert_events_for_module("cognition", target_events)

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "subjective_objective_gap")
        assert len(rows) == 0

    def test_no_rt_data_no_gap(self, db):
        """Without RT events on target day, no gap event is produced."""
        # Energy but no RT on target day
        db.insert_events_for_module("cognition", [_make_energy_event(TARGET_DATE, 7.0)])

        mod = create_module(MODULE_CONFIG)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = _query_derived(db, "cognition.derived", "subjective_objective_gap")
        assert len(rows) == 0
