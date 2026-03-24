"""
LifeData V4 — Meta Module: Sync Health Checks
modules/meta/sync.py

Monitors Syncthing sync lag, database backup freshness,
and Syncthing relay configuration.
"""

import os
import time

from core.logger import get_logger

log = get_logger("lifedata.meta.sync")


def check_sync_lag(raw_base: str) -> dict:
    """Check if Syncthing is keeping up by examining newest file age.

    Args:
        raw_base: Path to raw data directory (~ allowed).

    Returns:
        Dict with newest_file_age_minutes, healthy, warning, critical.
    """
    expanded = os.path.expanduser(raw_base)
    if not os.path.isdir(expanded):
        return {
            "newest_file_age_minutes": -1,
            "healthy": False,
            "warning": False,
            "critical": True,
            "message": f"Raw base directory not found: {expanded}",
        }

    newest_mtime = 0
    for root, _dirs, files in os.walk(expanded):
        for f in files:
            try:
                mtime = os.path.getmtime(os.path.join(root, f))
                newest_mtime = max(newest_mtime, mtime)
            except OSError:
                continue

    if newest_mtime == 0:
        return {
            "newest_file_age_minutes": -1,
            "healthy": False,
            "warning": False,
            "critical": True,
            "message": "No files found in raw base directory",
        }

    lag_minutes = (time.time() - newest_mtime) / 60
    healthy = lag_minutes < 120
    warning = 120 <= lag_minutes < 360
    critical = lag_minutes >= 360

    if critical:
        msg = f"CRITICAL — sync lag {round(lag_minutes)} min (>6 hours)"
    elif warning:
        msg = f"WARNING — sync lag {round(lag_minutes)} min (>2 hours)"
    else:
        msg = f"OK — newest file {round(lag_minutes)} min ago"

    return {
        "newest_file_age_minutes": round(lag_minutes),
        "healthy": healthy,
        "warning": warning,
        "critical": critical,
        "message": msg,
    }


def check_db_backup_age(db_path: str, max_age_days: int = 1) -> dict:
    """Verify a recent database backup exists.

    Args:
        db_path: Path to the database file (~ allowed).
        max_age_days: Maximum acceptable backup age.

    Returns:
        Dict with healthy status and backup age details.
    """
    backup_dir = os.path.join(os.path.dirname(os.path.expanduser(db_path)), "backups")

    if not os.path.isdir(backup_dir):
        return {
            "healthy": False,
            "newest_backup_age_days": None,
            "message": "No backup directory exists. Run ETL to create first backup.",
        }

    backup_files = [
        f for f in os.listdir(backup_dir) if os.path.isfile(os.path.join(backup_dir, f))
    ]

    if not backup_files:
        return {
            "healthy": False,
            "newest_backup_age_days": None,
            "message": "No backups found in backup directory.",
        }

    newest = max(os.path.getmtime(os.path.join(backup_dir, f)) for f in backup_files)
    age_days = (time.time() - newest) / 86400

    healthy = age_days <= max_age_days
    if healthy:
        msg = f"OK — backup {round(age_days, 1)}d old"
    else:
        msg = f"WARNING — newest backup is {round(age_days, 1)} days old"

    return {
        "healthy": healthy,
        "newest_backup_age_days": round(age_days, 2),
        "message": msg,
    }


def verify_syncthing_relay(
    api_key: str, api_url: str = "http://localhost:8384"
) -> dict:
    """Query the Syncthing REST API to verify relay is disabled.

    This is called BEFORE data ingestion as a security gate.
    If relay is enabled, LifeData data may traverse third-party servers.

    Args:
        api_key: Syncthing API key.
        api_url: Syncthing REST API base URL.

    Returns:
        Dict with relay status and health assessment.
    """
    import json
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{api_url}/rest/config/options",
            headers={"X-API-Key": api_key},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            config = json.loads(resp.read())

        relay_enabled = config.get("relaysEnabled", True)
        return {
            "relay_enabled": relay_enabled,
            "healthy": not relay_enabled,
            "message": (
                "OK — relay is disabled"
                if not relay_enabled
                else "CRITICAL — Syncthing relay is ENABLED. "
                "LifeData data may traverse third-party servers."
            ),
        }
    except Exception as e:
        return {
            "relay_enabled": None,
            "healthy": False,
            "message": f"Could not connect to Syncthing API: {e}",
        }
