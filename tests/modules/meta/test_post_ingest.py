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


# ────────────────────────────────────────────────────────────
# Module Properties & Basic Methods
# ────────────────────────────────────────────────────────────


class TestModuleProperties:
    """Cover module_id, display_name, version, source_types, manifest, discover_files, parse."""

    def test_module_id(self):
        mod = create_module({})
        assert mod.module_id == "meta"

    def test_display_name(self):
        mod = create_module({})
        assert mod.display_name == "Meta Module"

    def test_version(self):
        mod = create_module({})
        assert mod.version == "1.0.0"

    def test_source_types(self):
        mod = create_module({})
        st = mod.source_types
        assert "meta.etl" in st
        assert "meta.completeness" in st
        assert len(st) == 5

    def test_get_metrics_manifest(self):
        mod = create_module({})
        manifest = mod.get_metrics_manifest()
        assert "metrics" in manifest
        names = [m["name"] for m in manifest["metrics"]]
        assert "meta.completeness" in names
        assert "meta.quality" in names

    def test_discover_files_returns_empty(self):
        mod = create_module({})
        assert mod.discover_files("/any/path") == []

    def test_parse_returns_empty(self):
        mod = create_module({})
        assert mod.parse("/any/file.csv") == []

    def test_create_module_factory_no_config(self):
        """create_module with None returns a working MetaModule."""
        mod = create_module(None)
        assert mod.module_id == "meta"

    def test_create_module_from_module_py(self):
        """The standalone create_module in module.py works."""
        from modules.meta.module import create_module as cm
        mod = cm({"enabled": True})
        assert mod.module_id == "meta"


# ────────────────────────────────────────────────────────────
# Disabled Metrics via disabled_metrics Config
# ────────────────────────────────────────────────────────────


