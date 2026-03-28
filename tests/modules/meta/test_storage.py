"""
Tests for modules/meta/storage.py — disk usage monitoring and retention enforcement.

Covers:
  - get_dir_size: existing dir, nested dirs, missing dir, single file, OSError
  - storage_report: reports sizes for configured directories
  - enforce_retention_policy: deletes old files, respects safety check, handles missing dirs
"""

import os
import time

from modules.meta.storage import enforce_retention_policy, get_dir_size, storage_report

# ──────────────────────────────────────────────────────────────
# get_dir_size
# ──────────────────────────────────────────────────────────────


class TestGetDirSize:
    def test_existing_directory(self, tmp_path):
        """Directory with files returns correct total size."""
        f1 = tmp_path / "a.txt"
        f1.write_text("hello")  # 5 bytes
        f2 = tmp_path / "b.txt"
        f2.write_text("world!")  # 6 bytes

        size = get_dir_size(str(tmp_path))
        assert size == 11

    def test_nested_directories(self, tmp_path):
        """Recursively sums files in subdirectories."""
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)
        (tmp_path / "top.txt").write_text("aaa")  # 3 bytes
        (sub / "deep.txt").write_text("bbbbb")  # 5 bytes

        size = get_dir_size(str(tmp_path))
        assert size == 8

    def test_missing_directory_returns_zero(self, tmp_path):
        """Non-existent path returns 0."""
        size = get_dir_size(str(tmp_path / "does_not_exist"))
        assert size == 0

    def test_single_file(self, tmp_path):
        """Path pointing to a file returns that file's size."""
        f = tmp_path / "single.txt"
        f.write_text("1234567890")  # 10 bytes

        size = get_dir_size(str(f))
        assert size == 10

    def test_empty_directory(self, tmp_path):
        """Empty directory returns 0."""
        empty = tmp_path / "empty"
        empty.mkdir()

        size = get_dir_size(str(empty))
        assert size == 0

    def test_oserror_on_file_is_skipped(self, tmp_path):
        """Files that can't be stat'd are skipped without crashing."""
        f = tmp_path / "good.txt"
        f.write_text("ok")  # 2 bytes

        # Create a symlink to a non-existent target
        bad_link = tmp_path / "bad_link"
        bad_link.symlink_to(tmp_path / "nonexistent_target")

        # Should still return the size of the good file, skipping the broken symlink
        size = get_dir_size(str(tmp_path))
        assert size >= 2


# ──────────────────────────────────────────────────────────────
# storage_report
# ──────────────────────────────────────────────────────────────


class TestStorageReport:
    def test_reports_configured_directories(self, tmp_path):
        """Reports sizes for directories that exist."""
        db_path = tmp_path / "db" / "lifedata.db"
        db_path.parent.mkdir()
        db_path.write_text("x" * (1024 * 1024 + 1))  # ~1MB

        raw = tmp_path / "raw"
        raw.mkdir()
        (raw / "data.csv").write_text("y" * 2048)  # 2KB

        config = {
            "lifedata": {
                "db_path": str(db_path),
                "raw_base": str(raw),
                "media_base": str(tmp_path / "media_nonexistent"),
                "reports_dir": str(tmp_path / "reports_nonexistent"),
            }
        }

        report = storage_report(config)

        # database and raw_data should be present (they exist)
        assert "database" in report
        assert report["database"]["size_mb"] >= 0
        assert "path" in report["database"]
        assert "raw_data" in report
        assert report["raw_data"]["size_mb"] >= 0
        assert "path" in report["raw_data"]

        # media and reports don't exist, should be absent
        assert "media" not in report
        assert "reports" not in report

    def test_empty_config_uses_defaults(self):
        """With empty config, uses ~/LifeData/... defaults."""
        report = storage_report({})
        # Should not crash even if default paths don't exist
        assert isinstance(report, dict)
        # disk info should always be available
        assert "disk" in report


# ──────────────────────────────────────────────────────────────
# enforce_retention_policy
# ──────────────────────────────────────────────────────────────


