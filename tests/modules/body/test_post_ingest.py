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
