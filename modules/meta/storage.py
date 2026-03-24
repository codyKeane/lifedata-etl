"""
LifeData V4 — Meta Module: Storage Monitor
modules/meta/storage.py

Monitors disk usage across all LifeData directories and enforces
retention policies for raw files and logs.
"""

import os
import shutil
import time

from core.logger import get_logger

log = get_logger("lifedata.meta.storage")


def get_dir_size(path: str) -> int:
    """Recursively compute directory size in bytes.

    Args:
        path: Absolute or ~ path to directory.

    Returns:
        Total size in bytes. 0 if path doesn't exist.
    """
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return 0

    if os.path.isfile(expanded):
        return os.path.getsize(expanded)

    total = 0
    for dirpath, _dirnames, filenames in os.walk(expanded):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


def storage_report(config: dict) -> dict:
    """Report on disk usage across all LifeData directories.

    Args:
        config: Full config.yaml dict.

    Returns:
        Dict with per-directory sizes and overall disk usage.
    """
    ld = config.get("lifedata", config)
    paths = {
        "database": ld.get("db_path", "~/LifeData/db/lifedata.db"),
        "raw_data": ld.get("raw_base", "~/LifeData/raw"),
        "media": ld.get("media_base", "~/LifeData/media"),
        "reports": ld.get("reports_dir", "~/LifeData/reports"),
        "logs": "~/LifeData/logs",
    }

    report: dict = {}
    for name, path in paths.items():
        expanded = os.path.expanduser(path)
        if os.path.exists(expanded):
            size = get_dir_size(expanded)
            report[name] = {
                "path": expanded,
                "size_mb": round(size / 1024 / 1024, 2),
            }

    # Overall disk free space
    try:
        lifedata_dir = os.path.expanduser("~/LifeData")
        total, used, free = shutil.disk_usage(lifedata_dir)
        report["disk"] = {
            "total_gb": round(total / 1024**3, 1),
            "used_gb": round(used / 1024**3, 1),
            "free_gb": round(free / 1024**3, 1),
            "used_pct": round(used / total * 100, 1),
        }
    except Exception as e:
        log.warning(f"Could not determine disk usage: {e}")

    return report


def enforce_retention_policy(config: dict) -> dict:
    """Enforce retention policies from config.yaml.

    Deletes raw files older than raw_files_days and rotates old logs.

    Args:
        config: Full config.yaml dict.

    Returns:
        Summary dict with counts of deleted files.
    """
    ld = config.get("lifedata", config)
    retention = ld.get("retention", {})
    raw_files_days = retention.get("raw_files_days", 365)
    log_rotation_days = retention.get("log_rotation_days", 30)

    now = time.time()
    raw_cutoff = now - (raw_files_days * 86400)
    log_cutoff = now - (log_rotation_days * 86400)

    summary = {"raw_deleted": 0, "logs_deleted": 0}

    # Prune old raw files
    raw_base = os.path.expanduser(ld.get("raw_base", "~/LifeData/raw"))

    # Safety check: refuse to run retention on suspiciously short paths
    # to prevent accidental deletion of system files from misconfiguration
    raw_real = os.path.realpath(raw_base)
    if len(raw_real.split(os.sep)) < 4 or "LifeData" not in raw_real:
        log.error(
            f"Retention policy refused: raw_base '{raw_real}' looks unsafe "
            f"(must be at least 4 levels deep and contain 'LifeData')"
        )
        return summary

    if os.path.isdir(raw_base):
        for root, _dirs, files in os.walk(raw_base):
            for f in files:
                fpath = os.path.join(root, f)
                try:
                    if os.path.getmtime(fpath) < raw_cutoff:
                        os.remove(fpath)
                        log.info(f"Retention: deleted old raw file {fpath}")
                        summary["raw_deleted"] += 1
                except OSError as e:
                    log.warning(f"Could not delete {fpath}: {e}")

    # Prune old log files
    log_dir = os.path.expanduser("~/LifeData/logs")
    if os.path.isdir(log_dir):
        for f in os.listdir(log_dir):
            fpath = os.path.join(log_dir, f)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < log_cutoff:
                    os.remove(fpath)
                    log.info(f"Retention: deleted old log {fpath}")
                    summary["logs_deleted"] += 1
            except OSError as e:
                log.warning(f"Could not delete {fpath}: {e}")

    log.info(
        f"Retention policy enforced: "
        f"{summary['raw_deleted']} raw, {summary['logs_deleted']} logs deleted"
    )

    return summary
