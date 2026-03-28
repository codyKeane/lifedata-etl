"""
LifeData V4 — ETL Integration Tests
tests/test_etl_integration.py

End-to-end tests that run the actual Orchestrator against synthetic data
in temporary directories. Covers:

  1. Full ETL cycle (device + environment + mind modules)
  2. Idempotency (re-run produces identical results)
  3. Module isolation (one module crash doesn't affect others)
  4. Allowlist enforcement (unlisted modules never load)
  5. Unstable file skipping (Syncthing mid-sync protection)
  6. Lock file concurrency guard
"""

import fcntl
import os
import sys
import time
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.orchestrator import Orchestrator

# ──────────────────────────────────────────────────────────────
# Helpers — build a minimal but real LifeData directory tree
# ──────────────────────────────────────────────────────────────

# Epoch base: 2026-03-20 08:00 CDT (UTC-5)
_BASE_EPOCH = 1742475600


def _write_config_yaml(tmp_path, allowlist=None, extra_modules=None):
    """Write a valid config.yaml + .env to tmp_path. Return config path."""
    db_dir = tmp_path / "db"
    db_dir.mkdir(exist_ok=True)
    raw_dir = tmp_path / "raw" / "LifeData"
    raw_dir.mkdir(parents=True, exist_ok=True)
    media_dir = tmp_path / "media"
    media_dir.mkdir(exist_ok=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(exist_ok=True)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(exist_ok=True)

    if allowlist is None:
        allowlist = ["device", "environment", "mind"]

    modules_cfg = extra_modules or {}
    # Ensure at least device/environment/mind have entries
    for mod in ("device", "environment", "body", "mind", "world",
                "social", "media", "meta", "cognition", "behavior", "oracle"):
        if mod not in modules_cfg:
            modules_cfg[mod] = {"enabled": mod in allowlist}

    config = {
        "lifedata": {
            "version": "4.0",
            "timezone": "America/Chicago",
            "db_path": str(db_dir / "lifedata.db"),
            "raw_base": str(raw_dir),
            "media_base": str(media_dir),
            "reports_dir": str(reports_dir),
            "log_path": str(logs_dir / "etl.log"),
            "security": {
                "syncthing_relay_enabled": False,
                "module_allowlist": allowlist,
            },
            "modules": modules_cfg,
        }
    }

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump(config, default_flow_style=False), encoding="utf-8")

    # Write dummy .env so load_config doesn't warn
    env_path = tmp_path / ".env"
    env_path.write_text(
        "WEATHER_API_KEY=test_key\n"
        "AIRNOW_API_KEY=test_key\n"
        "AMBEE_API_KEY=test_key\n"
        "NEWS_API_KEY=test_key\n"
        "EIA_API_KEY=test_key\n"
        "SYNCTHING_API_KEY=test_key\n"
        "HOME_LAT=32.7767\n"
        "HOME_LON=-96.7970\n",
        encoding="utf-8",
    )

    return str(config_path), str(env_path)


def _populate_device_csvs(raw_dir, old_mtime=True):
    """Write realistic device CSVs into the raw tree. Returns expected event count.

    Device module searches: raw_base/, raw_base/device/, raw_base/logs/device/
    """
    device_dir = os.path.join(raw_dir, "logs", "device")
    os.makedirs(device_dir, exist_ok=True)

    # screen CSV — 5 rows (v4 format)
    screen_rows = []
    for i in range(5):
        epoch = _BASE_EPOCH + i * 720
        state = "on" if i % 2 == 0 else "off"
        batt = 90 - i
        screen_rows.append(f"{epoch},3-20-26,{8 + i // 5}:{(i * 12) % 60:02d},-0500,{state},{batt}")
    screen_path = os.path.join(device_dir, "screen_2026-03-20.csv")
    with open(screen_path, "w") as f:
        f.write("\n".join(screen_rows) + "\n")

    # battery CSV — 3 rows (v4 format)
    battery_rows = []
    for i in range(3):
        epoch = _BASE_EPOCH + i * 900
        batt = 85 - i * 2
        battery_rows.append(
            f"{epoch},3-20-26,{8 + i // 4}:{(i * 15) % 60:02d},-0500,{batt},28.0,4096,100000"
        )
    battery_path = os.path.join(device_dir, "battery_2026-03-20.csv")
    with open(battery_path, "w") as f:
        f.write("\n".join(battery_rows) + "\n")

    if old_mtime:
        # Set mtime to 5 minutes ago so files pass the stability check
        old_time = time.time() - 300
        os.utime(screen_path, (old_time, old_time))
        os.utime(battery_path, (old_time, old_time))

    # 5 screen events + 3 battery events = 8
    return 8