class TestEnforceRetentionPolicy:
    def test_deletes_old_raw_files(self, tmp_path):
        """Files older than raw_files_days are deleted."""
        # Build a path that passes the safety check (4+ levels, contains "LifeData")
        raw_base = tmp_path / "home" / "user" / "LifeData" / "raw"
        raw_base.mkdir(parents=True)

        old_file = raw_base / "old_data.csv"
        old_file.write_text("old data")
        # Set mtime to 400 days ago
        old_mtime = time.time() - (400 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        new_file = raw_base / "new_data.csv"
        new_file.write_text("new data")
        # Leave mtime as current

        config = {
            "lifedata": {
                "raw_base": str(raw_base),
                "retention": {
                    "raw_files_days": 365,
                    "log_rotation_days": 30,
                },
            }
        }

        summary = enforce_retention_policy(config)
        assert summary["raw_deleted"] == 1
        assert not old_file.exists()
        assert new_file.exists()

    def test_keeps_recent_files(self, tmp_path):
        """Files within retention window are kept."""
        raw_base = tmp_path / "home" / "user" / "LifeData" / "raw"
        raw_base.mkdir(parents=True)

        recent_file = raw_base / "recent.csv"
        recent_file.write_text("recent data")

        config = {
            "lifedata": {
                "raw_base": str(raw_base),
                "retention": {"raw_files_days": 365, "log_rotation_days": 30},
            }
        }

        summary = enforce_retention_policy(config)
        assert summary["raw_deleted"] == 0
        assert recent_file.exists()

    def test_safety_check_refuses_short_paths(self, tmp_path):
        """Paths with <4 levels or missing 'LifeData' are rejected."""
        # Path too shallow (only 2 levels)
        shallow = tmp_path / "raw"
        shallow.mkdir()
        (shallow / "file.csv").write_text("data")

        config = {
            "lifedata": {
                "raw_base": str(shallow),
                "retention": {"raw_files_days": 0, "log_rotation_days": 0},
            }
        }

        summary = enforce_retention_policy(config)
        # Safety check prevents deletion
        assert summary["raw_deleted"] == 0
        assert (shallow / "file.csv").exists()

    def test_missing_raw_directory(self, tmp_path):
        """Non-existent raw_base doesn't crash."""
        config = {
            "lifedata": {
                "raw_base": str(tmp_path / "nonexistent" / "LifeData" / "deep" / "raw"),
                "retention": {"raw_files_days": 365, "log_rotation_days": 30},
            }
        }

        summary = enforce_retention_policy(config)
        assert summary["raw_deleted"] == 0
        assert summary["logs_deleted"] == 0

    def test_deletes_old_log_files(self, tmp_path, monkeypatch):
        """Old log files are pruned."""
        # Create a fake ~/LifeData/logs directory
        log_dir = tmp_path / "LifeData" / "logs"
        log_dir.mkdir(parents=True)

        old_log = log_dir / "etl.log.old"
        old_log.write_text("old log data")
        old_mtime = time.time() - (60 * 86400)  # 60 days ago
        os.utime(old_log, (old_mtime, old_mtime))

        new_log = log_dir / "etl.log"
        new_log.write_text("current log")

        # Monkeypatch expanduser so ~/LifeData/logs points to our tmp dir
        _real_expanduser = os.path.expanduser

        def _patched_expanduser(p: str) -> str:
            if p == "~/LifeData/logs":
                return str(log_dir)
            return _real_expanduser(p)

        monkeypatch.setattr("modules.meta.storage.os.path.expanduser", _patched_expanduser)

        # Need raw_base that passes safety check but doesn't exist
        # so we only test log deletion
        raw_base = tmp_path / "home" / "user" / "LifeData" / "raw_empty"

        config = {
            "lifedata": {
                "raw_base": str(raw_base),
                "retention": {"raw_files_days": 365, "log_rotation_days": 30},
            }
        }

        summary = enforce_retention_policy(config)
        assert summary["logs_deleted"] == 1
        assert not old_log.exists()
        assert new_log.exists()
