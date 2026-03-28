"""
Tests for core/orchestrator.py — path safety, env var resolution, module allowlist,
security checks, disk encryption, dry-run mode, report generation, WAL checkpoint
failure handling, quarantine collection, and correlation persistence.
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from core.config import _resolve_env_vars
from core.orchestrator import Orchestrator, enforce_log_rotation

# ──────────────────────────────────────────────────────────────
# Path safety — _is_safe_path
# ──────────────────────────────────────────────────────────────


class TestIsSafePath:
    """Ensure _is_safe_path blocks path traversal attacks."""

    @pytest.fixture
    def raw_base(self, tmp_path):
        """Create a realistic raw_base directory structure."""
        raw = tmp_path / "raw" / "LifeData"
        raw.mkdir(parents=True)
        (raw / "device").mkdir()
        (raw / "device" / "battery_2026.csv").write_text("data")
        # Also create raw/api for world module
        api = tmp_path / "raw" / "api"
        api.mkdir()
        (api / "headlines.json").write_text("{}")
        return str(raw)

    def test_file_inside_raw_base(self, raw_base):
        safe_file = os.path.join(raw_base, "device", "battery_2026.csv")
        assert Orchestrator._is_safe_path(safe_file, raw_base)

    def test_traversal_blocked(self, raw_base):
        bad_path = os.path.join(raw_base, "..", "..", "etc", "passwd")
        assert not Orchestrator._is_safe_path(bad_path, raw_base)

    def test_absolute_outside_blocked(self, raw_base):
        assert not Orchestrator._is_safe_path("/etc/passwd", raw_base)

    def test_raw_api_sibling_allowed(self, raw_base, tmp_path):
        """Files under raw/api/ should be accepted (world module data)."""
        api_file = str(tmp_path / "raw" / "api" / "headlines.json")
        assert Orchestrator._is_safe_path(api_file, raw_base)

    def test_symlink_traversal_blocked(self, raw_base, tmp_path):
        """Symlinks that escape raw_base should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.csv"
        secret.write_text("secret")

        link = os.path.join(raw_base, "evil_link.csv")
        try:
            os.symlink(str(secret), link)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        assert not Orchestrator._is_safe_path(link, raw_base)

    def test_empty_path(self, raw_base):
        assert not Orchestrator._is_safe_path("", raw_base)

    def test_raw_base_itself(self, raw_base):
        assert Orchestrator._is_safe_path(raw_base, raw_base)


# ──────────────────────────────────────────────────────────────
# Environment variable resolution
# ──────────────────────────────────────────────────────────────


