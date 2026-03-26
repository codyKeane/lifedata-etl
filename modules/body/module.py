"""
LifeData V4 — Body Module
modules/body/module.py

Captures physiological and biometric data: health metrics from Samsung
Health exports, manual Quick_Log entries (caffeine, weight, water, exercise,
pain, vape, supplements), sleep tracking triggers, and reaction time tests.

File discovery pattern:
  logs/manual/quicklog_*.csv → body.caffeine, body.meal, body.vape, etc.
  spool/health/steps_*.csv   → body.steps
  spool/health/hr_*.csv      → body.heart_rate
  spool/health/health_*.csv  → auto-detect health type
  logs/sleep/sleep_*.csv     → body.sleep (start/end triggers)
  spool/health/reaction_*.csv → body.cognition (reaction time)

Derived metrics (computed in post_ingest):
  body.derived/daily_step_total   → sum of step_count events per day
  body.derived/caffeine_level     → pharmacokinetic model (5hr half-life)
  body.derived/sleep_duration     → paired sleep_start/sleep_end duration
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_float, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.body")


class BodyModule(ModuleInterface):
    """Body module — captures physiological and biometric data."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._parser_registry: dict[str, Any] | None = None

    def _get_parsers(self) -> dict[str, Any]:
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.body.parsers import PARSER_REGISTRY

            self._parser_registry = PARSER_REGISTRY
        assert self._parser_registry is not None
        return self._parser_registry

    @property
    def module_id(self) -> str:
        return "body"

    @property
    def display_name(self) -> str:
        return "Body Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "body.steps",
            "body.heart_rate",
            "body.hrv",
            "body.spo2",
            "body.sleep",
            "body.caffeine",
            "body.meal",
            "body.vape",
            "body.exercise",
            "body.pain",
            "body.weight",
            "body.water",
            "body.blood_pressure",
            "body.supplement",
            "body.cognition",
            "body.movement",
            "body.activity",
            "body.derived",
        ]

    def get_metrics_manifest(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "name": "body.steps",
                    "display_name": "Steps",
                    "unit": "count",
                    "aggregate": "SUM",
                    "event_type": None,
                    "trend_eligible": True,
                    "anomaly_eligible": True,
                },
                {
                    "name": "body.caffeine",
                    "display_name": "Caffeine Intake",
                    "unit": "mg",
                    "aggregate": "SUM",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": True,
                },
                {
                    "name": "body.derived:daily_step_total",
                    "display_name": "Daily Step Total",
                    "unit": "steps",
                    "aggregate": "SUM",
                    "event_type": "daily_step_total",
                    "trend_eligible": True,
                    "anomaly_eligible": False,
                },
                {
                    "name": "body.derived:sleep_duration",
                    "display_name": "Sleep Duration",
                    "unit": "hours",
                    "aggregate": "AVG",
                    "event_type": "sleep_duration",
                    "trend_eligible": True,
                    "anomaly_eligible": True,
                },
                {
                    "name": "body.derived:caffeine_level",
                    "display_name": "Caffeine Level",
                    "unit": "mg",
                    "aggregate": "AVG",
                    "event_type": "caffeine_level",
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
            ],
        }

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all body-related CSV files in the raw data tree."""
        files = []
        expanded = os.path.expanduser(raw_base)

        sensor_dir = self._config.get("sensor_logger_dir", "logs/sensors")

        search_dirs = [
            os.path.join(expanded, "body"),
            os.path.join(expanded, "logs", "body"),
            os.path.join(expanded, "logs", "manual"),
            os.path.join(expanded, "logs", "sleep"),
            os.path.join(expanded, "spool", "health"),
            os.path.join(expanded, "spool", "health", "samsung"),
            os.path.join(expanded, sensor_dir),  # Sensor Logger summaries
        ]

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for csv_file in glob_files(search_dir, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                if any(basename.startswith(prefix) for prefix in self._get_parsers()):
                    files.append(csv_file)

        # Deduplicate
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single body CSV file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in self._get_parsers().items():
            if basename.startswith(prefix):
                events: list[Event] = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for body file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Compute derived body metrics after all events are ingested.

        Derived metrics:
          - body.derived/daily_step_total: sum of steps for today
          - body.derived/caffeine_level: estimated blood caffeine (mg) at current hour
          - body.derived/sleep_duration: computed from start/end pairs
        """
        # Determine which dates to process
        if affected_dates:
            days_to_process = sorted(affected_dates)
        else:
            days_to_process = [datetime.now(UTC).strftime("%Y-%m-%d")]

        all_derived: list[Event] = []
        for today in days_to_process:
            all_derived.extend(self._compute_day_metrics(db, today))

        if all_derived:
            inserted, skipped = db.insert_events_for_module("body", all_derived)
            log.info(f"Body derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db: Database, today: str) -> list[Event]:
        """Compute all derived body metrics for a single day."""
        derived_events: list[Event] = []
        # Deterministic timestamp for derived daily metrics (idempotent hashing)
        day_ts = f"{today}T23:59:00+00:00"

        # --- Daily step total ---
        if self.is_metric_enabled("body.derived:daily_step_total"):
            rows = db.execute(
                """
                SELECT SUM(value_numeric) as total_steps, COUNT(*) as readings
                FROM events
                WHERE source_module = 'body.steps'
                  AND date(timestamp_utc) = ?
                  AND value_numeric IS NOT NULL
                """,
                (today,),
            )
            row: Any = (
                rows.fetchone()
                if hasattr(rows, "fetchone")
                else (list(rows)[0] if rows else None)
            )
            if row and row[0] is not None and row[0] > 0:
                step_total = int(row[0])
                step_goal = self._config.get("step_goal", 8000)
                derived_events.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="body.derived",
                        event_type="daily_step_total",
                        value_numeric=float(step_total),
                        value_json=safe_json(
                            {
                                "readings": row[1],
                                "goal": step_goal,
                                "goal_pct": round(step_total / step_goal * 100, 1),
                            }
                        ),
                        confidence=0.95,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"Daily steps: {step_total} ({round(step_total / step_goal * 100, 1)}% of goal)"
                )

        # --- Caffeine pharmacokinetic model ---
        if self.is_metric_enabled("body.derived:caffeine_level"):
            half_life = self._config.get("caffeine_half_life_hours", 5.0)
            rows = db.execute(
                """
                SELECT timestamp_utc, value_numeric
                FROM events
                WHERE source_module = 'body.caffeine'
                  AND event_type = 'intake'
                  AND value_numeric IS NOT NULL
                  AND date(timestamp_utc) = ?
                ORDER BY timestamp_utc
                """,
                (today,),
            )
            caffeine_events = []
            result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
            for r in result_set:
                ts = r[0]
                mg = safe_float(r[1])
                if mg and mg > 0:
                    caffeine_events.append((ts, mg))

            if caffeine_events:
                # Use end-of-day as reference for decay calculation (deterministic)
                ref_dt = datetime.fromisoformat(day_ts)
                total_remaining = 0.0
                for ts, mg in caffeine_events:
                    try:
                        intake_dt = datetime.fromisoformat(ts)
                        if intake_dt.tzinfo is None:
                            intake_dt = intake_dt.replace(tzinfo=UTC)
                        hours_elapsed = (ref_dt - intake_dt).total_seconds() / 3600
                        if hours_elapsed < 0:
                            continue
                        remaining = mg * (0.5 ** (hours_elapsed / half_life))
                        total_remaining += remaining
                    except (ValueError, TypeError):
                        continue

                total_remaining = round(total_remaining, 1)
                derived_events.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="body.derived",
                        event_type="caffeine_level",
                        value_numeric=total_remaining,
                        value_json=safe_json(
                            {
                                "intakes_today": len(caffeine_events),
                                "total_ingested_mg": sum(mg for _, mg in caffeine_events),
                                "half_life_hours": half_life,
                            }
                        ),
                        confidence=0.85,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"Caffeine level: {total_remaining}mg remaining "
                    f"({len(caffeine_events)} intakes today)"
                )

        # --- Sleep duration from start/end pairs ---
        if self.is_metric_enabled("body.derived:sleep_duration"):
            rows = db.execute(
                """
                SELECT event_type, timestamp_utc
                FROM events
                WHERE source_module = 'body.sleep'
                  AND event_type IN ('sleep_start', 'sleep_end')
                  AND date(timestamp_utc) >= date(?, '-1 day')
                  AND date(timestamp_utc) <= ?
                ORDER BY timestamp_utc
                """,
                (today, today),
            )
            sleep_events = []
            result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
            for r in result_set:
                sleep_events.append((r[0], r[1]))

            # Pair the last sleep_start with the first sleep_end after it
            last_start = None
            for event_type, ts in sleep_events:
                if event_type == "sleep_start":
                    last_start = ts
                elif event_type == "sleep_end" and last_start:
                    try:
                        start_dt = datetime.fromisoformat(last_start)
                        end_dt = datetime.fromisoformat(ts)
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=UTC)
                        if end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=UTC)
                        duration_min = (end_dt - start_dt).total_seconds() / 60
                        duration_hours = round(duration_min / 60, 2)

                        if 0 < duration_hours < 24:  # sanity check
                            sleep_target = self._config.get("sleep_target_hours", 7.5)
                            derived_events.append(
                                Event(
                                    timestamp_utc=day_ts,
                                    timestamp_local=day_ts,
                                    timezone_offset="-0500",
                                    source_module="body.derived",
                                    event_type="sleep_duration",
                                    value_numeric=duration_hours,
                                    value_json=safe_json(
                                        {
                                            "duration_min": round(duration_min, 0),
                                            "target_hours": sleep_target,
                                            "delta_hours": round(
                                                duration_hours - sleep_target, 2
                                            ),
                                        }
                                    ),
                                    confidence=0.9,
                                    parser_version=self.version,
                                )
                            )
                            log.info(
                                f"Sleep duration: {duration_hours}h "
                                f"(target: {sleep_target}h, "
                                f"delta: {round(duration_hours - sleep_target, 2):+}h)"
                            )
                    except (ValueError, TypeError):
                        pass
                    last_start = None  # Reset for next pair

        return derived_events

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily body metrics for report generation."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt,
                   AVG(value_numeric) as avg_val,
                   SUM(value_numeric) as sum_val,
                   MIN(value_numeric) as min_val,
                   MAX(value_numeric) as max_val
            FROM events
            WHERE source_module LIKE 'body.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        for row in result_set:
            src, evt, cnt, avg_val, sum_val, min_val, max_val = row
            key = f"{src}.{evt}"
            summary[key] = {
                "count": cnt,
                "avg": round(avg_val, 2) if avg_val is not None else None,
                "sum": round(sum_val, 2) if sum_val is not None else None,
                "min": round(min_val, 2) if min_val is not None else None,
                "max": round(max_val, 2) if max_val is not None else None,
            }

        if not summary:
            return None

        return {
            "event_counts": summary,
            "total_body_events": sum(v["count"] for v in summary.values()),
            "section_title": "Body",
            "bullets": [],
        }


def create_module(config: dict[str, Any] | None = None) -> BodyModule:
    """Factory function called by the orchestrator."""
    return BodyModule(config)
