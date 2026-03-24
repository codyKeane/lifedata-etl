#!/usr/bin/env python3
"""
LifeData V4 — ETL Entry Point

Usage:
    python run_etl.py                       # Run full ETL
    python run_etl.py --report              # Run ETL + generate daily report
    python run_etl.py --module device       # Run only the device module
    python run_etl.py --dry-run             # Parse but don't write to DB
    python run_etl.py --dry-run --module device  # Parse device only, no writes
    python run_etl.py --status                  # Health summary (last 7 runs)

Cron (nightly at 11:55 PM):
    55 23 * * * cd ~/LifeData && venv/bin/python run_etl.py --report
"""

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.orchestrator import Orchestrator

# Lock file path — prevents concurrent ETL runs
LOCK_FILE = os.path.expanduser("~/LifeData/.etl.lock")


def _acquire_lock():
    """Acquire an exclusive flock on the ETL lock file.

    Returns the open file descriptor (must stay open for the lock to hold).
    Raises SystemExit if another ETL process is already running.
    """
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_fd.close()
        print(
            "FATAL: Another ETL process is already running (could not acquire "
            f"flock on {LOCK_FILE}). Exiting to prevent concurrent writes.",
            file=sys.stderr,
        )
        sys.exit(3)
    # Write PID for debugging
    lock_fd.write(str(os.getpid()))
    lock_fd.flush()
    return lock_fd


METRICS_PATH = os.path.expanduser("~/LifeData/logs/metrics.jsonl")


def _read_last_n_lines(path: str, n: int) -> list[str]:
    """Read the last n lines from a file efficiently."""
    try:
        with open(path, "rb") as f:
            # Seek to end and read backwards to find n newlines
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            # Read up to 64KB from the end — plenty for 7 JSON lines
            chunk = min(size, 65536)
            f.seek(size - chunk)
            lines = f.read().decode("utf-8").strip().splitlines()
            return lines[-n:]
    except FileNotFoundError:
        return []


def _format_bytes(n: int) -> str:
    """Format byte count as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _print_status() -> int:
    """Read last 7 metrics entries and print a health summary table."""
    lines = _read_last_n_lines(METRICS_PATH, 7)

    if not lines:
        print("No metrics found. Run the ETL at least once first.")
        return 0

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not entries:
        print("No valid metrics entries found.")
        return 0

    # Collect all module names across all entries
    all_modules = sorted(
        {m for e in entries for m in e.get("events_per_module", {})}
    )

    # Header
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              LifeData ETL — Health Summary                  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # Run history table
    header = f"{'Run Time':<22} {'Duration':>8} {'Events':>7} {'Errors':>7} {'Dry?':>5}"
    print(header)
    print("─" * len(header))

    for e in entries:
        ts = e.get("timestamp", "?")
        try:
            dt = datetime.fromisoformat(ts).astimezone()
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            ts_str = ts[:19]

        dur = e.get("duration_seconds", 0)
        evts = e.get("total_events", 0)
        errs = e.get("total_errors", 0)
        dry = "yes" if e.get("dry_run") else "no"

        print(f"{ts_str:<22} {dur:>7.1f}s {evts:>7} {errs:>7} {dry:>5}")

    print()

    # Per-module breakdown from latest run
    latest = entries[-1]
    epm = latest.get("events_per_module", {})
    errpm = latest.get("errors_per_module", {})

    if epm or errpm:
        print("Latest run — per module:")
        mod_header = f"  {'Module':<20} {'Events':>7} {'Errors':>7}"
        print(mod_header)
        print("  " + "─" * (len(mod_header) - 2))
        for mod in sorted(set(list(epm) + list(errpm))):
            print(f"  {mod:<20} {epm.get(mod, 0):>7} {errpm.get(mod, 0):>7}")
        print()

    # System stats from latest entry
    db_size = latest.get("db_size_bytes", 0)
    disk_free = latest.get("disk_free_bytes", 0)
    print(f"DB size:    {_format_bytes(db_size)}")
    print(f"Disk free:  {_format_bytes(disk_free)}")

    # Warnings
    if disk_free < 1_000_000_000:
        print("\n⚠  WARNING: Less than 1 GB disk space remaining!")
    if latest.get("total_errors", 0) > 0:
        print(f"\n⚠  WARNING: Latest run had {latest['total_errors']} module error(s)")

    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LifeData V4 ETL Pipeline",
        epilog="See LIFEDATA_MASTER_PROMPT_V4.md for full documentation.",
    )
    parser.add_argument(
        "--config",
        default="~/LifeData/config.yaml",
        help="Path to config.yaml (default: ~/LifeData/config.yaml)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate daily report after ETL",
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        help="Run only a specific module (e.g., 'device')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse but don't write to DB",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print health summary from last 7 ETL runs (no ETL executed)",
    )
    args = parser.parse_args()

    if args.status:
        return _print_status()


    # Acquire exclusive lock — prevents overlapping cron runs
    lock_fd = _acquire_lock()

    try:
        orch = Orchestrator(args.config)
        summary = orch.run(
            report=args.report,
            single_module=args.module,
            dry_run=args.dry_run,
        )

        # Non-zero exit on module failures
        if summary.get("failed_modules"):
            return 1
        return 0

    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    finally:
        # Release lock — fd close releases the flock automatically
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            os.unlink(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
