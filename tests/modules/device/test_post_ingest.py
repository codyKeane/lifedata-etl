"""
Tests for DeviceModule.post_ingest() derived metric computation.

Covers:
  - device.derived/screen_time_minutes — from consecutive screen_on timestamps
  - device.derived/battery_drain_rate — %/hour during non-charging periods
  - device.derived/charging_duration — total minutes on charger
"""

import json
from datetime import UTC

from core.event import Event
from modules.device import create_module

TARGET_DATE = "2026-03-20"
TZ_OFFSET = "-0500"


def _device_config():
    return {"enabled": True}


def _make_event(source_module, event_type, value_numeric=None, value_text=None,
                minute_offset=0):
    """Build a device event at a known timestamp on TARGET_DATE."""
    from datetime import datetime, timedelta

    dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=UTC) + timedelta(minutes=minute_offset)
    ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ts_local = (dt - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=TZ_OFFSET,
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        confidence=1.0,
        parser_version="1.0.0",
    )


# ────────────────────────────────────────────────────────────
# Screen Time Minutes
# ────────────────────────────────────────────────────────────


class TestScreenTimeMinutes:
    """device.derived/screen_time_minutes — inter-unlock gap estimation."""

    def test_multiple_unlocks_calculate_total(self, db):
        """3 screen_on events 5 min apart → screen_time derived event."""
        mod = create_module(_device_config())

        # 3 unlocks, 5 minutes apart
        events = [
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=i * 5)
            for i in range(3)
        ]
        db.insert_events_for_module("device_screen", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="screen_time_minutes")
        assert len(rows) == 1
        row = rows[0]
        # Two gaps of 5 min each = 10 min, plus avg session added for last unlock
        assert row["value_numeric"] is not None
        assert row["value_numeric"] > 0

        data = json.loads(row["value_json"])
        assert data["sessions"] == 3
        assert data["method"] == "inter_unlock_gap_capped"

    def test_single_unlock_no_event(self, db):
        """A single screen_on cannot compute inter-unlock gaps."""
        mod = create_module(_device_config())

        events = [
            _make_event("device.screen", "screen_on", value_text="on"),
        ]
        db.insert_events_for_module("device_screen", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="screen_time_minutes")
        assert len(rows) == 0

    def test_large_gap_capped_at_10_minutes(self, db):
        """Gaps longer than 10 minutes are capped at 10 min per session."""
        mod = create_module(_device_config())

        # 2 unlocks 60 minutes apart → gap capped at 10 min
        events = [
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=0),
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=60),
        ]
        db.insert_events_for_module("device_screen", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="screen_time_minutes")
        assert len(rows) == 1
        # 1 gap of 60 min capped to 10 + avg session (10 min) capped to 10 = 20
        assert rows[0]["value_numeric"] <= 20.0


# ────────────────────────────────────────────────────────────
# Battery Drain Rate
# ────────────────────────────────────────────────────────────


class TestBatteryDrainRate:
    """device.derived/battery_drain_rate — %/hour during non-charging periods."""

    def test_decreasing_battery_positive_drain(self, db):
        """Battery dropping from 90% to 80% over 2 hours → positive drain rate."""
        mod = create_module(_device_config())

        # Battery readings: 90% at t=0, 80% at t=120min (2 hours)
        events = [
            _make_event("device.battery", "pulse", value_numeric=90.0,
                        minute_offset=0),
            _make_event("device.battery", "pulse", value_numeric=80.0,
                        minute_offset=120),
        ]
        db.insert_events_for_module("device_battery", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="battery_drain_rate")
        assert len(rows) == 1
        row = rows[0]
        # 10% over 2 hours = 5%/hr
        assert row["value_numeric"] == 5.0

        data = json.loads(row["value_json"])
        assert data["unit"] == "pct_per_hour"
        assert data["segments_analyzed"] == 1

    def test_no_battery_data_no_event(self, db):
        """With no battery pulses, no drain rate event is produced."""
        mod = create_module(_device_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="battery_drain_rate")
        assert len(rows) == 0

    def test_increasing_battery_no_drain(self, db):
        """Battery increasing (charging) does not produce a drain segment."""
        mod = create_module(_device_config())

        # Battery rising: 50% → 80% (charging, but no charge_start/stop events)
        events = [
            _make_event("device.battery", "pulse", value_numeric=50.0,
                        minute_offset=0),
            _make_event("device.battery", "pulse", value_numeric=80.0,
                        minute_offset=120),
        ]
        db.insert_events_for_module("device_battery", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="battery_drain_rate")
        # pct2 > pct1 so no drain segment; no event produced
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Charging Duration
# ────────────────────────────────────────────────────────────


