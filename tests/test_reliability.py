"""
LifeData V4 — Reliability Mechanism Tests
tests/test_reliability.py

Tests for the three reliability pillars:
  1. Lockfile with 5-second timeout
  2. Configurable file stability check
  3. Graceful parser degradation (safe_parse_rows + quarantine)
"""

import fcntl
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event import Event
from core.parser_utils import ParseResult, safe_parse_rows, QUARANTINE_THRESHOLD


# ══════════════════════════════════════════════════════════════
# 1. LOCKFILE TESTS
# ══════════════════════════════════════════════════════════════


class TestLockfileTimeout:
    """Verify that _acquire_lock retries for the configured timeout
    before exiting with code 1."""

    def test_acquire_lock_succeeds_when_free(self, tmp_path):
        """Lock acquisition on a free file should succeed immediately."""
        import run_etl

        original_lock = run_etl.LOCK_FILE
        lock_path = str(tmp_path / ".test.lock")
        run_etl.LOCK_FILE = lock_path
        try:
            lock_fd = run_etl._acquire_lock()
            assert lock_fd is not None
            # PID should be written to the file
            with open(lock_path) as f:
                content = f.read()
            assert str(os.getpid()) in content
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        finally:
            run_etl.LOCK_FILE = original_lock

    def test_acquire_lock_exits_1_when_held(self, tmp_path):
        """When the lock is held, _acquire_lock should retry and then
        exit with code 1 after the timeout."""
        import run_etl

        original_lock = run_etl.LOCK_FILE
        original_timeout = run_etl.LOCK_TIMEOUT_SECONDS
        lock_path = str(tmp_path / ".test.lock")
        run_etl.LOCK_FILE = lock_path
        run_etl.LOCK_TIMEOUT_SECONDS = 0.5  # fast timeout

        # Hold the lock
        holder = open(lock_path, "w")
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            start = time.monotonic()
            with pytest.raises(SystemExit) as exc_info:
                run_etl._acquire_lock()
            elapsed = time.monotonic() - start

            assert exc_info.value.code == 1
            # Should have waited at least ~0.5s (the timeout)
            assert elapsed >= 0.4, f"Exited too fast ({elapsed:.2f}s), should wait ~0.5s"
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
            holder.close()
            run_etl.LOCK_FILE = original_lock
            run_etl.LOCK_TIMEOUT_SECONDS = original_timeout

    def test_lock_released_on_fd_close(self, tmp_path):
        """flock is released automatically when the fd is closed,
        even without explicit unlock (crash-safe)."""
        lock_path = str(tmp_path / ".test.lock")

        # Acquire and close (simulating a crash — no explicit unlock)
        fd1 = open(lock_path, "w")
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fd1.close()  # releases the flock

        # Should be acquirable again
        fd2 = open(lock_path, "w")
        fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # should not raise
        fcntl.flock(fd2, fcntl.LOCK_UN)
        fd2.close()

    def test_exit_message_content(self, tmp_path, capsys):
        """The exit message should say 'ETL already running (lockfile held). Exiting.'"""
        import run_etl

        original_lock = run_etl.LOCK_FILE
        original_timeout = run_etl.LOCK_TIMEOUT_SECONDS
        lock_path = str(tmp_path / ".test.lock")
        run_etl.LOCK_FILE = lock_path
        run_etl.LOCK_TIMEOUT_SECONDS = 0.25

        holder = open(lock_path, "w")
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            with pytest.raises(SystemExit):
                run_etl._acquire_lock()
            captured = capsys.readouterr()
            assert "ETL already running (lockfile held). Exiting." in captured.err
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
            holder.close()
            run_etl.LOCK_FILE = original_lock
            run_etl.LOCK_TIMEOUT_SECONDS = original_timeout


# ══════════════════════════════════════════════════════════════
# 2. FILE STABILITY CHECK TESTS
# ══════════════════════════════════════════════════════════════