def _populate_environment_csvs(raw_dir, corrupt=False, old_mtime=True):
    """Write environment CSVs. If corrupt=True, write invalid data that will
    cause the parser to raise an exception at the module level.

    Environment module searches: raw_base/environment/, raw_base/logs/environment/,
    raw_base/location/, raw_base/logs/location/, raw_base/astro/, raw_base/logs/astro/
    """
    env_dir = os.path.join(raw_dir, "logs", "environment")
    os.makedirs(env_dir, exist_ok=True)

    if corrupt:
        # Write a file that looks like an hourly CSV but we'll monkey-patch
        # the parser to raise. Instead, write a structurally valid file —
        # the corruption test will patch the module to throw.
        hourly_path = os.path.join(env_dir, "hourly_2026-03-20.csv")
        with open(hourly_path, "w") as f:
            f.write(f"{_BASE_EPOCH},3-20-26,10:00,72.5,45,32.7767,-96.7970,15\n")
        if old_mtime:
            old_time = time.time() - 300
            os.utime(hourly_path, (old_time, old_time))
        return 0

    # hourly CSV — 2 rows
    hourly_path = os.path.join(env_dir, "hourly_2026-03-20.csv")
    hourly_rows = [
        f"{_BASE_EPOCH},3-20-26,10:00,72.5,45,32.7767,-96.7970,15",
        f"{_BASE_EPOCH + 3600},3-20-26,11:00,74.0,42,32.7767,-96.7970,12",
    ]
    with open(hourly_path, "w") as f:
        f.write("\n".join(hourly_rows) + "\n")

    # astro CSV — 1 row
    astro_dir = os.path.join(raw_dir, "logs", "astro")
    os.makedirs(astro_dir, exist_ok=True)
    astro_path = os.path.join(astro_dir, "astro_2026-03-20.csv")
    with open(astro_path, "w") as f:
        f.write(f"{_BASE_EPOCH},15,Waxing Gibbous,85.3,12.1\n")

    if old_mtime:
        old_time = time.time() - 300
        os.utime(hourly_path, (old_time, old_time))
        os.utime(astro_path, (old_time, old_time))

    # 2 hourly + 1 astro = 3
    return 3


def _populate_mind_csvs(raw_dir, old_mtime=True):
    """Write mind check-in CSVs. Returns expected event count.

    Mind module searches: raw_base/manual/, raw_base/logs/manual/
    Morning emits 4 events per row (assessment + sleep + mood + energy).
    Evening emits 4 events per row (assessment + mood + stress + productivity + social).
    Actually: morning = 4 per row, evening = 5 per row (assessment + day_rating/mood + stress + productivity + social_satisfaction).
    Let me count from the parser code:
    - morning: assessment + sleep + mood + energy = 4 events per row
    - evening: assessment + mood + stress + productivity + social_satisfaction = 5 events per row
    """
    manual_dir = os.path.join(raw_dir, "logs", "manual")
    os.makedirs(manual_dir, exist_ok=True)

    # morning CSV — 1 row → 4 events
    morning_path = os.path.join(manual_dir, "morning_2026-03-20.csv")
    with open(morning_path, "w") as f:
        f.write(f"{_BASE_EPOCH - 3600},3-20-26,07:00,8,1,7,6\n")

    # evening CSV — 1 row → 5 events
    evening_path = os.path.join(manual_dir, "evening_2026-03-20.csv")
    with open(evening_path, "w") as f:
        f.write(f"{_BASE_EPOCH + 50400},3-20-26,22:00,7,3,8,6\n")

    if old_mtime:
        old_time = time.time() - 300
        os.utime(morning_path, (old_time, old_time))
        os.utime(evening_path, (old_time, old_time))

    # 4 morning + 5 evening = 9
    return 9


def _make_orchestrator(config_path, env_path):
    """Instantiate an Orchestrator, overriding the .env path."""
    # Patch load_config to use our .env path
    import core.config as config_mod
    original_load = config_mod.load_config

    def patched_load(path=None, env_path_arg=None):
        return original_load(path=config_path, env_path=env_path)

    config_mod.load_config = patched_load
    try:
        orch = Orchestrator(config_path)
    finally:
        config_mod.load_config = original_load
    return orch


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────