class TestChargingDuration:
    """device.derived/charging_duration — total minutes on charger."""

    def test_start_stop_pair(self, db):
        """A charge_start followed by charge_stop produces a duration event."""
        mod = create_module(_device_config())

        events = [
            _make_event("device.charging", "charge_start", value_numeric=45.0,
                        minute_offset=0),
            _make_event("device.charging", "charge_stop", value_numeric=90.0,
                        minute_offset=120),
        ]
        db.insert_events_for_module("device_charging", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="charging_duration")
        assert len(rows) == 1
        row = rows[0]
        # 120 minutes of charging
        assert row["value_numeric"] == 120.0

        data = json.loads(row["value_json"])
        assert data["sessions"] == 1
        assert data["total_pct_gained"] == 45.0  # 90 - 45

    def test_no_charging_no_event(self, db):
        """Without charging events, no charging_duration is produced."""
        mod = create_module(_device_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="charging_duration")
        assert len(rows) == 0

    def test_orphan_charge_stop_ignored(self, db):
        """A charge_stop without a preceding charge_start produces no duration."""
        mod = create_module(_device_config())

        events = [
            _make_event("device.charging", "charge_stop", value_numeric=90.0,
                        minute_offset=60),
        ]
        db.insert_events_for_module("device_charging", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="charging_duration")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Disabled Metrics
# ────────────────────────────────────────────────────────────


class TestDisabledMetrics:
    """Verify disabled_metrics config prevents derived metric computation."""

    def test_disable_screen_time_skips_computation(self, db):
        """Disabling screen_time_minutes produces no screen time event."""
        cfg = {"enabled": True, "disabled_metrics": ["device.derived:screen_time_minutes"]}
        mod = create_module(cfg)

        events = [
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=i * 5)
            for i in range(3)
        ]
        db.insert_events_for_module("device_screen", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="screen_time_minutes")
        assert len(rows) == 0

        # Other derived metrics should still compute
        unlock_rows = db.query_events(source_module="device.derived",
                                      event_type="unlock_count")
        assert len(unlock_rows) == 1

    def test_disable_all_derived_via_prefix(self, db):
        """Disabling 'device.derived' skips all derived metrics."""
        cfg = {"enabled": True, "disabled_metrics": ["device.derived"]}
        mod = create_module(cfg)

        events = [
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=i * 5)
            for i in range(3)
        ]
        events.append(
            _make_event("device.battery", "pulse", value_numeric=90.0,
                        minute_offset=0),
        )
        db.insert_events_for_module("device_all", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        # No derived events should exist
        all_derived = db.query_events(source_module="device.derived")
        assert len(all_derived) == 0

    def test_empty_disabled_metrics_computes_all(self, db):
        """Empty disabled_metrics list computes everything (backward compat)."""
        cfg = {"enabled": True, "disabled_metrics": []}
        mod = create_module(cfg)

        events = [
            _make_event("device.screen", "screen_on", value_text="on",
                        minute_offset=i * 5)
            for i in range(3)
        ]
        db.insert_events_for_module("device_screen", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="device.derived",
                               event_type="unlock_count")
        assert len(rows) == 1
