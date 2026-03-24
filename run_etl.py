#!/usr/bin/env python3
"""
LifeData V4 — ETL Entry Point

Usage:
    python run_etl.py                       # Run full ETL
    python run_etl.py --report              # Run ETL + generate daily report
    python run_etl.py --module device       # Run only the device module
    python run_etl.py --dry-run             # Parse but don't write to DB
    python run_etl.py --dry-run --module device  # Parse device only, no writes

Cron (nightly at 11:55 PM):
    55 23 * * * cd ~/LifeData && venv/bin/python run_etl.py --report
"""

import argparse
import os
import sys

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.orchestrator import Orchestrator


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
    args = parser.parse_args()

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


if __name__ == "__main__":
    sys.exit(main())