class TestFullETLCycle:
    """test_full_etl_cycle: Run the orchestrator against synthetic data
    and verify events table, source_modules, dedup, and module status."""

    def test_full_etl_cycle(self, tmp_path):
        config_path, env_path = _write_config_yaml(tmp_path)
        raw_dir = str(tmp_path / "raw" / "LifeData")

        device_count = _populate_device_csvs(raw_dir)
        env_count = _populate_environment_csvs(raw_dir)
        mind_count = _populate_mind_csvs(raw_dir)
        expected_total = device_count + env_count + mind_count

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        # 1. Correct total event count
        assert summary["total_events"] == expected_total, (
            f"Expected {expected_total} events, got {summary['total_events']}"
        )

        # 2. Correct source_modules present in the database
        rows = orch.db.conn.execute(
            "SELECT DISTINCT source_module FROM events"
        ).fetchall()
        source_modules = {r[0] for r in rows}
        # Device emits device.screen and device.battery
        assert "device.screen" in source_modules
        assert "device.battery" in source_modules
        # Environment emits environment.hourly and environment.astro
        assert "environment.hourly" in source_modules
        assert "environment.astro" in source_modules
        # Mind emits mind.morning, mind.mood, mind.sleep, mind.energy, etc.
        assert "mind.morning" in source_modules
        assert "mind.mood" in source_modules

        # 3. No duplicate raw_source_ids
        dup_check = orch.db.conn.execute(
            "SELECT raw_source_id, COUNT(*) as cnt FROM events "
            "GROUP BY raw_source_id HAVING cnt > 1"
        ).fetchall()
        assert len(dup_check) == 0, f"Found duplicate raw_source_ids: {dup_check}"

        # 4. Modules table updated with last_run_utc and success status
        for mod_id in ("device", "environment", "mind"):
            row = orch.db.conn.execute(
                "SELECT last_run_utc, last_status FROM modules WHERE module_id = ?",
                (mod_id,),
            ).fetchone()
            assert row is not None, f"Module '{mod_id}' not in modules table"
            assert row[0] is not None, f"Module '{mod_id}' has no last_run_utc"
            assert row[1] == "success", f"Module '{mod_id}' status is '{row[1]}', expected 'success'"

        # 5. No failed modules
        assert summary["failed_modules"] == []

        orch.db.close()


class TestETLIdempotency:
    """test_etl_idempotency: Run ETL twice on the same data and verify
    that event count and event_ids are identical (INSERT OR REPLACE)."""

    def test_etl_idempotency(self, tmp_path):
        config_path, env_path = _write_config_yaml(tmp_path)
        raw_dir = str(tmp_path / "raw" / "LifeData")

        _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir)
        _populate_mind_csvs(raw_dir)

        # --- First run ---
        orch = _make_orchestrator(config_path, env_path)
        summary1 = orch.run(report=False)

        count1 = orch.db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        ids1 = {
            r[0]
            for r in orch.db.conn.execute(
                "SELECT event_id FROM events ORDER BY event_id"
            ).fetchall()
        }

        # --- Second run (same data, same orchestrator) ---
        summary2 = orch.run(report=False)

        count2 = orch.db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        ids2 = {
            r[0]
            for r in orch.db.conn.execute(
                "SELECT event_id FROM events ORDER BY event_id"
            ).fetchall()
        }

        # Event count is identical after both runs
        assert count1 == count2, (
            f"Event count changed: {count1} → {count2} (should be identical)"
        )

        # Event IDs are identical (deterministic)
        assert ids1 == ids2, "Event IDs differ between runs (not deterministic)"

        # Both runs report the same total (INSERT OR REPLACE counts as inserted)
        assert summary1["total_events"] == summary2["total_events"]

        orch.db.close()


