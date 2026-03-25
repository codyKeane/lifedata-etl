"""
LifeData V4 — Cognition Module (NU)
modules/cognition/module.py

Captures objective cognitive performance biomarkers: reaction time, working
memory capacity, time perception accuracy, and psychomotor speed (typing).

File discovery pattern:
  spool/cognition/simple_rt_*.csv    → cognition.reaction / simple_rt
  spool/cognition/choice_rt_*.csv    → cognition.reaction / choice_rt
  spool/cognition/gonogo_*.csv       → cognition.reaction / go_nogo
  spool/cognition/digit_span_*.csv   → cognition.memory / digit_span
  spool/cognition/time_prod_*.csv    → cognition.time / production
  spool/cognition/time_est_*.csv     → cognition.time / estimation
  spool/cognition/typing_*.csv       → cognition.typing / speed_test

Derived metrics (computed in post_ingest):
  cognition.reaction.derived / daily_baseline
  cognition.derived / cognitive_load_index
  cognition.derived / impairment_flag
  cognition.derived / peak_cognition_hour
  cognition.derived / subjective_objective_gap
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.cognition")


class CognitionModule(ModuleInterface):
    """Cognition module — objective cognitive performance probes."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._parser_registry: dict[str, Any] | None = None

    def _get_parsers(self) -> dict[str, Any]:
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.cognition.parsers import PARSER_REGISTRY

            self._parser_registry = PARSER_REGISTRY
        return self._parser_registry

    @property
    def module_id(self) -> str:
        return "cognition"

    @property
    def display_name(self) -> str:
        return "Cognition Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "cognition.reaction",
            "cognition.reaction.derived",
            "cognition.memory",
            "cognition.memory.derived",
            "cognition.time",
            "cognition.time.derived",
            "cognition.typing",
            "cognition.typing.derived",
            "cognition.derived",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all cognition CSV files in the spool/cognition directory."""
        files = []
        expanded = os.path.expanduser(raw_base)

        search_dirs = [
            os.path.join(expanded, "spool", "cognition"),
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
        """Parse a single cognition CSV file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in self._get_parsers().items():
            if basename.startswith(prefix):
                events: list[Event] = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for cognition file: {basename}")
        return []

    def post_ingest(self, db: Database) -> None:
        """Compute derived cognition metrics after all events are ingested.

        Derived metrics:
          - cognition.reaction.derived/daily_baseline: median simple RT per day
          - cognition.derived/cognitive_load_index: weighted composite z-score
          - cognition.derived/impairment_flag: >2σ below 14-day baseline
          - cognition.derived/peak_cognition_hour: best performance hour (14-day)
          - cognition.derived/subjective_objective_gap: self-report vs probes
        """
        derived_events = []
        baseline_days = self._config.get("baseline_window_days", 14)
        impairment_threshold = self._config.get("impairment_zscore_threshold", 2.0)

        # Get all dates with cognition data
        rows = db.execute(
            """
            SELECT DISTINCT date(timestamp_utc) as d
            FROM events
            WHERE source_module LIKE 'cognition.%'
              AND source_module NOT LIKE '%.derived'
            ORDER BY d
            """
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        dates = [r[0] for r in result_set if r[0]]

        for date_str in dates:
            # --- Daily RT baseline ---
            rt_events = self._get_daily_rt_baseline(db, date_str, baseline_days)
            if rt_events:
                derived_events.extend(rt_events)

            # --- Cognitive load index ---
            cli_event = self._compute_cognitive_load_index(db, date_str, baseline_days)
            if cli_event:
                derived_events.append(cli_event)

                # --- Impairment flag (depends on CLI) ---
                imp_event = self._compute_impairment_flag(
                    db,
                    date_str,
                    cli_event.value_numeric if cli_event.value_numeric is not None else 0.0,
                    baseline_days,
                    impairment_threshold,
                )
                if imp_event:
                    derived_events.append(imp_event)

            # --- Subjective-objective gap ---
            gap_event = self._compute_subjective_objective_gap(db, date_str)
            if gap_event:
                derived_events.append(gap_event)

        # --- Peak cognition hour (rolling 14-day, computed once) ---
        peak_event = self._compute_peak_cognition_hour(db, baseline_days)
        if peak_event:
            derived_events.append(peak_event)

        # Insert derived events
        if derived_events:
            inserted, skipped = db.insert_events_for_module("cognition", derived_events)
            log.info(
                f"Cognition derived metrics: {inserted} inserted, {skipped} skipped"
            )

    def _get_daily_rt_baseline(
        self, db: Database, date_str: str, baseline_days: int
    ) -> list[Event]:
        """Compute daily RT baseline: median simple_rt for the day."""
        events: list[Event] = []

        rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = 'cognition.reaction'
              AND event_type = 'simple_rt'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            ORDER BY value_numeric
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        rts = [r[0] for r in result_set if r[0] is not None]

        if not rts:
            return events

        n = len(rts)
        median_rt = rts[n // 2] if n % 2 == 1 else (rts[n // 2 - 1] + rts[n // 2]) / 2
        mean_rt = sum(rts) / n
        std_rt = math.sqrt(sum((x - mean_rt) ** 2 for x in rts) / n) if n > 1 else 0.0

        # Get 7-day trend
        trend_rows = db.execute(
            """
            SELECT date(timestamp_utc) as d, AVG(value_numeric) as avg_rt
            FROM events
            WHERE source_module = 'cognition.reaction'
              AND event_type = 'simple_rt'
              AND date(timestamp_utc) BETWEEN date(?, '-7 days') AND ?
              AND value_numeric IS NOT NULL
            GROUP BY d
            ORDER BY d
            """,
            (date_str, date_str),
        )
        trend_set = (
            trend_rows.fetchall() if hasattr(trend_rows, "fetchall") else trend_rows
        )
        trend_7d = [round(r[1], 1) for r in trend_set if r[1] is not None]

        ts_utc = f"{date_str}T23:59:00+00:00"
        events.append(
            Event(
                timestamp_utc=ts_utc,
                timestamp_local=ts_utc,
                timezone_offset="-0500",
                source_module="cognition.reaction.derived",
                event_type="daily_baseline",
                value_numeric=round(median_rt, 1),
                value_json=safe_json(
                    {
                        "mean": round(mean_rt, 1),
                        "std": round(std_rt, 1),
                        "n_trials": n,
                        "trend_7d": trend_7d,
                    }
                ),
                tags="reaction_time,baseline,derived",
                confidence=0.8,
                parser_version=self.version,
            )
        )

        return events

    def _compute_cognitive_load_index(self, db: Database, date_str: str, baseline_days: int) -> Optional[Event]:
        """Weighted composite z-score across all available cognitive probes."""
        components = {}

        # Simple RT (higher = worse → positive z = impairment)
        rt_z = self._zscore_metric(
            db,
            date_str,
            baseline_days,
            "cognition.reaction",
            "simple_rt",
            invert=False,  # higher RT = worse
        )
        if rt_z is not None:
            components["rt"] = rt_z

        # Digit span (higher = better → invert)
        ds_z = self._zscore_metric(
            db,
            date_str,
            baseline_days,
            "cognition.memory",
            "digit_span",
            invert=True,
        )
        if ds_z is not None:
            components["memory"] = ds_z

        # Time production absolute error (higher = worse)
        tp_z = self._zscore_time_error(db, date_str, baseline_days)
        if tp_z is not None:
            components["time"] = tp_z

        # Typing WPM (higher = better → invert)
        tw_z = self._zscore_metric(
            db,
            date_str,
            baseline_days,
            "cognition.typing",
            "speed_test",
            invert=True,
        )
        if tw_z is not None:
            components["typing"] = tw_z

        if len(components) < 1:
            return None

        weights = {"rt": 0.3, "memory": 0.3, "time": 0.2, "typing": 0.2}
        total_weight = sum(weights.get(k, 0.2) for k in components)
        cli = (
            sum(components[k] * weights.get(k, 0.2) for k in components) / total_weight
        )

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="cognition.derived",
            event_type="cognitive_load_index",
            value_numeric=round(cli, 3),
            value_json=safe_json(
                {
                    "components": {k: round(v, 3) for k, v in components.items()},
                    "weights": {k: weights.get(k, 0.2) for k in components},
                    "n_components": len(components),
                }
            ),
            tags="cognitive_load,composite,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_impairment_flag(
        self, db: Database, date_str: str, cli_value: float, baseline_days: int, threshold: float
    ) -> Optional[Event]:
        """Binary flag: CLI > threshold σ above baseline (= impaired)."""
        rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = 'cognition.derived'
              AND event_type = 'cognitive_load_index'
              AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
              AND value_numeric IS NOT NULL
            """,
            (date_str, str(-baseline_days), date_str),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        history = [r[0] for r in result_set if r[0] is not None]

        if len(history) < 3:
            return None

        mean_cli = sum(history) / len(history)
        std_cli = math.sqrt(sum((x - mean_cli) ** 2 for x in history) / len(history))
        if std_cli < 0.01:
            return None

        z = (cli_value - mean_cli) / std_cli
        impaired = 1 if z > threshold else 0

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="cognition.derived",
            event_type="impairment_flag",
            value_numeric=float(impaired),
            value_json=safe_json(
                {
                    "cli_zscore": round(z, 3),
                    "threshold": threshold,
                    "baseline_days": len(history),
                    "baseline_mean": round(mean_cli, 3),
                    "baseline_std": round(std_cli, 3),
                }
            ),
            tags="impairment,flag,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_peak_cognition_hour(self, db: Database, baseline_days: int) -> Optional[Event]:
        """Hour of day with best average probe scores (rolling window)."""
        rows = db.execute(
            """
            SELECT CAST(strftime('%H', timestamp_utc) AS INTEGER) as hour,
                   AVG(value_numeric) as avg_rt
            FROM events
            WHERE source_module = 'cognition.reaction'
              AND event_type = 'simple_rt'
              AND date(timestamp_utc) >= date('now', ? || ' days')
              AND value_numeric IS NOT NULL
            GROUP BY hour
            HAVING COUNT(*) >= 3
            ORDER BY avg_rt ASC
            LIMIT 1
            """,
            (str(-baseline_days),),
        )
        result_set: list[Any] = rows.fetchall() if hasattr(rows, "fetchall") else list(rows)
        if not result_set:
            return None

        best_hour = result_set[0][0]
        best_avg_rt = result_set[0][1]

        now_utc = datetime.now(timezone.utc).isoformat()
        return Event(
            timestamp_utc=now_utc,
            timestamp_local=now_utc,
            timezone_offset="-0500",
            source_module="cognition.derived",
            event_type="peak_cognition_hour",
            value_numeric=float(best_hour),
            value_json=safe_json(
                {
                    "best_avg_rt_ms": round(best_avg_rt, 1),
                    "window_days": baseline_days,
                }
            ),
            tags="peak_hour,circadian,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_subjective_objective_gap(self, db: Database, date_str: str) -> Optional[Event]:
        """Difference between self-reported energy/focus and probe performance."""
        # Get subjective scores from mind module
        subj_rows = db.execute(
            """
            SELECT event_type, AVG(value_numeric) as avg_val
            FROM events
            WHERE source_module IN ('mind.assessment', 'mind.energy', 'mind.mood')
              AND event_type IN ('energy', 'focus', 'morning_energy', 'evening_energy')
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            GROUP BY event_type
            """,
            (date_str,),
        )
        subj_set = subj_rows.fetchall() if hasattr(subj_rows, "fetchall") else subj_rows
        subj_scores = {r[0]: r[1] for r in subj_set if r[1] is not None}

        if not subj_scores:
            return None

        # Average subjective score (1-10 scale)
        subj_mean = sum(subj_scores.values()) / len(subj_scores)
        # Normalize to approximate z-score space
        subj_z = (subj_mean - 5.5) / 2.0

        # Get objective: average simple RT z-score for the day
        rt_rows = db.execute(
            """
            SELECT AVG(value_numeric) as avg_rt
            FROM events
            WHERE source_module = 'cognition.reaction'
              AND event_type = 'simple_rt'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (date_str,),
        )
        rt_set: list[Any] = rt_rows.fetchall() if hasattr(rt_rows, "fetchall") else list(rt_rows)
        if not rt_set or rt_set[0][0] is None:
            return None

        today_rt = rt_set[0][0]

        # Get baseline RT
        baseline_rows = db.execute(
            """
            SELECT AVG(value_numeric) as mean_rt,
                   COUNT(*) as n
            FROM events
            WHERE source_module = 'cognition.reaction'
              AND event_type = 'simple_rt'
              AND date(timestamp_utc) BETWEEN date(?, '-14 days') AND date(?, '-1 day')
              AND value_numeric IS NOT NULL
            """,
            (date_str, date_str),
        )
        bl_set: list[Any] = (
            baseline_rows.fetchall()
            if hasattr(baseline_rows, "fetchall")
            else list(baseline_rows)
        )
        if not bl_set or bl_set[0][0] is None or bl_set[0][1] < 3:
            # Not enough baseline — use raw RT as a crude signal
            # Lower RT = better → invert so positive = good
            obj_z = -(today_rt - 300) / 100  # rough normalization around 300ms
        else:
            baseline_mean = bl_set[0][0]
            # Compute std
            std_rows = db.execute(
                """
                SELECT value_numeric FROM events
                WHERE source_module = 'cognition.reaction'
                  AND event_type = 'simple_rt'
                  AND date(timestamp_utc) BETWEEN date(?, '-14 days') AND date(?, '-1 day')
                  AND value_numeric IS NOT NULL
                """,
                (date_str, date_str),
            )
            std_set = std_rows.fetchall() if hasattr(std_rows, "fetchall") else std_rows
            vals = [r[0] for r in std_set]
            std_rt = (
                math.sqrt(sum((x - baseline_mean) ** 2 for x in vals) / len(vals))
                if vals
                else 50
            )
            std_rt = max(std_rt, 1)
            obj_z = -(today_rt - baseline_mean) / std_rt  # invert: lower RT = positive

        gap = round(subj_z - obj_z, 3)

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="cognition.derived",
            event_type="subjective_objective_gap",
            value_numeric=gap,
            value_json=safe_json(
                {
                    "subjective_mean": round(subj_mean, 2),
                    "subjective_z": round(subj_z, 3),
                    "objective_z": round(obj_z, 3),
                    "subjective_components": subj_scores,
                }
            ),
            tags="gap,subjective_objective,derived",
            confidence=0.7,
            parser_version=self.version,
        )

    def _zscore_metric(
        self,
        db: Database,
        date_str: str,
        baseline_days: int,
        source_module: str,
        event_type: str,
        invert: bool = False,
    ) -> Optional[float]:
        """Compute z-score for a metric on a given day vs rolling baseline."""
        # Today's value
        rows = db.execute(
            """
            SELECT AVG(value_numeric)
            FROM events
            WHERE source_module = ? AND event_type = ?
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (source_module, event_type, date_str),
        )
        result: Any = (
            rows.fetchone()
            if hasattr(rows, "fetchone")
            else (list(rows)[0] if rows else None)
        )
        if not result or result[0] is None:
            return None
        today_val = result[0]

        # Baseline
        bl_rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = ? AND event_type = ?
              AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
              AND value_numeric IS NOT NULL
            """,
            (source_module, event_type, date_str, str(-baseline_days), date_str),
        )
        bl_set = bl_rows.fetchall() if hasattr(bl_rows, "fetchall") else bl_rows
        vals = [r[0] for r in bl_set if r[0] is not None]

        if len(vals) < 3:
            return None

        mean_val = sum(vals) / len(vals)
        std_val = math.sqrt(sum((x - mean_val) ** 2 for x in vals) / len(vals))
        if std_val < 0.01:
            return None

        z: float = (today_val - mean_val) / std_val
        return -z if invert else z

    def _zscore_time_error(self, db: Database, date_str: str, baseline_days: int) -> Optional[float]:
        """Z-score for absolute time production error."""
        rows = db.execute(
            """
            SELECT value_json
            FROM events
            WHERE source_module = 'cognition.time'
              AND event_type = 'production'
              AND date(timestamp_utc) = ?
              AND value_json IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        errors = []
        for r in result_set:
            try:
                data = json.loads(r[0])
                err = abs(data.get("error_pct", 0))
                errors.append(err)
            except (json.JSONDecodeError, TypeError):
                continue

        if not errors:
            return None

        today_err = sum(errors) / len(errors)

        # Baseline
        bl_rows = db.execute(
            """
            SELECT value_json
            FROM events
            WHERE source_module = 'cognition.time'
              AND event_type = 'production'
              AND date(timestamp_utc) BETWEEN date(?, ? || ' days') AND date(?, '-1 day')
              AND value_json IS NOT NULL
            """,
            (date_str, str(-baseline_days), date_str),
        )
        bl_set = bl_rows.fetchall() if hasattr(bl_rows, "fetchall") else bl_rows
        bl_errors = []
        for r in bl_set:
            try:
                data = json.loads(r[0])
                bl_errors.append(abs(data.get("error_pct", 0)))
            except (json.JSONDecodeError, TypeError):
                continue

        if len(bl_errors) < 3:
            return None

        mean_err = sum(bl_errors) / len(bl_errors)
        std_err = math.sqrt(
            sum((x - mean_err) ** 2 for x in bl_errors) / len(bl_errors)
        )
        if std_err < 0.01:
            return None

        return float((today_err - mean_err) / std_err)

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily cognition metrics for report generation."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt,
                   AVG(value_numeric) as avg_val,
                   MIN(value_numeric) as min_val,
                   MAX(value_numeric) as max_val
            FROM events
            WHERE source_module LIKE 'cognition.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        for row in result_set:
            src, evt, cnt, avg_val, min_val, max_val = row
            key = f"{src}.{evt}"
            summary[key] = {
                "count": cnt,
                "avg": round(avg_val, 2) if avg_val is not None else None,
                "min": round(min_val, 2) if min_val is not None else None,
                "max": round(max_val, 2) if max_val is not None else None,
            }

        if not summary:
            return None

        return {
            "event_counts": summary,
            "total_cognition_events": sum(v["count"] for v in summary.values()),
        }


def create_module(config: dict[str, Any] | None = None) -> CognitionModule:
    """Factory function called by the orchestrator."""
    return CognitionModule(config)
