"""
Tests for modules/meta/sync.py — sync health checks.

Covers:
  - check_sync_lag: healthy/warning/critical states, missing dir, empty dir
  - check_db_backup_age: recent backup, old backup, no backup dir, no backup files
  - verify_syncthing_relay: relay disabled (healthy), relay enabled, connection error
"""

import json
import os
import time
from unittest.mock import MagicMock, patch

from modules.meta.sync import check_db_backup_age, check_sync_lag, verify_syncthing_relay

# ──────────────────────────────────────────────────────────────
# check_sync_lag
# ──────────────────────────────────────────────────────────────


class TestCheckSyncLag:
    def test_healthy_recent_files(self, tmp_path):
        """Files modified within 2 hours → healthy."""
        f = tmp_path / "recent.csv"
        f.write_text("data")
        # mtime is current (just created), so lag < 120 min

        result = check_sync_lag(str(tmp_path))
        assert result["healthy"] is True
        assert result["warning"] is False
        assert result["critical"] is False
        assert result["newest_file_age_minutes"] < 120
        assert "OK" in result["message"]

    def test_warning_stale_files(self, tmp_path):
        """Files 3 hours old → warning (120-360 min)."""
        f = tmp_path / "stale.csv"
        f.write_text("old data")
        old_mtime = time.time() - (3 * 3600)  # 3 hours ago = 180 min
        os.utime(f, (old_mtime, old_mtime))

        result = check_sync_lag(str(tmp_path))
        assert result["healthy"] is False
        assert result["warning"] is True
        assert result["critical"] is False
        assert 120 <= result["newest_file_age_minutes"] < 360
        assert "WARNING" in result["message"]

    def test_critical_very_stale_files(self, tmp_path):
        """Files 7 hours old → critical (>360 min)."""
        f = tmp_path / "very_stale.csv"
        f.write_text("ancient data")
        old_mtime = time.time() - (7 * 3600)  # 7 hours ago = 420 min
        os.utime(f, (old_mtime, old_mtime))

        result = check_sync_lag(str(tmp_path))
        assert result["healthy"] is False
        assert result["warning"] is False
        assert result["critical"] is True
        assert result["newest_file_age_minutes"] >= 360
        assert "CRITICAL" in result["message"]

    def test_missing_directory(self, tmp_path):
        """Non-existent directory → critical with -1 age."""
        result = check_sync_lag(str(tmp_path / "nonexistent"))
        assert result["healthy"] is False
        assert result["critical"] is True
        assert result["newest_file_age_minutes"] == -1
        assert "not found" in result["message"]

    def test_empty_directory(self, tmp_path):
        """Directory with no files → critical with -1 age."""
        empty = tmp_path / "empty"
        empty.mkdir()

        result = check_sync_lag(str(empty))
        assert result["healthy"] is False
        assert result["critical"] is True
        assert result["newest_file_age_minutes"] == -1
        assert "No files found" in result["message"]

    def test_nested_files_considered(self, tmp_path):
        """Newest file in subdirectory is found."""
        sub = tmp_path / "sub" / "deep"
        sub.mkdir(parents=True)

        # Old file at top level
        old = tmp_path / "old.csv"
        old.write_text("old")
        old_mtime = time.time() - (5 * 3600)  # 5 hours ago
        os.utime(old, (old_mtime, old_mtime))

        # Recent file in subdirectory
        recent = sub / "recent.csv"
        recent.write_text("new")
        # mtime is current

        result = check_sync_lag(str(tmp_path))
        # Should report healthy because the newest file (recent.csv) is current
        assert result["healthy"] is True
        assert result["newest_file_age_minutes"] < 120


# ──────────────────────────────────────────────────────────────
# check_db_backup_age
# ──────────────────────────────────────────────────────────────


