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
    python run_etl.py --trace <raw_source_id>  # Trace a single event's provenance

Cron (nightly at 11:55 PM):
    55 23 * * * cd ~/LifeData && venv/bin/python run_etl.py --report
"""

import argparse
import fcntl
import os
import sys
from datetime import datetime

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.orchestrator import Orchestrator

# Lock file path — prevents concurrent ETL runs
LOCK_FILE = os.path.expanduser("~/LifeData/.etl.lock")


LOCK_TIMEOUT_SECONDS = 5


def _acquire_lock():
    """Acquire an exclusive flock on the ETL lock file.

    Retries for up to LOCK_TIMEOUT_SECONDS before giving up. This avoids
    false failures from momentary lock contention (e.g. overlapping cron
    triggers that start within the same second).

    Returns the open file descriptor (must stay open for the lock to hold).
    Raises SystemExit(1) if the lock cannot be acquired within the timeout.
    """
    import time

    lock_fd = open(LOCK_FILE, "w")
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS

    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break  # acquired
        except OSError:
            if time.monotonic() >= deadline:
                lock_fd.close()
                print(
                    "ETL already running (lockfile held). Exiting.",
                    file=sys.stderr,
                )
                sys.exit(1)
            time.sleep(0.25)

    # Write PID for debugging
    lock_fd.write(str(os.getpid()))
    lock_fd.flush()
    return lock_fd


from core.database import Database
from core.metrics import read_last_n_metrics


def _print_status() -> int:
    """Read last 7 metrics entries and print a health summary table with warnings."""
    entries = read_last_n_metrics(7)

    if not entries:
        print("No metrics found. Run the ETL at least once first.")
        return 0

    # Header
    print()
    print("╔══════════════════════════════════════════════════════════════════════════╗")
    print("║                      LifeData ETL — Health Summary                      ║")
    print("╚══════════════════════════════════════════════════════════════════════════╝")
    print()

    # Run history table — columns: date, duration, events ingested, failed modules, db size, disk free
    header = (
        f"{'Date':<22} {'Duration':>8} {'Ingested':>9} "
        f"{'Failed':>8} {'DB Size':>9} {'Disk Free':>10}"
    )
    print(header)
    print("─" * len(header))

    for e in entries:
        ts = e.started_utc or "?"
        try:
            dt = datetime.fromisoformat(ts).astimezone()
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            ts_str = ts[:19]

        failed = e.failed_modules()
        failed_str = ",".join(failed) if failed else "—"
        if len(failed_str) > 8:
            failed_str = f"{len(failed)}mod"

        db_str = f"{e.db_size_mb:.1f}MB" if e.db_size_mb < 1024 else f"{e.db_size_mb / 1024:.1f}GB"
        disk_str = f"{e.disk_free_gb:.1f}GB"

        print(
            f"{ts_str:<22} {e.duration_sec:>7.1f}s {e.total_events_ingested:>9} "
            f"{failed_str:>8} {db_str:>9} {disk_str:>10}"
        )

    print()

    # Per-module breakdown from latest run
    latest = entries[-1]
    if latest.modules:
        print("Latest run — per module:")
        mod_header = f"  {'Module':<16} {'Status':<9} {'Files':>5} {'Parsed':>7} {'Ingested':>9} {'Skip':>5} {'Time':>7}"
        print(mod_header)
        print("  " + "─" * (len(mod_header) - 2))
        for mid in sorted(latest.modules):
            mm = latest.modules[mid]
            print(
                f"  {mm.module_id:<16} {mm.status:<9} {mm.files_parsed:>5} "
                f"{mm.events_parsed:>7} {mm.events_ingested:>9} "
                f"{mm.events_skipped:>5} {mm.duration_sec:>6.2f}s"
            )
        print()

    # ── Warnings ─────────────────────────────────────────────
    warnings: list[str] = []

    # 1. Any module failed in the last 3 runs
    recent = entries[-3:] if len(entries) >= 3 else entries
    recent_failures: set[str] = set()
    for e in recent:
        recent_failures.update(e.failed_modules())
    if recent_failures:
        warnings.append(
            f"Module failure(s) in last {len(recent)} run(s): "
            f"{', '.join(sorted(recent_failures))}"
        )

    # 2. DB size > 5 GB
    if latest.db_size_mb > 5120:
        warnings.append(
            f"Database size is {latest.db_size_mb / 1024:.1f} GB (> 5 GB threshold)"
        )

    # 3. Disk free < 20 GB
    if latest.disk_free_gb < 20:
        warnings.append(
            f"Disk free space is {latest.disk_free_gb:.1f} GB (< 20 GB threshold)"
        )

    # 4. Events ingested dropped >50% compared to 7-day average
    if len(entries) >= 2:
        historical = entries[:-1]  # all except latest
        avg_events = sum(e.total_events_ingested for e in historical) / len(historical)
        if avg_events > 0:
            drop_pct = (avg_events - latest.total_events_ingested) / avg_events * 100
            if drop_pct > 50:
                warnings.append(
                    f"Events ingested dropped {drop_pct:.0f}% vs "
                    f"{len(historical)}-run average "
                    f"({latest.total_events_ingested} vs avg {avg_events:.0f})"
                )

    if warnings:
        for w in warnings:
            print(f"  !! {w}")
        print()

    return 0


def _print_trace(raw_source_id: str, config_path: str) -> int:
    """Trace a single event by raw_source_id.

    Prints: full event record, inferred raw file, parser version,
    related daily_summaries, and correlations.
    """
    from core.config import load_config

    try:
        config = load_config(config_path)
    except Exception as e:
        print(f"Could not load config: {e}", file=sys.stderr)
        return 2

    db = Database(config.lifedata.db_path)
    db.ensure_schema()

    # Look up by raw_source_id (exact match or prefix)
    row = db.conn.execute(
        "SELECT * FROM events WHERE raw_source_id = ?",
        (raw_source_id,),
    ).fetchone()
    if row is None:
        # Try prefix match
        row = db.conn.execute(
            "SELECT * FROM events WHERE raw_source_id LIKE ?",
            (raw_source_id + "%",),
        ).fetchone()
    if row is None:
        print(f"No event found with raw_source_id: {raw_source_id}")
        db.close()
        return 1

    event = dict(row)

    # ── Full event record ─────────────────────────────────────
    print()
    print("── Event Record ──────────────────────────────────────")
    for key in event:
        val = event[key]
        if val is not None:
            print(f"  {key:<20} {val}")
    print()

    # ── Inferred raw file ─────────────────────────────────────
    source_module = event["source_module"]
    timestamp_local = event["timestamp_local"]
    raw_base = os.path.expanduser(config.lifedata.raw_base)
    date_part = timestamp_local[:10] if timestamp_local else ""

    # Derive the top-level module name (e.g. "device" from "device.screen")
    top_module = source_module.split(".")[0] if source_module else ""

    print("── Inferred Source File ──────────────────────────────")
    found_files: list[str] = []
    if date_part and top_module:
        # Search raw_base recursively for files containing the date
        for dirpath, _, filenames in os.walk(raw_base):
            for fname in filenames:
                # Match files that belong to this module's date
                date_compact = date_part.replace("-", "")  # 20260322
                date_dashed = date_part  # 2026-03-22
                # Also try M-DD-YY format used by Tasker
                parts = date_part.split("-")
                if len(parts) == 3:
                    date_tasker = f"{int(parts[1])}-{int(parts[2])}-{parts[0][2:]}"
                else:
                    date_tasker = ""
                if any(d in fname for d in [date_compact, date_dashed, date_tasker] if d):
                    found_files.append(os.path.join(dirpath, fname))

    if found_files:
        for f in found_files[:5]:
            print(f"  {f}")
        if len(found_files) > 5:
            print(f"  ... and {len(found_files) - 5} more")
    else:
        print("  (could not infer — no matching files found in raw/)")
    print()

    # ── Parser version ────────────────────────────────────────
    print("── Parser ───────────────────────────────────────────")
    print(f"  parser_version:    {event.get('parser_version', '?')}")
    print(f"  source_module:     {source_module}")
    print()

    # ── Daily summaries for this date + source_module ─────────
    print("── Related Daily Summaries ──────────────────────────")
    summaries = db.conn.execute(
        "SELECT * FROM daily_summaries WHERE date_local = ? AND source_module LIKE ?",
        (date_part, top_module + ".%"),
    ).fetchall()
    if summaries:
        for s in summaries:
            sd = dict(s)
            print(
                f"  {sd['date_local']}  {sd['source_module']:<24} "
                f"{sd['metric_name']:<28} = {sd.get('value_numeric', sd.get('value_json', ''))}"
            )
    else:
        print("  (none)")
    print()

    # ── Correlations referencing this source_module ────────────
    print("── Related Correlations ─────────────────────────────")
    correlations = db.conn.execute(
        "SELECT * FROM correlations WHERE metric_a LIKE ? OR metric_b LIKE ?",
        (source_module + "%", source_module + "%"),
    ).fetchall()
    if correlations:
        for c in correlations:
            cd = dict(c)
            print(
                f"  {cd['metric_a']} <-> {cd['metric_b']}  "
                f"r={cd.get('pearson_r', '?')}  "
                f"rho={cd.get('spearman_rho', '?')}  "
                f"n={cd.get('n_observations', '?')}"
            )
    else:
        print("  (none)")
    print()

    db.close()
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
    parser.add_argument(
        "--trace",
        type=str,
        default=None,
        metavar="RAW_SOURCE_ID",
        help="Trace an event by raw_source_id: show full record, source file, downstream data",
    )
    parser.add_argument(
        "--weekly-report",
        action="store_true",
        help="Generate weekly report after ETL",
    )
    parser.add_argument(
        "--monthly-report",
        action="store_true",
        help="Generate monthly report after ETL",
    )
    args = parser.parse_args()

    if args.status:
        return _print_status()

    if args.trace:
        return _print_trace(args.trace, args.config)


    # Acquire exclusive lock — prevents overlapping cron runs
    lock_fd = _acquire_lock()

    try:
        orch = Orchestrator(args.config)
        summary = orch.run(
            report=args.report,
            single_module=args.module,
            dry_run=args.dry_run,
        )

        # Weekly / monthly report generation (after ETL, like --report)
        if not args.dry_run:
            config_dump = orch.config.model_dump()
            if args.weekly_report:
                try:
                    from analysis.reports import generate_weekly_report

                    generate_weekly_report(orch.db, orch.modules, config_dump)
                    print("Weekly report generated")
                except Exception as e:
                    print(f"Weekly report generation failed: {e}", file=sys.stderr)

            if args.monthly_report:
                try:
                    from analysis.reports import generate_monthly_report

                    generate_monthly_report(orch.db, orch.modules, config_dump)
                    print("Monthly report generated")
                except Exception as e:
                    print(f"Monthly report generation failed: {e}", file=sys.stderr)

        # Non-zero exit on module failures
        if summary.get("failed_modules"):
            return 1
        return 0

    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2

    finally:
        # Release lock — closing the fd releases the flock automatically.
        # We intentionally do NOT unlink the lock file: flock operates on
        # the file descriptor, not the path, so unlinking is unnecessary
        # and could cause race conditions with concurrent processes.
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    sys.exit(main())
