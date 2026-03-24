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

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files
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
                    log.info(
                        f"Parsed {len(events)} events from {basename}"
                    )
                return events

        log.warning(f"No parser found for mind file: {basename}")
        return []

    def post_ingest(self, db) -> None:
        """Compute derived mind metrics after ingestion."""
        # Future: compute subjective_day_score, mood_trend_7d, etc.
        pass

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