class TestCheckDbBackupAge:
    def test_recent_backup_is_healthy(self, tmp_path):
        """Backup file created today → healthy."""
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        backup_dir = db_dir / "backups"
        backup_dir.mkdir()

        backup = backup_dir / "lifedata_backup.db"
        backup.write_text("backup data")
        # mtime is current

        db_path = str(db_dir / "lifedata.db")
        result = check_db_backup_age(db_path, max_age_days=1)
        assert result["healthy"] is True
        assert result["newest_backup_age_days"] < 1
        assert "OK" in result["message"]

    def test_old_backup_is_unhealthy(self, tmp_path):
        """Backup older than max_age_days → unhealthy."""
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        backup_dir = db_dir / "backups"
        backup_dir.mkdir()

        backup = backup_dir / "old_backup.db"
        backup.write_text("old backup")
        old_mtime = time.time() - (3 * 86400)  # 3 days ago
        os.utime(backup, (old_mtime, old_mtime))

        db_path = str(db_dir / "lifedata.db")
        result = check_db_backup_age(db_path, max_age_days=1)
        assert result["healthy"] is False
        assert result["newest_backup_age_days"] > 1
        assert "WARNING" in result["message"]

    def test_no_backup_directory(self, tmp_path):
        """No backups/ directory → unhealthy."""
        db_dir = tmp_path / "db"
        db_dir.mkdir()

        db_path = str(db_dir / "lifedata.db")
        result = check_db_backup_age(db_path)
        assert result["healthy"] is False
        assert result["newest_backup_age_days"] is None
        assert "No backup directory" in result["message"]

    def test_empty_backup_directory(self, tmp_path):
        """Backup directory exists but has no files → unhealthy."""
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        backup_dir = db_dir / "backups"
        backup_dir.mkdir()

        db_path = str(db_dir / "lifedata.db")
        result = check_db_backup_age(db_path)
        assert result["healthy"] is False
        assert result["newest_backup_age_days"] is None
        assert "No backups found" in result["message"]

    def test_multiple_backups_uses_newest(self, tmp_path):
        """With multiple backups, checks age of the newest one."""
        db_dir = tmp_path / "db"
        db_dir.mkdir()
        backup_dir = db_dir / "backups"
        backup_dir.mkdir()

        # Old backup
        old = backup_dir / "backup_old.db"
        old.write_text("old")
        old_mtime = time.time() - (5 * 86400)
        os.utime(old, (old_mtime, old_mtime))

        # Recent backup
        recent = backup_dir / "backup_recent.db"
        recent.write_text("recent")
        # mtime is current

        db_path = str(db_dir / "lifedata.db")
        result = check_db_backup_age(db_path, max_age_days=1)
        assert result["healthy"] is True
        assert result["newest_backup_age_days"] < 1


# ──────────────────────────────────────────────────────────────
# verify_syncthing_relay
# ──────────────────────────────────────────────────────────────


class TestVerifySyncthingRelay:
    @patch("urllib.request.urlopen")
    def test_relay_disabled_is_healthy(self, mock_urlopen):
        """Syncthing relay disabled → healthy."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"relaysEnabled": False}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = verify_syncthing_relay("test-api-key")
        assert result["healthy"] is True
        assert result["relay_enabled"] is False
        assert "disabled" in result["message"]

    @patch("urllib.request.urlopen")
    def test_relay_enabled_is_critical(self, mock_urlopen):
        """Syncthing relay enabled → unhealthy/critical."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"relaysEnabled": True}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = verify_syncthing_relay("test-api-key")
        assert result["healthy"] is False
        assert result["relay_enabled"] is True
        assert "ENABLED" in result["message"]

    @patch("urllib.request.urlopen")
    def test_connection_error_is_unhealthy(self, mock_urlopen):
        """Connection failure → unhealthy with error message."""
        mock_urlopen.side_effect = ConnectionError("Connection refused")

        result = verify_syncthing_relay("test-api-key")
        assert result["healthy"] is False
        assert result["relay_enabled"] is None
        assert "Could not connect" in result["message"]

    @patch("urllib.request.urlopen")
    def test_timeout_error_is_unhealthy(self, mock_urlopen):
        """Timeout → unhealthy."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timeout")

        result = verify_syncthing_relay("test-api-key")
        assert result["healthy"] is False
        assert result["relay_enabled"] is None

    @patch("urllib.request.urlopen")
    def test_api_key_passed_in_header(self, mock_urlopen):
        """API key is sent in X-API-Key header."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"relaysEnabled": False}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        verify_syncthing_relay("my-secret-key", api_url="http://custom:8384")

        # Verify the request was made
        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        assert request.get_header("X-api-key") == "my-secret-key"
        assert "custom:8384" in request.full_url
