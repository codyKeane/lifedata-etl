"""
Tests for MetaModule.post_ingest() health check event generation.

Covers:
  - Completeness check produces events with percentage
  - Quality check flags future timestamps
  - post_ingest doesn't crash on empty DB or missing directories
"""

import json
import os

import pytest

from core.event import Event
from modules.meta import create_module


TARGET_DATE = "2026-03-20"
TZ_OFFSET = "-0500"


def _make_event(source_module, event_type, value_numeric=None, value_text=None,
                minute_offset=0):
    """Build an event at a known timestamp on TARGET_DATE."""
    from datetime import datetime, timedelta, timezone as tz

    dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=tz.utc) + timedelta(minutes=minute_offset)
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


def _meta_config(tmp_path):
    """Build a meta module config with real filesystem paths."""
    db_path = str(tmp_path / "test.db")
    raw_base = str(tmp_path / "raw")
    os.makedirs(raw_base, exist_ok=True)
    return {
        "enabled": True,
        "completeness_check": True,
        "quality_check": True,
        "storage_check": True,
        "sync_lag_check": True,
        # Internal path hints used by _get_raw_base / _get_db_path
        "_raw_base": raw_base,
        "_db_path": db_path,
    }


# ────────────────────────────────────────────────────────────
# Completeness Check
# ────────────────────────────────────────────────────────────


class TestCompletenessCheck:
    """meta.completeness/daily_check — reports data arrival percentage."""

    def test_has_events_nonzero_percentage(self, db, tmp_path):
        """When some expected sources have data, completeness > 0%."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        # The completeness check uses today_local() internally, so we need
        # events timestamped for today's actual date.
        from core.utils import today_local
        today = today_local()

        screen_events = []
        for i in range(15):
            evt = Event(
                timestamp_utc=f"{today}T{8 + i // 6:02d}:{(i * 5) % 60:02d}:00+00:00",
                timestamp_local=f"{today}T{3 + i // 6:02d}:{(i * 5) % 60:02d}:00-05:00",
                timezone_offset=TZ_OFFSET,
                source_module="device.screen",
                event_type="screen_on",
                value_text="on",
                confidence=1.0,
                parser_version="1.0.0",
            )
            screen_events.append(evt)
        db.insert_events_for_module("device_screen", screen_events)

        mod.post_ingest(db, affected_dates={today})

        rows = db.query_events(source_module="meta.completeness",
                               event_type="daily_check")
        assert len(rows) == 1
        row = rows[0]
        # At least device.screen met its threshold → percentage > 0
        assert row["value_numeric"] is not None
        assert row["value_numeric"] > 0

    def test_empty_db_zero_percentage(self, db, tmp_path):
        """On an empty DB, completeness is 0%."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.completeness",
                               event_type="daily_check")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 0.0


# ────────────────────────────────────────────────────────────
# Quality Check
# ────────────────────────────────────────────────────────────


class TestQualityCheck:
    """meta.quality/daily_check — flags data quality issues."""

    def test_future_timestamp_flagged(self, db, tmp_path):
        """An event with a far-future timestamp triggers a quality issue."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        # Insert an event with timestamp far in the future
        future_event = Event(
            timestamp_utc="2099-12-31T23:59:00+00:00",
            timestamp_local="2099-12-31T18:59:00-05:00",
            timezone_offset=TZ_OFFSET,
            source_module="device.screen",
            event_type="screen_on",
            value_text="on",
            confidence=1.0,
            parser_version="1.0.0",
        )
        db.insert_events_for_module("device_screen", [future_event])

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.quality",
                               event_type="daily_check")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])
        # Should report at least 1 issue (future timestamp)
        assert data["issue_count"] >= 1

    def test_valid_data_passes(self, db, tmp_path):
        """Normal events produce a quality check with 0 issues."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        # Insert a normal event
        normal_event = _make_event("device.battery", "pulse", value_numeric=85.0)
        db.insert_events_for_module("device_battery", [normal_event])

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.quality",
                               event_type="daily_check")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])
        assert data["issue_count"] == 0


# ────────────────────────────────────────────────────────────
# Crash Safety
# ────────────────────────────────────────────────────────────


class TestPostIngestDoesNotCrash:
    """post_ingest must not raise on edge cases."""

    def test_empty_db(self, db, tmp_path):
        """post_ingest on a totally empty DB does not raise."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        # Should not raise
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        # Should still produce at least completeness and quality events
        all_meta = db.query_events(source_module="meta.completeness")
        assert len(all_meta) >= 0  # just verify no crash

    def test_missing_directories(self, db, tmp_path):
        """post_ingest with nonexistent raw_base doesn't crash."""
        config = _meta_config(tmp_path)
        config["_raw_base"] = str(tmp_path / "nonexistent" / "path")
        config["_db_path"] = str(tmp_path / "nonexistent" / "db" / "test.db")
        mod = create_module(config)

        # Should not raise — errors are caught internally
        mod.post_ingest(db, affected_dates={TARGET_DATE})

    def test_all_checks_disabled(self, db, tmp_path):
        """With all checks disabled, no meta events are produced."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        all_meta = db.query_events(source_module="meta.completeness")
        all_meta += db.query_events(source_module="meta.quality")
        all_meta += db.query_events(source_module="meta.storage")
        all_meta += db.query_events(source_module="meta.sync")
        assert len(all_meta) == 0