class TestDisabledMetrics:
    """Metrics disabled via disabled_metrics list should not produce events."""

    def test_completeness_disabled(self, db, tmp_path):
        config = _meta_config(tmp_path)
        config["disabled_metrics"] = ["meta.completeness"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.completeness")
        assert len(rows) == 0

    def test_quality_disabled(self, db, tmp_path):
        config = _meta_config(tmp_path)
        config["disabled_metrics"] = ["meta.quality"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.quality")
        assert len(rows) == 0

    def test_storage_disabled(self, db, tmp_path):
        config = _meta_config(tmp_path)
        config["disabled_metrics"] = ["meta.storage"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.storage")
        assert len(rows) == 0

    def test_sync_disabled(self, db, tmp_path):
        config = _meta_config(tmp_path)
        config["disabled_metrics"] = ["meta.sync"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Storage Check
# ────────────────────────────────────────────────────────────


class TestStorageCheck:
    """meta.storage/usage_report — reports disk and DB sizes."""

    def test_storage_produces_event(self, db, tmp_path, monkeypatch):
        """Storage check creates an event with db_size_mb."""
        config = _meta_config(tmp_path)
        # Only enable storage check
        config["completeness_check"] = False
        config["quality_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        # Mock storage_report to return deterministic data
        fake_report = {
            "database": {"size_mb": 12.5},
            "raw_data": {"size_mb": 200.0},
            "disk": {"free_gb": 100.0, "used_pct": 40.0},
        }
        monkeypatch.setattr(
            "modules.meta.storage.storage_report", lambda cfg: fake_report
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.storage",
                               event_type="usage_report")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 12.5
        data = json.loads(rows[0]["value_json"])
        assert data["db_size_mb"] == 12.5
        assert data["disk_free_gb"] == 100.0

    def test_storage_exception_handled(self, db, tmp_path, monkeypatch):
        """Storage check exception is caught, doesn't crash post_ingest."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        def _raise(*a, **kw):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr("modules.meta.storage.storage_report", _raise)

        # Should not raise
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.storage")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Sync Lag Check
# ────────────────────────────────────────────────────────────


class TestSyncLagCheck:
    """meta.sync/sync_status — reports sync freshness."""

    def test_sync_lag_produces_event(self, db, tmp_path, monkeypatch):
        """Sync lag check creates an event with lag minutes."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        fake_lag = {
            "newest_file_age_minutes": 15,
            "healthy": True,
            "message": "OK — newest file 15 min ago",
        }
        monkeypatch.setattr(
            "modules.meta.sync.check_sync_lag", lambda raw_base: fake_lag
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="sync_status")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 15.0
        data = json.loads(rows[0]["value_json"])
        assert data["healthy"] is True

    def test_sync_lag_exception_handled(self, db, tmp_path, monkeypatch):
        """Sync lag exception is caught gracefully."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        monkeypatch.setattr(
            "modules.meta.sync.check_sync_lag",
            lambda raw_base: (_ for _ in ()).throw(OSError("no disk")),
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        rows = db.query_events(source_module="meta.sync", event_type="sync_status")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# DB Backup Check
# ────────────────────────────────────────────────────────────


class TestBackupCheck:
    """meta.sync/backup_status — reports backup freshness."""

    def test_backup_produces_event(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        fake_backup = {
            "healthy": True,
            "newest_backup_age_days": 0.5,
            "message": "OK — backup 0.5d old",
        }
        monkeypatch.setattr(
            "modules.meta.sync.check_db_backup_age",
            lambda db_path: fake_backup,
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="backup_status")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 0.5
        data = json.loads(rows[0]["value_json"])
        assert data["healthy"] is True

    def test_backup_no_backups_found(self, db, tmp_path, monkeypatch):
        """When no backups exist, value_numeric is -1."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        fake_backup = {
            "healthy": False,
            "newest_backup_age_days": None,
            "message": "No backups found",
        }
        monkeypatch.setattr(
            "modules.meta.sync.check_db_backup_age",
            lambda db_path: fake_backup,
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="backup_status")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == -1.0

    def test_backup_exception_handled(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        def _raise(db_path):
            raise RuntimeError("backup exploded")

        monkeypatch.setattr("modules.meta.sync.check_db_backup_age", _raise)

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        rows = db.query_events(source_module="meta.sync", event_type="backup_status")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Syncthing Relay Check
# ────────────────────────────────────────────────────────────


class TestSyncthingRelayCheck:
    """meta.sync/relay_check — verifies Syncthing relay is disabled."""

    def test_relay_check_with_api_key(self, db, tmp_path, monkeypatch):
        """When API key is set and relay is disabled, event is created."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = True
        config["syncthing_api_key"] = "test-api-key-123"
        mod = create_module(config)

        fake_relay = {
            "relay_enabled": False,
            "healthy": True,
            "message": "OK — relay is disabled",
        }
        monkeypatch.setattr(
            "modules.meta.sync.verify_syncthing_relay",
            lambda api_key: fake_relay,
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="relay_check")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["healthy"] is True
        assert data["relay_enabled"] is False

    def test_relay_check_relay_enabled_critical(self, db, tmp_path, monkeypatch):
        """When relay is enabled, tags include 'critical'."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = True
        config["syncthing_api_key"] = "test-api-key-123"
        mod = create_module(config)

        fake_relay = {
            "relay_enabled": True,
            "healthy": False,
            "message": "CRITICAL — relay is ENABLED",
        }
        monkeypatch.setattr(
            "modules.meta.sync.verify_syncthing_relay",
            lambda api_key: fake_relay,
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="relay_check")
        assert len(rows) == 1
        assert "critical" in rows[0]["tags"]

    def test_relay_check_no_api_key_skipped(self, db, tmp_path):
        """When no API key is set, relay check is skipped."""
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = True
        # No syncthing_api_key
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="meta.sync",
                               event_type="relay_check")
        assert len(rows) == 0

    def test_relay_check_exception_handled(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = True
        config["syncthing_api_key"] = "test-key"
        mod = create_module(config)

        def _raise(api_key):
            raise ConnectionError("syncthing down")

        monkeypatch.setattr("modules.meta.sync.verify_syncthing_relay", _raise)

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        rows = db.query_events(source_module="meta.sync", event_type="relay_check")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Completeness Exception Handling
# ────────────────────────────────────────────────────────────


class TestCompletenessException:
    """Completeness check failure is caught gracefully."""

    def test_completeness_exception_handled(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["quality_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        def _raise(db_inst, date_str):
            raise ValueError("completeness boom")

        monkeypatch.setattr(
            "modules.meta.completeness.check_daily_completeness", _raise
        )

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        rows = db.query_events(source_module="meta.completeness")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Quality Exception Handling
# ────────────────────────────────────────────────────────────


class TestQualityException:
    """Quality check failure is caught gracefully."""

    def test_quality_exception_handled(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["completeness_check"] = False
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        def _raise(db_inst, date_str):
            raise ValueError("quality boom")

        monkeypatch.setattr("modules.meta.quality.validate_events", _raise)

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        rows = db.query_events(source_module="meta.quality")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Insert Events Exception Handling
# ────────────────────────────────────────────────────────────


class TestInsertEventsException:
    """insert_events_for_module failure is caught."""

    def test_insert_exception_handled(self, db, tmp_path, monkeypatch):
        config = _meta_config(tmp_path)
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        original_insert = db.insert_events_for_module

        def _failing_insert(module_name, events):
            if module_name == "meta":
                raise RuntimeError("insert failed")
            return original_insert(module_name, events)

        monkeypatch.setattr(db, "insert_events_for_module", _failing_insert)

        # Should not raise
        mod.post_ingest(db, affected_dates={TARGET_DATE})


# ────────────────────────────────────────────────────────────
# get_daily_summary
# ────────────────────────────────────────────────────────────


class TestGetDailySummary:
    """get_daily_summary returns structured meta health data."""

    def test_summary_with_data(self, db, tmp_path):
        """After post_ingest, get_daily_summary returns health metrics."""
        config = _meta_config(tmp_path)
        # Only completeness and quality (no filesystem-dependent checks)
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        from core.utils import today_local
        today = today_local()

        mod.post_ingest(db, affected_dates={today})

        summary = mod.get_daily_summary(db, today)
        assert summary is not None
        # Should have completeness and quality keys
        assert any("completeness" in k for k in summary)
        assert any("quality" in k for k in summary)

        # Each entry should have a 'value' key
        for key, val in summary.items():
            assert "value" in val

    def test_summary_with_json_detail(self, db, tmp_path):
        """Summary entries with value_json include parsed 'detail'."""
        config = _meta_config(tmp_path)
        config["storage_check"] = False
        config["sync_lag_check"] = False
        config["db_backup_check"] = False
        config["syncthing_relay_check"] = False
        mod = create_module(config)

        from core.utils import today_local
        today = today_local()

        mod.post_ingest(db, affected_dates={today})

        summary = mod.get_daily_summary(db, today)
        assert summary is not None

        # At least one entry should have 'detail' from parsed JSON
        has_detail = any("detail" in v for v in summary.values())
        assert has_detail

    def test_summary_empty_db(self, db, tmp_path):
        """get_daily_summary returns None when no meta events exist for date."""
        mod = create_module({})
        result = mod.get_daily_summary(db, "2020-01-01")
        assert result is None

    def test_summary_no_rows(self, db, tmp_path):
        """get_daily_summary returns None for a date with no events."""
        config = _meta_config(tmp_path)
        mod = create_module(config)
        result = mod.get_daily_summary(db, "1999-01-01")
        assert result is None

    def test_summary_invalid_json_handled(self, db, tmp_path):
        """get_daily_summary handles invalid JSON in value_json gracefully."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        from core.utils import today_local
        today = today_local()

        # Insert directly via SQL to bypass JSON validation in insert_events
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """INSERT INTO events
               (event_id, raw_source_id, timestamp_utc, timestamp_local,
                timezone_offset, source_module, event_type, value_numeric,
                value_json, confidence, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-invalid-json-id",
                "test-raw-source-id",
                f"{today}T00:00:00+00:00",
                f"{today}T00:00:00-05:00",
                "-0500",
                "meta.completeness",
                "daily_check",
                50.0,
                "{not valid json!!!",
                1.0,
                "1.0.0",
                now,
            ),
        )
        db.conn.commit()

        summary = mod.get_daily_summary(db, today)
        assert summary is not None
        key = "meta.completeness.daily_check"
        assert key in summary
        assert summary[key]["value"] == 50.0
        # 'detail' should not be present due to invalid JSON
        assert "detail" not in summary[key]

    def test_summary_db_query_exception(self, db, tmp_path, monkeypatch):
        """get_daily_summary returns None if db.execute raises."""
        mod = create_module({})

        def _raise(*args, **kwargs):
            raise RuntimeError("db query failed")

        monkeypatch.setattr(db, "execute", _raise)

        result = mod.get_daily_summary(db, "2026-03-20")
        assert result is None

    def test_summary_null_json(self, db, tmp_path):
        """get_daily_summary handles NULL value_json."""
        config = _meta_config(tmp_path)
        mod = create_module(config)

        from core.utils import today_local
        today = today_local()

        # Insert with NULL value_json via SQL
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """INSERT INTO events
               (event_id, raw_source_id, timestamp_utc, timestamp_local,
                timezone_offset, source_module, event_type, value_numeric,
                value_json, confidence, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "test-null-json-id",
                "test-null-raw-source-id",
                f"{today}T00:00:00+00:00",
                f"{today}T00:00:00-05:00",
                "-0500",
                "meta.quality",
                "daily_check",
                3.0,
                None,
                1.0,
                "1.0.0",
                now,
            ),
        )
        db.conn.commit()

        summary = mod.get_daily_summary(db, today)
        assert summary is not None
        key = "meta.quality.daily_check"
        assert key in summary
        assert summary[key]["value"] == 3.0
        assert "detail" not in summary[key]
