"""
LifeData V4 — Provenance Tracing Tests
tests/test_provenance.py

Tests for:
  1. Event.provenance field (ephemeral, not in DB tuple, in repr)
  2. safe_parse_rows stamps provenance on returned events
  3. Database.insert_events_for_module logs provenance
  4. --trace CLI command
"""

import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event import Event
from core.parser_utils import safe_parse_rows


# ══════════════════════════════════════════════════════════════
# 1. EVENT PROVENANCE FIELD
# ══════════════════════════════════════════════════════════════


class TestEventProvenance:

    def _make_event(self, **kwargs):
        defaults = dict(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="device.battery",
            event_type="pulse",
            value_numeric=85.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        defaults.update(kwargs)
        return Event(**defaults)

    def test_provenance_default_none(self):
        e = self._make_event()
        assert e.provenance is None

    def test_provenance_can_be_set(self):
        e = self._make_event(provenance="file=test.csv:line=1:parser=device:v=1.0.0")
        assert e.provenance == "file=test.csv:line=1:parser=device:v=1.0.0"

    def test_provenance_not_in_db_tuple(self):
        e = self._make_event(provenance="file=test.csv:line=1:parser=device:v=1.0.0")
        t = e.to_db_tuple()
        assert len(t) == 17
        # Provenance string should not appear anywhere in the tuple
        assert "test.csv" not in str(t)

    def test_provenance_in_repr(self):
        e = self._make_event(provenance="file=bat.csv:line=5:parser=device:v=1.0.0")
        r = repr(e)
        assert "bat.csv" in r
        assert "line=5" in r

    def test_provenance_absent_from_repr_when_none(self):
        e = self._make_event()
        r = repr(e)
        assert "[" not in r  # no provenance bracket

    def test_provenance_not_in_raw_source_id(self):
        """Provenance must not affect deduplication."""
        e1 = self._make_event(provenance="file=a.csv:line=1:parser=x:v=1")
        e2 = self._make_event(provenance="file=b.csv:line=99:parser=y:v=2")
        e3 = self._make_event()
        assert e1.raw_source_id == e2.raw_source_id == e3.raw_source_id

    def test_provenance_not_in_event_id(self):
        e1 = self._make_event(provenance="a")
        e2 = self._make_event(provenance="b")
        assert e1.event_id == e2.event_id


# ══════════════════════════════════════════════════════════════
# 2. SAFE_PARSE_ROWS PROVENANCE STAMPING
# ══════════════════════════════════════════════════════════════


class TestSafeParseRowsProvenance:

    def _make_csv(self, tmp_path, filename, lines):
        path = tmp_path / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def test_provenance_stamped_on_single_event(self, tmp_path):
        csv_path = self._make_csv(tmp_path, "screen_2026-03-22.csv", [
            "1711303200,3-24-26,10:00,-0500,on,85",
        ])

        def parse_fn(fields, line_num):
            return Event(
                timestamp_utc="2026-03-24T15:00:00+00:00",
                timestamp_local="2026-03-24T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="device.screen",
                event_type="screen_on",
                value_text="on",
                confidence=1.0,
                parser_version="1.2.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "device")
        assert len(result.events) == 1
        prov = result.events[0].provenance
        assert prov is not None
        assert "file=screen_2026-03-22.csv" in prov
        assert "line=1" in prov
        assert "parser=device" in prov
        assert "v=1.2.0" in prov

    def test_provenance_line_numbers_correct(self, tmp_path):
        csv_path = self._make_csv(tmp_path, "bat.csv", [
            "row1,data",
            "",  # blank — skipped, doesn't count
            "row3,data",
        ])

        def parse_fn(fields, line_num):
            return Event(
                timestamp_utc="2026-03-24T15:00:00+00:00",
                timestamp_local="2026-03-24T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.mod",
                event_type="test",
                value_text=fields[0],
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 2
        assert "line=1" in result.events[0].provenance
        assert "line=3" in result.events[1].provenance  # line 3, not 2

    def test_provenance_on_list_return(self, tmp_path):
        """When parse_fn returns a list, all events get provenance."""
        csv_path = self._make_csv(tmp_path, "morning.csv", [
            "1711278000,3-24-26,07:00,8,1,7,6",
        ])

        def parse_fn(fields, line_num):
            base = dict(
                timestamp_utc="2026-03-24T12:00:00+00:00",
                timestamp_local="2026-03-24T07:00:00-05:00",
                timezone_offset="-0500",
                confidence=1.0,
                parser_version="1.0.0",
            )
            return [
                Event(source_module="mind.morning", event_type="assessment",
                      value_text="composite", **base),
                Event(source_module="mind.mood", event_type="check_in",
                      value_numeric=7.0, **base),
            ]

        result = safe_parse_rows(csv_path, parse_fn, "mind")
        assert len(result.events) == 2
        for evt in result.events:
            assert evt.provenance is not None
            assert "file=morning.csv" in evt.provenance
            assert "line=1" in evt.provenance
            assert "parser=mind" in evt.provenance

    def test_provenance_with_no_parser_version(self, tmp_path):
        """Events without parser_version get v=? in provenance."""
        csv_path = self._make_csv(tmp_path, "test.csv", ["a,b"])

        def parse_fn(fields, line_num):
            return Event(
                timestamp_utc="2026-03-24T15:00:00+00:00",
                timestamp_local="2026-03-24T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.mod",
                event_type="test",
                value_text="ok",
                confidence=1.0,
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert "v=?" in result.events[0].provenance


# ══════════════════════════════════════════════════════════════
# 3. DATABASE PROVENANCE LOGGING
# ══════════════════════════════════════════════════════════════


class TestDatabaseProvenanceLogging:

    def test_debug_log_on_ingest(self, tmp_path, caplog):
        """Each ingested event should produce a DEBUG log with provenance."""
        from core.database import Database

        db = Database(str(tmp_path / "test.db"))
        db.ensure_schema()

        evt = Event(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="device.battery",
            event_type="pulse",
            value_numeric=85.0,
            confidence=1.0,
            parser_version="1.0.0",
            provenance="file=battery.csv:line=1:parser=device:v=1.0.0",
        )

        with caplog.at_level(logging.DEBUG, logger="lifedata.database"):
            inserted, skipped = db.insert_events_for_module("device", [evt])

        assert inserted == 1
        assert skipped == 0
        # Check DEBUG log contains provenance
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("battery.csv" in m and "Ingested" in m for m in debug_msgs), \
            f"Expected provenance in DEBUG log, got: {debug_msgs}"
        db.close()

    def test_warning_log_on_validation_failure(self, tmp_path, caplog):
        """Rejected events should produce a WARNING log with provenance."""
        from core.database import Database

        db = Database(str(tmp_path / "test.db"))
        db.ensure_schema()

        # Missing source_module dot-notation — will fail validation
        bad_evt = Event(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="nodot",
            event_type="test",
            value_numeric=1.0,
            confidence=1.0,
            provenance="file=bad.csv:line=42:parser=test:v=1.0.0",
        )

        with caplog.at_level(logging.WARNING, logger="lifedata.database"):
            inserted, skipped = db.insert_events_for_module("test", [bad_evt])

        assert inserted == 0
        assert skipped == 1
        warn_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("bad.csv" in m and "Rejected" in m for m in warn_msgs), \
            f"Expected provenance in WARNING log, got: {warn_msgs}"
        db.close()

    def test_unknown_provenance_when_not_set(self, tmp_path, caplog):
        """Events without provenance should log 'unknown'."""
        from core.database import Database

        db = Database(str(tmp_path / "test.db"))
        db.ensure_schema()

        evt = Event(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="device.battery",
            event_type="pulse",
            value_numeric=85.0,
            confidence=1.0,
            parser_version="1.0.0",
        )

        with caplog.at_level(logging.DEBUG, logger="lifedata.database"):
            db.insert_events_for_module("device", [evt])

        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("unknown" in m for m in debug_msgs)
        db.close()


# ══════════════════════════════════════════════════════════════
# 4. --TRACE CLI COMMAND
# ══════════════════════════════════════════════════════════════


class TestTraceCLI:

    def _setup_db_with_event(self, tmp_path):
        """Create a test DB with one event and return (db, event, config_path)."""
        import yaml

        # Create directory structure
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        raw_dir = tmp_path / "raw" / "LifeData"
        raw_dir.mkdir(parents=True)
        for d in ("media", "reports", "logs"):
            (tmp_path / d).mkdir()

        from core.database import Database
        db = Database(str(db_dir / "lifedata.db"))
        db.ensure_schema()

        evt = Event(
            timestamp_utc="2026-03-22T15:00:00+00:00",
            timestamp_local="2026-03-22T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="device.screen",
            event_type="screen_on",
            value_text="on",
            value_numeric=85.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        db.insert_events_for_module("device", [evt])

        # Add a daily summary for this date + module
        db.upsert_daily_summary(
            "2026-03-22", "device.derived", "unlock_count", value_numeric=15.0
        )

        # Write config
        config = {
            "lifedata": {
                "version": "4.0",
                "timezone": "America/Chicago",
                "db_path": str(db_dir / "lifedata.db"),
                "raw_base": str(raw_dir),
                "media_base": str(tmp_path / "media"),
                "reports_dir": str(tmp_path / "reports"),
                "log_path": str(tmp_path / "logs" / "etl.log"),
                "security": {
                    "syncthing_relay_enabled": False,
                    "module_allowlist": ["device"],
                },
                "modules": {
                    mod: {"enabled": mod == "device"}
                    for mod in (
                        "device", "environment", "body", "mind", "world",
                        "social", "media", "meta", "cognition", "behavior", "oracle",
                    )
                },
            }
        }
        config_path = str(tmp_path / "config.yaml")
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        env_path = str(tmp_path / ".env")
        with open(env_path, "w") as f:
            f.write("WEATHER_API_KEY=x\nAIRNOW_API_KEY=x\nAMBEE_API_KEY=x\n"
                    "NEWS_API_KEY=x\nEIA_API_KEY=x\nSYNCTHING_API_KEY=x\n"
                    "HOME_LAT=0\nHOME_LON=0\n")

        db.close()
        return evt, config_path, env_path

    def test_trace_finds_event(self, tmp_path, capsys, monkeypatch):
        evt, config_path, env_path = self._setup_db_with_event(tmp_path)

        import run_etl
        import core.config as config_mod

        original_load = config_mod.load_config
        def patched_load(path=None, env_path_arg=None):
            return original_load(path=config_path, env_path=env_path)
        config_mod.load_config = patched_load

        try:
            result = run_etl._print_trace(evt.raw_source_id, config_path)
        finally:
            config_mod.load_config = original_load

        captured = capsys.readouterr()
        assert result == 0
        assert "Event Record" in captured.out
        assert evt.event_id in captured.out
        assert "device.screen" in captured.out
        assert "screen_on" in captured.out
        assert "parser_version" in captured.out

    def test_trace_shows_daily_summaries(self, tmp_path, capsys, monkeypatch):
        evt, config_path, env_path = self._setup_db_with_event(tmp_path)

        import run_etl
        import core.config as config_mod

        original_load = config_mod.load_config
        def patched_load(path=None, env_path_arg=None):
            return original_load(path=config_path, env_path=env_path)
        config_mod.load_config = patched_load

        try:
            run_etl._print_trace(evt.raw_source_id, config_path)
        finally:
            config_mod.load_config = original_load

        captured = capsys.readouterr()
        assert "Daily Summaries" in captured.out
        assert "unlock_count" in captured.out

    def test_trace_not_found(self, tmp_path, capsys, monkeypatch):
        evt, config_path, env_path = self._setup_db_with_event(tmp_path)

        import run_etl
        import core.config as config_mod

        original_load = config_mod.load_config
        def patched_load(path=None, env_path_arg=None):
            return original_load(path=config_path, env_path=env_path)
        config_mod.load_config = patched_load

        try:
            result = run_etl._print_trace("nonexistent_id_12345", config_path)
        finally:
            config_mod.load_config = original_load

        captured = capsys.readouterr()
        assert result == 1
        assert "No event found" in captured.out

    def test_trace_prefix_match(self, tmp_path, capsys, monkeypatch):
        """Short prefix of raw_source_id should still find the event."""
        evt, config_path, env_path = self._setup_db_with_event(tmp_path)

        import run_etl
        import core.config as config_mod

        original_load = config_mod.load_config
        def patched_load(path=None, env_path_arg=None):
            return original_load(path=config_path, env_path=env_path)
        config_mod.load_config = patched_load

        try:
            prefix = evt.raw_source_id[:8]
            result = run_etl._print_trace(prefix, config_path)
        finally:
            config_mod.load_config = original_load

        captured = capsys.readouterr()
        assert result == 0
        assert "Event Record" in captured.out


# ══════════════════════════════════════════════════════════════
# 5. INTEGRATION: DEVICE PARSERS SET PROVENANCE
# ══════════════════════════════════════════════════════════════


class TestDeviceParsersProvenance:
    """Verify the real device parsers (via safe_parse_rows) stamp provenance."""

    def test_battery_parser_sets_provenance(self, tmp_path):
        from modules.device.parsers import parse_battery

        path = tmp_path / "battery_2026-03-22.csv"
        path.write_text(
            "1711303200,3-24-26,10:00,-0500,85,28.5,4096,123456\n",
            encoding="utf-8",
        )

        events = parse_battery(str(path))
        assert len(events) == 1
        assert events[0].provenance is not None
        assert "file=battery_2026-03-22.csv" in events[0].provenance
        assert "line=1" in events[0].provenance
        assert "parser=device" in events[0].provenance
        assert "v=1.0.0" in events[0].provenance

    def test_screen_parser_sets_provenance(self, tmp_path):
        from modules.device.parsers import parse_screen

        path = tmp_path / "screen_2026-03-22.csv"
        path.write_text(
            "1711303200,3-24-26,10:00,-0500,on,85\n"
            "1711303500,3-24-26,10:05,-0500,off,84\n",
            encoding="utf-8",
        )

        events = parse_screen(str(path))
        assert len(events) == 2
        assert "line=1" in events[0].provenance
        assert "line=2" in events[1].provenance
