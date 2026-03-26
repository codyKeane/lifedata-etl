"""
Tests for MindModule.post_ingest() derived metrics.

Derived metrics tested:
  - mind.derived/subjective_day_score: weighted composite
  - mind.derived/mood_trend_7d: 7-day rolling average
  - mind.derived/energy_stability: coefficient of variation over 7 days
"""

import json
import statistics

import pytest

from core.event import Event
from modules.mind import create_module

DATE = "2026-03-20"
DAY_TS = f"{DATE}T23:59:00+00:00"

CONFIG = {
    "lifedata": {
        "modules": {
            "mind": {
                "enabled": True,
            }
        }
    }
}


def _mind_config() -> dict:
    return CONFIG["lifedata"]["modules"]["mind"]


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
        WHERE source_module = 'mind.derived'
          AND event_type = ?
          AND timestamp_utc = ?
        """,
        (event_type, DAY_TS),
    ).fetchall()
    return rows


# ──────────────────────────────────────────────────────────────
# TestSubjectiveDayScore
# ──────────────────────────────────────────────────────────────


class TestSubjectiveDayScore:
    """Tests for mind.derived/subjective_day_score."""

    def test_all_components(self, db):
        """All five score components present yields correct weighted composite."""
        events = [
            _make_event(
                "mind.mood",
                "check_in",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_numeric=7.0,
            ),
            _make_event(
                "mind.energy",
                "check_in",
                timestamp_local=f"{DATE}T08:05:00-05:00",
                timestamp_utc=f"{DATE}T13:05:00+00:00",
                value_numeric=6.0,
            ),
            _make_event(
                "mind.stress",
                "check_in",
                timestamp_local=f"{DATE}T08:10:00-05:00",
                timestamp_utc=f"{DATE}T13:10:00+00:00",
                value_numeric=3.0,
            ),
            _make_event(
                "mind.productivity",
                "check_in",
                timestamp_local=f"{DATE}T18:00:00-05:00",
                timestamp_utc=f"{DATE}T23:00:00+00:00",
                value_numeric=8.0,
            ),
            _make_event(
                "mind.sleep",
                "check_in",
                timestamp_local=f"{DATE}T08:01:00-05:00",
                timestamp_utc=f"{DATE}T13:01:00+00:00",
                value_numeric=7.0,
            ),
        ]
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "subjective_day_score")
        assert len(rows) == 1

        # mood=7*0.3, energy=6*0.2, stress=(10-3)*0.15=1.05,
        # productivity=8*0.2, sleep=7*0.15
        # weighted_sum = 2.1 + 1.2 + 1.05 + 1.6 + 1.05 = 7.0
        # total_weight = 0.3 + 0.2 + 0.15 + 0.2 + 0.15 = 1.0
        # day_score = 7.0 / 1.0 = 7.0
        expected = round(
            (7.0 * 0.3 + 6.0 * 0.2 + (10.0 - 3.0) * 0.15 + 8.0 * 0.2 + 7.0 * 0.15)
            / (0.3 + 0.2 + 0.15 + 0.2 + 0.15),
            2,
        )
        assert rows[0][0] == pytest.approx(expected, abs=0.01)

    def test_missing_components(self, db):
        """Only mood and energy present; score uses available weights only."""
        events = [
            _make_event(
                "mind.mood",
                "check_in",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_numeric=7.0,
            ),
            _make_event(
                "mind.energy",
                "check_in",
                timestamp_local=f"{DATE}T08:05:00-05:00",
                timestamp_utc=f"{DATE}T13:05:00+00:00",
                value_numeric=6.0,
            ),
        ]
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "subjective_day_score")
        assert len(rows) == 1

        # mood=7*0.3, energy=6*0.2
        # weighted_sum = 2.1 + 1.2 = 3.3
        # total_weight = 0.3 + 0.2 = 0.5
        # day_score = 3.3 / 0.5 = 6.6
        expected = round((7.0 * 0.3 + 6.0 * 0.2) / (0.3 + 0.2), 2)
        assert rows[0][0] == pytest.approx(expected, abs=0.01)

    def test_no_data_no_event(self, db):
        """No check-in events should produce no day score event."""
        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "subjective_day_score")
        assert len(rows) == 0


# ──────────────────────────────────────────────────────────────
# TestMoodTrend7d
# ──────────────────────────────────────────────────────────────


class TestMoodTrend7d:
    """Tests for mind.derived/mood_trend_7d."""

    def test_seven_days_average(self, db):
        """7 days of mood check-ins produce a correct rolling average."""
        events = []
        mood_values = [5.0, 6.0, 7.0, 8.0, 6.0, 7.0, 7.0]
        for i, mood in enumerate(mood_values):
            day_offset = i - 6  # days from -6 to 0 relative to DATE
            day_str = f"2026-03-{20 + day_offset:02d}"
            events.append(
                _make_event(
                    "mind.mood",
                    "check_in",
                    timestamp_utc=f"{day_str}T13:00:00+00:00",
                    timestamp_local=f"{day_str}T08:00:00-05:00",
                    value_numeric=mood,
                )
            )
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "mood_trend_7d")
        assert len(rows) == 1

        expected_avg = round(statistics.mean(mood_values), 2)
        assert rows[0][0] == pytest.approx(expected_avg, abs=0.01)

        meta = json.loads(rows[0][1])
        assert meta["days_in_window"] == 7

    def test_insufficient_data_still_produces(self, db):
        """Even 1 day of mood data produces a trend (with lower confidence)."""
        events = [
            _make_event(
                "mind.mood",
                "check_in",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_numeric=7.0,
            ),
        ]
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "mood_trend_7d")
        assert len(rows) == 1
        assert rows[0][0] == 7.0

        meta = json.loads(rows[0][1])
        assert meta["days_in_window"] == 1


# ──────────────────────────────────────────────────────────────
# TestEnergyStability
# ──────────────────────────────────────────────────────────────


class TestEnergyStability:
    """Tests for mind.derived/energy_stability."""

    def test_stable_energy_low_cv(self, db):
        """Identical energy values across 7 days should yield CV = 0."""
        events = []
        for i in range(7):
            day_offset = i - 6
            day_str = f"2026-03-{20 + day_offset:02d}"
            events.append(
                _make_event(
                    "mind.energy",
                    "check_in",
                    timestamp_utc=f"{day_str}T13:00:00+00:00",
                    timestamp_local=f"{day_str}T08:00:00-05:00",
                    value_numeric=6.0,
                )
            )
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "energy_stability")
        assert len(rows) == 1
        assert rows[0][0] == 0.0

    def test_variable_energy_high_cv(self, db):
        """Varying energy values should yield a positive CV."""
        energy_values = [3.0, 8.0, 4.0, 9.0, 2.0, 7.0, 5.0]
        events = []
        for i, energy in enumerate(energy_values):
            day_offset = i - 6
            day_str = f"2026-03-{20 + day_offset:02d}"
            events.append(
                _make_event(
                    "mind.energy",
                    "check_in",
                    timestamp_utc=f"{day_str}T13:00:00+00:00",
                    timestamp_local=f"{day_str}T08:00:00-05:00",
                    value_numeric=energy,
                )
            )
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "energy_stability")
        assert len(rows) == 1

        e_mean = statistics.mean(energy_values)
        e_stdev = statistics.stdev(energy_values)
        expected_cv = round((e_stdev / e_mean) * 100, 1)

        assert rows[0][0] == pytest.approx(expected_cv, abs=0.2)
        assert rows[0][0] > 0

        meta = json.loads(rows[0][1])
        assert meta["days_in_window"] == 7

    def test_fewer_than_two_values_no_event(self, db):
        """With only 1 day of energy data, no stability event is produced."""
        events = [
            _make_event(
                "mind.energy",
                "check_in",
                timestamp_local=f"{DATE}T08:00:00-05:00",
                value_numeric=6.0,
            ),
        ]
        db.insert_events_for_module("mind", events)

        mod = create_module(_mind_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "energy_stability")
        assert len(rows) == 0