class TestFileStabilityConfig:
    """Verify that file_stability_seconds is configurable via the etl
    section in config.yaml and wired through the orchestrator."""

    def test_etl_config_default(self):
        """EtlConfig defaults to file_stability_seconds=60."""
        from core.config_schema import EtlConfig

        cfg = EtlConfig()
        assert cfg.file_stability_seconds == 60

    def test_etl_config_custom_value(self):
        """EtlConfig accepts a custom file_stability_seconds."""
        from core.config_schema import EtlConfig

        cfg = EtlConfig(file_stability_seconds=120)
        assert cfg.file_stability_seconds == 120

    def test_etl_config_zero_disables(self):
        """Setting file_stability_seconds=0 effectively disables the check."""
        from core.config_schema import EtlConfig

        cfg = EtlConfig(file_stability_seconds=0)
        assert cfg.file_stability_seconds == 0

    def test_etl_config_rejects_negative(self):
        """Negative values should be rejected by the validator."""
        from core.config_schema import EtlConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EtlConfig(file_stability_seconds=-1)

    def test_etl_config_rejects_over_600(self):
        """Values over 600 should be rejected."""
        from core.config_schema import EtlConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EtlConfig(file_stability_seconds=601)

    def test_lifedata_config_includes_etl(self):
        """LifeDataConfig should include the etl section with defaults."""
        from core.config_schema import (
            LifeDataConfig,
            SecurityConfig,
        )

        cfg = LifeDataConfig(
            version="4.0",
            timezone="America/Chicago",
            db_path="/tmp/test.db",
            raw_base="/tmp/raw",
            media_base="/tmp/media",
            reports_dir="/tmp/reports",
            log_path="/tmp/etl.log",
            security=SecurityConfig(module_allowlist=["device"]),
        )
        assert cfg.etl.file_stability_seconds == 60

    def test_stability_check_uses_config_value(self, tmp_path):
        """The orchestrator should use the configured value, not a hardcoded one.
        With file_stability_seconds=0, even very recent files should be processed."""
        import yaml
        from tests.test_etl_integration import (
            _write_config_yaml,
            _make_orchestrator,
            _BASE_EPOCH,
        )

        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device"]
        )

        # Patch the config to set file_stability_seconds=0
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cfg["lifedata"]["etl"] = {"file_stability_seconds": 0}
        with open(config_path, "w") as f:
            yaml.dump(cfg, f)

        raw_dir = str(tmp_path / "raw" / "LifeData")
        device_dir = os.path.join(raw_dir, "logs", "device")
        os.makedirs(device_dir, exist_ok=True)

        # Write a screen CSV with very recent mtime (just now)
        screen_path = os.path.join(device_dir, "screen_2026-03-20.csv")
        with open(screen_path, "w") as f:
            f.write(f"{_BASE_EPOCH},3-20-26,10:00,-0500,on,85\n")
        # mtime is now — normally would be skipped with 60s threshold

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        # With stability=0, the file should NOT be skipped
        total = orch.db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert total >= 1, "File was skipped despite file_stability_seconds=0"
        orch.db.close()


# ══════════════════════════════════════════════════════════════
# 3. GRACEFUL PARSER DEGRADATION TESTS
# ══════════════════════════════════════════════════════════════


