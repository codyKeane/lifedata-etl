"""
LifeData V4 — Mind Module
modules/mind/module.py

Captures subjective states from morning/evening check-in CSVs:
  - Morning: sleep quality, dream recall, mood, energy
  - Evening: day rating, stress, productivity, social satisfaction

Supports both standard (auto-triggered) and manual entry variants.
Implements the ModuleInterface contract.
"""

import os
import statistics

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json
from modules.mind.parsers import PARSER_REGISTRY

log = get_logger("lifedata.mind")


class MindModule(ModuleInterface):
    """Mind module — parses subjective check-in data from Tasker."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "mind"

    @property
    def display_name(self) -> str:
        return "Mind Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "mind.morning",
            "mind.evening",
            "mind.mood",
            "mind.energy",
            "mind.stress",
            "mind.sleep",
            "mind.productivity",
            "mind.social_satisfaction",
            "mind.derived",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all morning/evening check-in CSV files in the raw data tree.

        Searches for files matching known parser prefixes within:
          - raw_base/manual/
          - raw_base/logs/manual/
        """
        files = []

        search_dirs = [
            os.path.join(raw_base, "manual"),
            os.path.join(raw_base, "logs", "manual"),
        ]

        for search_dir in search_dirs:
            expanded = os.path.expanduser(search_dir)
            if not os.path.isdir(expanded):
                continue
            for csv_file in glob_files(expanded, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                # Only include files matching a known parser prefix
                if any(basename.startswith(prefix) for prefix in PARSER_REGISTRY):
                    files.append(csv_file)

        # Deduplicate (same file found via different search paths)
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single check-in CSV file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for mind file: {basename}")
        return []

    def post_ingest(self, db) -> None:
        """Compute derived mind metrics after ingestion.

        Processes all dates with mind events. Derived metrics per day:
          - mind.derived/subjective_day_score: weighted composite of ratings
          - mind.derived/mood_trend_7d: 7-day rolling average of mood
          - mind.derived/energy_stability: coefficient of variation over 7 days
        """
        date_rows = db.execute(
            """
            SELECT DISTINCT date(timestamp_local) as d FROM events
            WHERE source_module LIKE 'mind.%'
              AND source_module != 'mind.derived'
            ORDER BY d
            """
        ).fetchall()

        all_derived: list[Event] = []
        for (day,) in date_rows:
            all_derived.extend(self._compute_day_metrics(db, day))

        if all_derived:
            inserted, skipped = db.insert_events_for_module("mind", all_derived)
            log.info(f"Mind derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db, day: str) -> list[Event]:
        """Compute derived mind metrics for a single day."""
        derived: list[Event] = []
        day_ts = f"{day}T12:00:00-05:00"

        # --- Subjective day score ---
        # Weighted composite of available ratings for the day.
        # Weights: mood=0.3, energy=0.2, productivity=0.2,
        #          sleep_quality=0.15, stress=0.15 (inverted: 10-stress)
        score_components: dict[str, tuple[float, float]] = {}  # name -> (value, weight)

        # Gather individual check_in scores
        checkin_rows = db.execute(
            """
            SELECT source_module, AVG(value_numeric) as avg_val
            FROM events
            WHERE source_module IN (
                'mind.mood', 'mind.energy', 'mind.stress',
                'mind.productivity', 'mind.sleep',
                'mind.social_satisfaction'
            )
              AND event_type = 'check_in'
              AND date(timestamp_local) = ?
              AND value_numeric IS NOT NULL
            GROUP BY source_module
            """,
            [day],
        ).fetchall()

        weights = {
            "mind.mood": 0.3,
            "mind.energy": 0.2,
            "mind.productivity": 0.2,
            "mind.sleep": 0.15,
            "mind.stress": 0.15,
        }

        for src, avg_val in checkin_rows:
            if src in weights and avg_val is not None:
                # Invert stress (high stress = low score)
                val = (10.0 - avg_val) if src == "mind.stress" else avg_val
                score_components[src] = (val, weights[src])

        if score_components:
            total_weight = sum(w for _, w in score_components.values())
            weighted_sum = sum(v * w for v, w in score_components.values())
            day_score = (
                round(weighted_sum / total_weight, 2) if total_weight > 0 else 0.0
            )

            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="mind.derived",
                    event_type="subjective_day_score",
                    value_numeric=day_score,
                    value_json=safe_json(
                        {
                            "components": {
                                k: round(v, 1) for k, (v, _) in score_components.items()
                            },
                            "weights_used": {
                                k: w for k, (_, w) in score_components.items()
                            },
                            "scale": "0-10",
                        }
                    ),
                    confidence=0.9,
                    parser_version=self.version,
                )
            )
            log.info(f"[{day}] Subjective day score: {day_score}/10")

        # --- Mood trend 7d (rolling average) ---
        mood_rows = db.execute(
            """
            SELECT date(timestamp_local) as d, AVG(value_numeric) as avg_mood
            FROM events
            WHERE source_module = 'mind.mood'
              AND event_type = 'check_in'
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) <= ?
              AND date(timestamp_local) >= date(?, '-6 days')
            GROUP BY d
            ORDER BY d
            """,
            [day, day],
        ).fetchall()

        mood_values = [r[1] for r in mood_rows if r[1] is not None]
        if mood_values:
            mood_avg = round(statistics.mean(mood_values), 2)
            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="mind.derived",
                    event_type="mood_trend_7d",
                    value_numeric=mood_avg,
                    value_json=safe_json(
                        {
                            "days_in_window": len(mood_values),
                            "values": [round(v, 1) for v in mood_values],
                        }
                    ),
                    confidence=0.8 if len(mood_values) >= 3 else 0.5,
                    parser_version=self.version,
                )
            )
            log.info(f"[{day}] Mood trend 7d: {mood_avg} ({len(mood_values)} days)")

        # --- Energy stability (coefficient of variation over 7 days) ---
        energy_rows = db.execute(
            """
            SELECT date(timestamp_local) as d, AVG(value_numeric) as avg_energy
            FROM events
            WHERE source_module = 'mind.energy'
              AND event_type = 'check_in'
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) <= ?
              AND date(timestamp_local) >= date(?, '-6 days')
            GROUP BY d
            ORDER BY d
            """,
            [day, day],
        ).fetchall()

        energy_values = [r[1] for r in energy_rows if r[1] is not None]
        if len(energy_values) >= 2:
            e_mean = statistics.mean(energy_values)
            e_stdev = statistics.stdev(energy_values)
            cv = round((e_stdev / e_mean) * 100, 1) if e_mean > 0 else 0.0

            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="mind.derived",
                    event_type="energy_stability",
                    value_numeric=cv,
                    value_json=safe_json(
                        {
                            "unit": "coefficient_of_variation_pct",
                            "mean": round(e_mean, 2),
                            "stdev": round(e_stdev, 2),
                            "days_in_window": len(energy_values),
                            "interpretation": "lower is more stable",
                        }
                    ),
                    confidence=0.7 if len(energy_values) >= 3 else 0.4,
                    parser_version=self.version,
                )
            )
            log.info(f"[{day}] Energy stability CV: {cv}% ({len(energy_values)} days)")

        return derived

    def get_daily_summary(self, db, date_str: str) -> dict | None:
        """Return daily mind metrics for report generation."""
        try:
            cursor = db.execute(
                """
                SELECT source_module, event_type, value_numeric, value_json
                FROM events
                WHERE date(timestamp_local) = ?
                  AND source_module LIKE 'mind.%'
                  AND event_type IN ('assessment', 'check_in')
                ORDER BY timestamp_utc
                """,
                (date_str,),
            )
            rows = cursor.fetchall()
        except Exception as e:
            log.warning(f"Failed to query daily summary for {date_str}: {e}")
            return None

        if not rows:
            return None

        summary = {}
        for source, etype, val_num, val_json in rows:
            if etype == "assessment" and val_json:
                import json

                try:
                    data = json.loads(val_json)
                    prefix = "morning" if source == "mind.morning" else "evening"
                    for k, v in data.items():
                        if k != "source" and v is not None:
                            summary[f"{prefix}_{k}"] = v
                except (json.JSONDecodeError, TypeError):
                    pass

        return summary if summary else None


def create_module(config: dict | None = None) -> MindModule:
    """Factory function called by the orchestrator."""
    return MindModule(config)