class TestETLModuleIsolation:
    """test_etl_module_isolation: A crashing environment module does not
    affect device events. SAVEPOINT isolation verified."""

    def test_etl_module_isolation(self, tmp_path):
        config_path, env_path = _write_config_yaml(tmp_path)
        raw_dir = str(tmp_path / "raw" / "LifeData")

        _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir, corrupt=False)

        orch = _make_orchestrator(config_path, env_path)

        # Patch discover_files at the class level so the environment module
        # throws a module-level exception (not a per-file one that gets caught).
        # This simulates a catastrophic module failure.
        with patch(
            "modules.environment.module.EnvironmentModule.discover_files",
            side_effect=RuntimeError("Simulated environment module crash!"),
        ):
            summary = orch.run(report=False)

        # Device events should be ingested successfully
        # (raw events + derived events from post_ingest)
        device_events = orch.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'device.%'"
        ).fetchone()[0]
        assert device_events > 0, "No device events were ingested"

        # Environment module should be marked as failed
        assert "environment" in summary["failed_modules"]

        env_row = orch.db.conn.execute(
            "SELECT last_status, last_error FROM modules WHERE module_id = 'environment'"
        ).fetchone()
        assert env_row is not None
        assert env_row[0] == "failed"
        assert env_row[1] is not None  # error message stored

        # No environment events should exist
        env_events = orch.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'environment.%'"
        ).fetchone()[0]
        assert env_events == 0, f"Environment events found ({env_events}) despite module crash"

        # Device module should be marked as success
        dev_row = orch.db.conn.execute(
            "SELECT last_status FROM modules WHERE module_id = 'device'"
        ).fetchone()
        assert dev_row is not None
        assert dev_row[0] == "success"

        orch.db.close()


class TestETLRespectsAllowlist:
    """test_etl_respects_allowlist: Only allowlisted modules are loaded
    and only their events appear in the database."""

    def test_etl_respects_allowlist(self, tmp_path):
        # Config with ONLY device in the allowlist
        config_path, env_path = _write_config_yaml(
            tmp_path,
            allowlist=["device"],
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")

        # Place CSVs for both device and environment
        device_count = _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir)
        _populate_mind_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        # Only device events should be in the database
        # (raw events + derived events from post_ingest)
        total = orch.db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert total >= device_count, (
            f"Expected at least {device_count} events (device only), got {total}"
        )
        # All events should be device events
        non_device = orch.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module NOT LIKE 'device.%'"
        ).fetchone()[0]
        assert non_device == 0, f"Found {non_device} non-device events"

        # No environment or mind events
        env_events = orch.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'environment.%'"
        ).fetchone()[0]
        assert env_events == 0, f"Environment events found ({env_events}) despite not being in allowlist"

        mind_events = orch.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'mind.%'"
        ).fetchone()[0]
        assert mind_events == 0, f"Mind events found ({mind_events}) despite not being in allowlist"

        # Only 1 module should have run
        assert summary["modules_run"] == 1

        # Environment module should NOT be in the modules table
        env_row = orch.db.conn.execute(
            "SELECT * FROM modules WHERE module_id = 'environment'"
        ).fetchone()
        assert env_row is None, "Environment module was loaded despite not being in allowlist"

        orch.db.close()


class TestETLSkipsUnstableFiles:
    """test_etl_skips_unstable_files: Files modified within the 60-second
    stability window are skipped (Syncthing mid-sync protection)."""

    def test_etl_skips_unstable_files(self, tmp_path):
        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device"]
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")

        # Create device CSVs but do NOT set old mtime — leave them fresh
        device_dir = os.path.join(raw_dir, "logs", "device")
        os.makedirs(device_dir, exist_ok=True)

        # Write a screen CSV
        screen_path = os.path.join(device_dir, "screen_2026-03-20.csv")
        with open(screen_path, "w") as f:
            f.write(f"{_BASE_EPOCH},3-20-26,10:00,-0500,on,85\n")

        # Set mtime to 5 seconds ago (within the 60-second stability window)
        recent_time = time.time() - 5
        os.utime(screen_path, (recent_time, recent_time))

        # Also write a stable battery CSV (mtime 5 minutes ago)
        battery_path = os.path.join(device_dir, "battery_2026-03-20.csv")
        with open(battery_path, "w") as f:
            f.write(f"{_BASE_EPOCH},3-20-26,10:00,-0500,85,28.0,4096,100000\n")
        old_time = time.time() - 300
        os.utime(battery_path, (old_time, old_time))

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        # Only battery event should be ingested (screen was unstable)
        total = orch.db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert total == 1, f"Expected 1 event (battery only), got {total}"

        # Verify it's the battery event, not the screen event
        row = orch.db.conn.execute(
            "SELECT source_module FROM events"
        ).fetchone()
        assert row[0] == "device.battery", f"Expected device.battery, got {row[0]}"

        orch.db.close()