class TestResolveEnvVars:
    """Test recursive ${ENV_VAR} substitution in config dicts."""

    def test_simple_substitution(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "secret123")
        config = {"api_key": "${TEST_API_KEY}"}
        _resolve_env_vars(config)
        assert config["api_key"] == "secret123"

    def test_nested_dict(self, monkeypatch):
        monkeypatch.setenv("INNER_VAR", "resolved")
        config = {"outer": {"inner": "${INNER_VAR}"}}
        _resolve_env_vars(config)
        assert config["outer"]["inner"] == "resolved"

    def test_list_values(self, monkeypatch):
        monkeypatch.setenv("LIST_VAR", "item")
        config = {"items": ["${LIST_VAR}", "static"]}
        _resolve_env_vars(config)
        assert config["items"] == ["item", "static"]

    def test_unset_var_becomes_empty(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        config = {"key": "${NONEXISTENT_VAR}"}
        _resolve_env_vars(config)
        assert config["key"] == ""

    def test_no_substitution_without_marker(self):
        config = {"key": "plain_value"}
        _resolve_env_vars(config)
        assert config["key"] == "plain_value"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("A", "hello")
        monkeypatch.setenv("B", "world")
        config = {"msg": "${A} ${B}"}
        _resolve_env_vars(config)
        assert config["msg"] == "hello world"

    def test_non_string_values_untouched(self):
        config = {"count": 42, "flag": True, "ratio": 3.14}
        _resolve_env_vars(config)
        assert config == {"count": 42, "flag": True, "ratio": 3.14}


# ──────────────────────────────────────────────────────────────
# Log rotation — enforce_log_rotation
# ──────────────────────────────────────────────────────────────


class TestLogRotation:
    """Test enforce_log_rotation() deletes old log files correctly."""

    def test_old_log_file_deleted(self, tmp_path):
        """Log files older than max_age_days should be deleted."""
        old_log = tmp_path / "etl.log"
        old_log.write_text("old log data")
        # Set mtime to 45 days ago
        old_mtime = time.time() - (45 * 86400)
        os.utime(old_log, (old_mtime, old_mtime))

        enforce_log_rotation(str(tmp_path), max_age_days=30)

        assert not old_log.exists()

    def test_recent_log_file_kept(self, tmp_path):
        """Log files newer than max_age_days should be kept."""
        recent_log = tmp_path / "etl.log"
        recent_log.write_text("recent log data")
        # mtime is now (default), well within 30 days

        enforce_log_rotation(str(tmp_path), max_age_days=30)

        assert recent_log.exists()

    def test_non_log_file_not_touched(self, tmp_path):
        """Non-log files should never be deleted regardless of age."""
        data_file = tmp_path / "important.db"
        data_file.write_text("database data")
        old_mtime = time.time() - (45 * 86400)
        os.utime(data_file, (old_mtime, old_mtime))

        enforce_log_rotation(str(tmp_path), max_age_days=30)

        assert data_file.exists()

    def test_nonexistent_directory(self):
        """Non-existent log directory should be a no-op (no crash)."""
        enforce_log_rotation("/tmp/nonexistent_lifedata_test_dir", max_age_days=30)

    def test_old_jsonl_file_deleted(self, tmp_path):
        """JSONL files older than max_age_days should also be deleted."""
        old_jsonl = tmp_path / "metrics.jsonl"
        old_jsonl.write_text('{"run": 1}')
        old_mtime = time.time() - (45 * 86400)
        os.utime(old_jsonl, (old_mtime, old_mtime))

        enforce_log_rotation(str(tmp_path), max_age_days=30)

        assert not old_jsonl.exists()

    def test_permission_error_handled(self, tmp_path):
        """OSError during unlink should be logged, not raised."""
        old_log = tmp_path / "etl.log"
        old_log.write_text("data")
        old_mtime = time.time() - (45 * 86400)
        os.utime(old_log, (old_mtime, old_mtime))

        with patch.object(type(old_log), "unlink", side_effect=OSError("perm denied")):
            # Should not raise
            enforce_log_rotation(str(tmp_path), max_age_days=30)


# ──────────────────────────────────────────────────────────────
# Helpers — reuse integration test helpers
# ──────────────────────────────────────────────────────────────


def _setup_orchestrator(tmp_path, allowlist=None, extra_modules=None):
    """Set up and return an Orchestrator from the integration helpers."""
    from tests.test_etl_integration import (
        _make_orchestrator,
        _write_config_yaml,
    )
    config_path, env_path = _write_config_yaml(
        tmp_path, allowlist=allowlist, extra_modules=extra_modules,
    )
    return _make_orchestrator(config_path, env_path), config_path, env_path


# ──────────────────────────────────────────────────────────────
# Startup security checks — _check_startup_security
# ──────────────────────────────────────────────────────────────


class TestStartupSecurity:
    """Test _check_startup_security advisory warnings."""

    def test_env_bad_permissions_warns(self, tmp_path):
        """Warn when .env has permissions other than 0600."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])

        env_file = tmp_path / ".env_test_sec"
        env_file.write_text("SECRET=foo")
        env_file.chmod(0o644)

        with patch("core.orchestrator.os.path.expanduser", return_value=str(env_file)):
            with patch("core.orchestrator.os.path.exists", return_value=True):
                with patch("core.orchestrator.os.stat") as mock_stat:
                    mock_stat.return_value = MagicMock(st_mode=0o100644)
                    warnings = orch._check_startup_security(str(tmp_path / "config.yaml"))

        assert any(".env permissions" in w for w in warnings)
        orch.db.close()

    def test_stfolder_warns(self, tmp_path):
        """Warn when ~/LifeData contains .stfolder (Syncthing shared folder)."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])
        lifedata_dir = tmp_path / "LifeData_sec"
        lifedata_dir.mkdir()
        (lifedata_dir / ".stfolder").mkdir()

        real_expanduser = os.path.expanduser

        def fake_expanduser(p):
            if p == "~/LifeData/.env":
                return str(lifedata_dir / ".env")
            if p == "~/LifeData":
                return str(lifedata_dir)
            return real_expanduser(p)

        with patch("core.orchestrator.os.path.expanduser", side_effect=fake_expanduser):
            warnings = orch._check_startup_security(str(tmp_path / "config.yaml"))

        assert any(".stfolder" in w for w in warnings)
        orch.db.close()

    def test_no_warnings_when_all_clean(self, tmp_path):
        """When all checks pass, return empty warnings list."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])

        # Mock everything to look clean
        with patch("core.orchestrator.os.path.expanduser") as mock_eu:
            mock_eu.return_value = "/nonexistent/path"
            with patch("core.orchestrator.os.path.exists", return_value=False):
                with patch("core.orchestrator.os.path.isdir", return_value=False):
                    warnings = orch._check_startup_security("/nonexistent/config.yaml")

        assert warnings == []
        orch.db.close()


# ──────────────────────────────────────────────────────────────
# Disk encryption check — _check_disk_encryption
# ──────────────────────────────────────────────────────────────


class TestDiskEncryption:
    """Test _check_disk_encryption best-effort logic."""

    def test_luks_device_detected(self):
        """dm-crypt/LUKS volume (/dev/mapper/*) should pass without warning."""
        warnings: list[str] = []
        result = MagicMock(returncode=0, stdout="Filesystem\n/dev/mapper/cryptroot\n")
        with patch("core.orchestrator.subprocess.run", return_value=result):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []

    def test_dm_device_detected(self):
        """dm-* device should pass without warning."""
        warnings: list[str] = []
        result = MagicMock(returncode=0, stdout="Filesystem\n/dev/dm-0\n")
        with patch("core.orchestrator.subprocess.run", return_value=result):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []

    def test_fscrypt_detected(self):
        """fscrypt policy active should pass without warning."""
        warnings: list[str] = []
        df_result = MagicMock(returncode=0, stdout="Filesystem\n/dev/sda1\n")
        fscrypt_result = MagicMock(returncode=0)
        with patch("core.orchestrator.subprocess.run", side_effect=[df_result, fscrypt_result]):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []

    def test_no_encryption_warns(self):
        """Non-encrypted device should produce a warning."""
        warnings: list[str] = []
        df_result = MagicMock(returncode=0, stdout="Filesystem\n/dev/sda1\n")
        fscrypt_result = MagicMock(returncode=1)
        with patch("core.orchestrator.subprocess.run", side_effect=[df_result, fscrypt_result]):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert len(warnings) == 1
        assert "No disk encryption" in warnings[0]

    def test_df_command_fails(self):
        """df failure should silently return (no warning)."""
        warnings: list[str] = []
        result = MagicMock(returncode=1, stdout="")
        with patch("core.orchestrator.subprocess.run", return_value=result):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []

    def test_df_not_installed(self):
        """FileNotFoundError (df not installed) should be caught."""
        warnings: list[str] = []
        with patch("core.orchestrator.subprocess.run", side_effect=FileNotFoundError):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []

    def test_df_output_too_short(self):
        """df output with no device line should return safely."""
        warnings: list[str] = []
        result = MagicMock(returncode=0, stdout="Filesystem\n")
        with patch("core.orchestrator.subprocess.run", return_value=result):
            Orchestrator._check_disk_encryption("/home/user", warnings)
        assert warnings == []


# ──────────────────────────────────────────────────────────────
# Module discovery — discover_modules
# ──────────────────────────────────────────────────────────────


class TestDiscoverModules:
    """Test module discovery, allowlist enforcement, disabled modules."""

    def test_single_module_filter(self, tmp_path):
        """--module flag should only load the specified module."""
        orch, _, _ = _setup_orchestrator(
            tmp_path, allowlist=["device", "environment"]
        )
        orch.discover_modules(single_module="device")
        assert len(orch.modules) == 1
        assert orch.modules[0].module_id == "device"
        orch.db.close()

    def test_disabled_module_skipped(self, tmp_path):
        """Module with enabled: false should not be loaded."""
        orch, _, _ = _setup_orchestrator(
            tmp_path,
            allowlist=["device", "environment"],
            extra_modules={
                "device": {"enabled": True},
                "environment": {"enabled": False},
            },
        )
        orch.discover_modules()
        module_ids = [m.module_id for m in orch.modules]
        assert "device" in module_ids
        assert "environment" not in module_ids
        orch.db.close()

    def test_invalid_disabled_metric_warns(self, tmp_path):
        """disabled_metrics with a bogus name should log a warning."""
        orch, _, _ = _setup_orchestrator(
            tmp_path,
            allowlist=["device"],
            extra_modules={
                "device": {"enabled": True, "disabled_metrics": ["nonexistent_metric"]},
            },
        )
        with patch("core.orchestrator.log") as mock_log:
            orch.discover_modules()
            # Check that a warning about "not found in metrics manifest" was logged
            warning_calls = [str(c) for c in mock_log.warning.call_args_list]
            assert any("nonexistent_metric" in w for w in warning_calls)
        orch.db.close()

    def test_empty_allowlist_refuses_all(self, tmp_path):
        """Empty allowlist should refuse to load any modules (fail-closed)."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])
        # Override the allowlist to empty after init
        orch.config.lifedata.security.module_allowlist = []
        orch.discover_modules()
        assert orch.modules == []
        orch.db.close()

    def test_module_not_in_allowlist_skipped(self, tmp_path):
        """Module not in allowlist should be skipped."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])
        orch.discover_modules()
        module_ids = [m.module_id for m in orch.modules]
        assert "device" in module_ids
        assert "environment" not in module_ids
        orch.db.close()


# ──────────────────────────────────────────────────────────────
# Orchestrator.run() — dry-run, report, quarantine, checkpoint
# ──────────────────────────────────────────────────────────────


class TestOrchestratorRun:
    """Test the main run() method covering dry-run, report, and error paths."""

    def test_dry_run_no_db_writes(self, tmp_path):
        """dry_run=True should parse events but not insert them."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(dry_run=True)

        # Events counted but total_events is the "inserted" count in dry-run
        assert summary["total_events"] > 0
        assert summary["modules_run"] == 1

        # No actual DB inserts — events table should be empty
        import sqlite3
        conn = sqlite3.connect(orch.config.lifedata.db_path)
        count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        assert count == 0
        orch.db.close()

    def test_dry_run_skips_backup_and_post_ingest(self, tmp_path):
        """dry_run should not call backup() or post_ingest()."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch.object(orch.db, "backup") as mock_backup:
            summary = orch.run(dry_run=True)
            mock_backup.assert_not_called()
        orch.db.close()

    def test_report_generation_on_run(self, tmp_path):
        """report=True should trigger report generation."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch("analysis.reports.generate_daily_report") as mock_report:
            summary = orch.run(report=True)
            mock_report.assert_called_once()
        orch.db.close()

    def test_report_generation_exception_handled(self, tmp_path):
        """Report generation failure should not crash the run."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch("analysis.reports.generate_daily_report", side_effect=RuntimeError("report boom")):
            summary = orch.run(report=True)
        # Should still return results, not crash
        assert summary["modules_run"] == 1
        orch.db.close()

    def test_wal_checkpoint_failure_handled(self, tmp_path):
        """WAL checkpoint failure should be logged, not raised."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch.object(orch.db, "checkpoint", side_effect=RuntimeError("WAL fail")):
            summary = orch.run(report=False)
        assert summary["modules_run"] == 1
        orch.db.close()

    def test_no_modules_loaded(self, tmp_path):
        """When no modules match, run() returns early with zero counts."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])

        orch = _make_orchestrator(config_path, env_path)
        # Force the module to be disabled
        orch.config.lifedata.modules.device.enabled = False
        summary = orch.run()
        assert summary["total_events"] == 0
        assert summary["modules_run"] == 0
        orch.db.close()

    def test_quarantine_collection(self, tmp_path):
        """Modules with quarantined_files attribute should have them collected."""
        from modules.device.module import DeviceModule
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )

        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        # Mock the quarantined_files property to return a non-empty list
        with patch.object(
            DeviceModule, "quarantined_files",
            new_callable=lambda: property(lambda self: ["/fake/quarantined.csv"]),
        ):
            summary = orch.run()

        assert summary["quarantined_files"] == ["/fake/quarantined.csv"]
        orch.db.close()

    def test_persist_correlations_called_on_normal_run(self, tmp_path):
        """_persist_correlations should be called during a normal (non-dry) run."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch.object(orch, "_persist_correlations") as mock_corr:
            summary = orch.run(report=False)
            mock_corr.assert_called_once()
        assert summary["modules_run"] == 1
        orch.db.close()

    def test_persist_correlations_skipped_on_dry_run(self, tmp_path):
        """_persist_correlations should NOT be called during dry run."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch.object(orch, "_persist_correlations") as mock_corr:
            summary = orch.run(dry_run=True)
            mock_corr.assert_not_called()
        orch.db.close()

    def test_module_failure_recorded(self, tmp_path):
        """A module that throws during discover_files should be marked failed."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device", "environment"]
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch(
            "modules.environment.module.EnvironmentModule.discover_files",
            side_effect=RuntimeError("crash"),
        ):
            summary = orch.run()

        assert "environment" in summary["failed_modules"]
        orch.db.close()

    def test_post_ingest_failure_does_not_crash(self, tmp_path):
        """post_ingest failure should not undo inserted events."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch(
            "modules.device.module.DeviceModule.post_ingest",
            side_effect=RuntimeError("post_ingest boom"),
        ):
            summary = orch.run()

        assert summary["total_events"] > 0
        assert summary["failed_modules"] == []  # post_ingest failure != module failure
        orch.db.close()

    def test_metrics_write_failure_handled(self, tmp_path):
        """Failure to write metrics.jsonl should not crash the run."""
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )
        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch("core.orchestrator.write_metrics", side_effect=OSError("no space")):
            summary = orch.run()
        assert summary["modules_run"] == 1
        orch.db.close()


# ──────────────────────────────────────────────────────────────
# Persist correlations
# ──────────────────────────────────────────────────────────────


class TestPersistCorrelations:
    """Test _persist_correlations in isolation."""

    def test_no_correlation_metrics_is_noop(self, tmp_path):
        """When weekly_correlation_metrics is empty, no correlation work happens."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])
        # Default config has no correlation metrics — should be a no-op
        orch._persist_correlations()  # Should not raise
        orch.db.close()

    def test_correlation_exception_caught(self, tmp_path):
        """Exception in correlation module should be caught."""
        orch, _, _ = _setup_orchestrator(tmp_path, allowlist=["device"])
        with patch("importlib.import_module", side_effect=ImportError("no correlator")):
            orch._persist_correlations()  # Should not raise
        orch.db.close()