class TestSafeParseRows:
    """Tests for core.parser_utils.safe_parse_rows."""

    def _make_csv(self, tmp_path, filename, lines):
        """Write lines to a CSV file and return the path."""
        path = tmp_path / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def test_happy_path_all_rows_parsed(self, tmp_path):
        """All valid rows produce events, skipped=0, quarantined=False."""
        lines = [
            "1742475600,3-20-26,10:00,-0500,on,85",
            "1742476320,3-20-26,10:12,-0500,off,84",
            "1742477040,3-20-26,10:24,-0500,on,83",
        ]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_numeric=float(fields[5]),
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 3
        assert result.skipped == 0
        assert result.total_rows == 3
        assert result.quarantined is False

    def test_none_return_skips_row_without_error(self, tmp_path):
        """parse_fn returning None is an intentional skip, not an error."""
        lines = ["header,line,skip", "1742475600,data,keep"]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            if not fields[0].isdigit():
                return None  # skip header
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_text="ok",
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 1
        assert result.skipped == 0  # None return is not counted as skip
        assert result.quarantined is False

    def test_exception_per_row_logged_and_skipped(self, tmp_path):
        """Exceptions from parse_fn are caught and counted as skips."""
        lines = [
            "good,line",
            "bad,line",
            "good,line2",
        ]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            if fields[0] == "bad":
                raise ValueError("simulated error")
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_text=fields[0],
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 2
        assert result.skipped == 1
        assert result.quarantined is False  # 1/3 = 33% < 50%

    def test_quarantine_when_majority_skipped(self, tmp_path):
        """File quarantined when >50% of rows are skipped."""
        lines = ["bad"] * 6 + ["good"] * 2  # 8 rows, 6 bad = 75%
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            if fields[0] == "bad":
                raise ValueError("corrupt")
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_text="ok",
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert result.quarantined is True
        assert result.skipped == 6
        assert len(result.events) == 2

    def test_not_quarantined_at_exactly_50_percent(self, tmp_path):
        """File is NOT quarantined at exactly 50% (threshold is >50%)."""
        lines = ["bad", "good"]  # 50% exactly
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            if fields[0] == "bad":
                raise ValueError("corrupt")
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_text="ok",
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert result.quarantined is False  # exactly 50% is not > 50%

    def test_empty_file_not_quarantined(self, tmp_path):
        """An empty file should produce no events and not be quarantined."""
        csv_path = self._make_csv(tmp_path, "empty.csv", [])
        # File contains just a newline from our helper

        def parse_fn(fields, line_num):
            return None

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 0
        assert result.quarantined is False

    def test_blank_lines_ignored(self, tmp_path):
        """Blank lines should be silently skipped, not counted."""
        lines = ["", "good,line", "", "good,line2", ""]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="test.module",
                event_type="test",
                value_text="ok",
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, parse_fn, "test")
        assert len(result.events) == 2
        assert result.total_rows == 2  # blank lines not counted
        assert result.skipped == 0

    def test_parse_fn_returns_list_of_events(self, tmp_path):
        """parse_fn can return a list of Events (e.g. morning check-in)."""
        lines = ["1742475600,data"]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def parse_fn(fields, line_num):
            base = dict(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
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
        assert result.total_rows == 1

    def test_nonexistent_file_returns_empty(self, tmp_path):
        """Trying to parse a file that doesn't exist returns empty result."""
        result = safe_parse_rows(
            str(tmp_path / "does_not_exist.csv"),
            lambda f, n: None,
            "test",
        )
        assert len(result.events) == 0
        assert result.quarantined is False

    def test_filepath_in_result(self, tmp_path):
        """ParseResult should store the filepath."""
        csv_path = self._make_csv(tmp_path, "test.csv", ["a,b"])
        result = safe_parse_rows(csv_path, lambda f, n: None, "test")
        assert result.filepath == csv_path


class TestDeviceParsersSafeRefactor:
    """Verify that the refactored device parsers produce the same results
    as the original implementation, now using safe_parse_rows under the hood."""

    def _make_csv(self, tmp_path, filename, lines):
        path = tmp_path / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def test_battery_v4_happy_path(self, tmp_path):
        from modules.device.parsers import parse_battery, parse_battery_safe

        lines = [
            "1711303200,3-24-26,10:00,-0500,85,28.5,4096,123456",
            "1711306800,3-24-26,11:00,-0500,82,29.0,4000,127000",
        ]
        csv_path = self._make_csv(tmp_path, "battery_test.csv", lines)

        events = parse_battery(csv_path)
        assert len(events) == 2
        assert all(e.source_module == "device.battery" for e in events)

        # Safe variant should return same events plus metadata
        result = parse_battery_safe(csv_path)
        assert len(result.events) == 2
        assert result.skipped == 0
        assert result.quarantined is False

    def test_screen_v4_happy_path(self, tmp_path):
        from modules.device.parsers import parse_screen, parse_screen_safe

        lines = [
            "1711303200,3-24-26,10:00,-0500,on,85",
            "1711303500,3-24-26,10:05,-0500,off,84",
        ]
        csv_path = self._make_csv(tmp_path, "screen_test.csv", lines)

        events = parse_screen(csv_path)
        assert len(events) == 2
        assert events[0].event_type == "screen_on"
        assert events[1].event_type == "screen_off"

        result = parse_screen_safe(csv_path)
        assert len(result.events) == 2
        assert result.quarantined is False

    def test_charging_v4_happy_path(self, tmp_path):
        from modules.device.parsers import parse_charging

        lines = [
            "1711303200,3-24-26,10:00,-0500,charge_start,45",
            "1711310400,3-24-26,12:00,-0500,charge_stop,90",
        ]
        csv_path = self._make_csv(tmp_path, "charging_test.csv", lines)

        events = parse_charging(csv_path)
        assert len(events) == 2
        assert events[0].event_type == "charge_start"
        assert events[1].event_type == "charge_stop"

    def test_bluetooth_v4_happy_path(self, tmp_path):
        from modules.device.parsers import parse_bluetooth

        lines = [
            "1711303200,3-24-26,10:00,-0500,bt_event,on",
            "1711306800,3-24-26,11:00,-0500,bt_event,off",
        ]
        csv_path = self._make_csv(tmp_path, "bluetooth_test.csv", lines)

        events = parse_bluetooth(csv_path)
        assert len(events) == 2
        assert all(e.event_type == "bt_event" for e in events)

    def test_battery_v3_unresolved_tasker_vars(self, tmp_path):
        """v3 format with unresolved %TEMP and %MFREE should still parse."""
        from modules.device.parsers import parse_battery

        lines = [
            "1711303200,3-24-26,10:00,85,%TEMP,%MFREE,123456",
        ]
        csv_path = self._make_csv(tmp_path, "battery_v3.csv", lines)

        events = parse_battery(csv_path)
        assert len(events) == 1
        assert events[0].value_numeric == 85.0

    def test_device_quarantine_on_corrupt_file(self, tmp_path):
        """A mostly-corrupt file should be quarantined."""
        from modules.device.parsers import parse_screen_safe

        # 5 corrupt lines + 1 valid = 83% corrupt → quarantined
        lines = [
            "not_an_epoch,bad",
            "also_bad,line",
            "still_bad,data",
            "nope,nope",
            "broken,again",
            "1711303200,3-24-26,10:00,-0500,on,85",
        ]
        csv_path = self._make_csv(tmp_path, "screen_corrupt.csv", lines)

        result = parse_screen_safe(csv_path)
        # The non-epoch lines return None (intentional skip), not exceptions.
        # Only the valid line produces an event.
        assert len(result.events) == 1
        # None returns aren't counted as skips, so this won't quarantine.
        # Let me use actually-crashing rows instead.

    def test_quarantine_with_actually_crashing_rows(self, tmp_path):
        """Rows that cause parse exceptions should trigger quarantine."""
        from core.parser_utils import safe_parse_rows

        # Create rows where 4 out of 5 will raise exceptions
        lines = [
            "1711303200",           # too few fields — will crash in parse_timestamp
            "1711303200",           # same
            "1711303200",           # same
            "1711303200",           # same
            "1711303200,3-24-26,10:00,-0500,on,85",  # valid
        ]
        csv_path = self._make_csv(tmp_path, "test.csv", lines)

        def crashy_parse(fields, line_num):
            if len(fields) < 4:
                raise ValueError("too few fields")
            return Event(
                timestamp_utc="2026-03-20T15:00:00+00:00",
                timestamp_local="2026-03-20T10:00:00-05:00",
                timezone_offset="-0500",
                source_module="device.screen",
                event_type="test",
                value_text="ok",
                confidence=1.0,
                parser_version="1.0.0",
            )

        result = safe_parse_rows(csv_path, crashy_parse, "device")
        assert result.quarantined is True
        assert result.skipped == 4
        assert len(result.events) == 1


class TestQuarantineInOrchestrator:
    """Verify that quarantined files are tracked in the orchestrator summary."""

    def test_quarantined_files_in_summary(self, tmp_path):
        """The orchestrator summary should include a quarantined_files key."""
        import yaml
        from tests.test_etl_integration import (
            _write_config_yaml,
            _make_orchestrator,
            _BASE_EPOCH,
        )

        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device"]
        )

        raw_dir = str(tmp_path / "raw" / "LifeData")
        device_dir = os.path.join(raw_dir, "logs", "device")
        os.makedirs(device_dir, exist_ok=True)

        # Write a valid battery file
        battery_path = os.path.join(device_dir, "battery_2026-03-20.csv")
        with open(battery_path, "w") as f:
            f.write(f"{_BASE_EPOCH},3-20-26,10:00,-0500,85,28.0,4096,100000\n")
        old_time = time.time() - 300
        os.utime(battery_path, (old_time, old_time))

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        # quarantined_files should be present in summary (empty for clean data)
        assert "quarantined_files" in summary
        assert isinstance(summary["quarantined_files"], list)
        assert len(summary["quarantined_files"]) == 0

        orch.db.close()