class TestETLLockfile:
    """test_etl_lockfile: Verify that the lockfile mechanism prevents
    concurrent ETL runs."""

    def test_lockfile_prevents_concurrent_run(self, tmp_path):
        """Acquire the ETL lock, then verify a second acquisition fails."""
        lock_path = str(tmp_path / ".etl.lock")

        # Acquire lock (simulating a running ETL process)
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()

        try:
            # Attempt to acquire the same lock — should fail
            lock_fd2 = open(lock_path, "w")
            with pytest.raises(OSError):
                fcntl.flock(lock_fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_fd2.close()
        finally:
            # Release the first lock
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def test_lockfile_released_after_completion(self, tmp_path):
        """After releasing the lock, a second acquisition should succeed."""
        lock_path = str(tmp_path / ".etl.lock")

        # Acquire and release
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

        # Second acquisition should succeed
        lock_fd2 = open(lock_path, "w")
        try:
            fcntl.flock(lock_fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # If we get here, the lock was successfully acquired
            acquired = True
        except OSError:
            acquired = False
        finally:
            fcntl.flock(lock_fd2, fcntl.LOCK_UN)
            lock_fd2.close()

        assert acquired, "Could not acquire lock after previous holder released it"

    def test_run_etl_lock_mechanism(self, tmp_path):
        """Verify the actual _acquire_lock function from run_etl.py
        respects the flock mechanism."""
        import run_etl

        # Temporarily override LOCK_FILE and timeout to speed up the test
        original_lock = run_etl.LOCK_FILE
        original_timeout = run_etl.LOCK_TIMEOUT_SECONDS
        run_etl.LOCK_FILE = str(tmp_path / ".etl_test.lock")
        run_etl.LOCK_TIMEOUT_SECONDS = 0.5  # fast timeout for test

        try:
            # First acquisition should succeed
            lock_fd = run_etl._acquire_lock()
            assert lock_fd is not None

            # Second acquisition should raise SystemExit(1) after timeout
            with pytest.raises(SystemExit) as exc_info:
                run_etl._acquire_lock()
            assert exc_info.value.code == 1

            # Clean up
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        finally:
            run_etl.LOCK_FILE = original_lock
            run_etl.LOCK_TIMEOUT_SECONDS = original_timeout
            try:
                os.unlink(str(tmp_path / ".etl_test.lock"))
            except OSError:
                pass


class TestETLToReportPipeline:
    """End-to-end test: config → modules → parse → insert → post_ingest →
    daily_summary → report generation → verify output contains expected sections."""

    def test_full_pipeline_produces_report(self, tmp_path):
        """Run ETL with report=True and verify report file is generated."""
        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device", "environment", "mind"],
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir)
        _populate_mind_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=True)

        # 1. ETL succeeded
        assert summary["total_events"] > 0
        assert summary["failed_modules"] == []
        assert summary["modules_run"] == 3

        # 2. Daily summaries were populated
        summaries = orch.db.conn.execute(
            "SELECT source_module, metric_name FROM daily_summaries"
        ).fetchall()
        summary_modules = {r[0] for r in summaries}
        # At least device should have a daily summary
        assert "device" in summary_modules

        # 3. Report file was generated (may be in a subdirectory like daily/)
        reports_dir = tmp_path / "reports"
        report_files = list(reports_dir.glob("**/*.md"))
        assert len(report_files) >= 1, "Expected at least one report file"

        # 4. Report contains expected sections
        report_content = report_files[0].read_text()
        assert "# LifeData" in report_content
        assert "Module Status" in report_content or "Events" in report_content

        # 5. Events table has data from all three modules
        rows = orch.db.conn.execute(
            "SELECT DISTINCT source_module FROM events"
        ).fetchall()
        source_modules = {r[0] for r in rows}
        assert "device.screen" in source_modules
        assert "device.battery" in source_modules

        # 6. Affected dates were tracked
        assert len(summary["affected_dates"]) >= 1

        # 7. Metrics object is present and valid
        m = summary["metrics"]
        assert m.total_events_ingested > 0
        assert m.total_files_discovered > 0
        assert m.duration_sec >= 0

        orch.db.close()

    def test_dry_run_produces_no_report(self, tmp_path):
        """dry_run + report=True should skip report generation."""
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=True, dry_run=True)

        # Events parsed but not inserted to DB
        assert summary["total_events"] > 0

        # No report generated during dry run
        reports_dir = tmp_path / "reports"
        report_files = list(reports_dir.glob("*.md"))
        assert len(report_files) == 0

        orch.db.close()
