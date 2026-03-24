"""
LifeData V4 — World Module
modules/world/module.py

Captures external context: news headlines, market indicators, RSS feeds,
and GDELT global events. This is the exogenous context layer — variables
that affect the user through the information environment but which the
user does not control.

File discovery pattern:
  raw/api/news/headlines_*.json  → world.news     (NewsAPI)
  raw/api/markets/markets_*.json → world.markets   (CoinGecko, EIA)
  raw/api/rss/feeds_*.json       → world.rss       (curated RSS)
  raw/api/gdelt/events_*.json    → world.gdelt     (GDELT DOC API)
"""

import json
import math
import os
from collections import Counter
from datetime import datetime, timezone

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_float, safe_json

log = get_logger("lifedata.world")


class WorldModule(ModuleInterface):
    """World module — captures exogenous context from news, markets, RSS, GDELT."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        # Lazy import to avoid circular dependencies at module load time
        self._parser_registry = None

    def _get_parsers(self):
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.world.parsers import PARSER_REGISTRY

            self._parser_registry = PARSER_REGISTRY
        return self._parser_registry

    @property
    def module_id(self) -> str:
        return "world"

    @property
    def display_name(self) -> str:
        return "World Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "world.news",
            "world.markets",
            "world.rss",
            "world.gdelt",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find JSON files in raw/api subdirectories."""
        files = []
        expanded = os.path.expanduser(raw_base)

        # raw_base is typically ~/LifeData/raw/LifeData
        # api data lives at ~/LifeData/raw/api/ — find the raw/ root
        raw_root = expanded
        while raw_root and os.path.basename(raw_root) != "raw":
            raw_root = os.path.dirname(raw_root)
        if not raw_root or os.path.basename(raw_root) != "raw":
            # Fallback: try one directory above raw_base's grandparent
            raw_root = os.path.dirname(os.path.dirname(expanded))

        api_base = os.path.join(raw_root, "api")

        search_dirs = [
            os.path.join(api_base, "news"),
            os.path.join(api_base, "markets"),
            os.path.join(api_base, "rss"),
            os.path.join(api_base, "gdelt"),
        ]

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for json_file in glob_files(search_dir, "*.json", recursive=False):
                basename = os.path.basename(json_file)
                if any(basename.startswith(prefix) for prefix in self._get_parsers()):
                    files.append(json_file)

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
        """Parse a single JSON file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in self._get_parsers().items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for world file: {basename}")
        return []

    def post_ingest(self, db) -> None:
        """Compute and store derived metrics after all world events are ingested.

        Derived metrics:
          - world.derived/news_sentiment_index: daily average sentiment
          - world.derived/information_entropy: topic diversity
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        derived_events = []

        # Collect today's headline sentiment values
        rows = db.execute(
            """
            SELECT value_numeric, value_json
            FROM events
            WHERE source_module IN ('world.news', 'world.rss')
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (today,),
        )
        sentiments = []
        categories = []
        for row in rows:
            val = safe_float(row[0])
            if val is not None:
                sentiments.append(val)
            # Extract category from value_json
            try:
                vj = json.loads(row[1]) if row[1] else {}
                cat = vj.get("category", "unknown")
                if cat:
                    categories.append(cat)
            except (json.JSONDecodeError, TypeError):
                pass

        now_utc = datetime.now(timezone.utc).isoformat()

        # News Sentiment Index (NSI)
        if sentiments:
            nsi = round(sum(sentiments) / len(sentiments), 4)
            derived_events.append(
                Event(
                    timestamp_utc=now_utc,
                    timestamp_local=now_utc,
                    timezone_offset="-0500",
                    source_module="world.derived",
                    event_type="news_sentiment_index",
                    value_numeric=nsi,
                    value_json=safe_json(
                        {
                            "sample_size": len(sentiments),
                            "min": round(min(sentiments), 4),
                            "max": round(max(sentiments), 4),
                        }
                    ),
                    confidence=0.9,
                    parser_version=self.version,
                )
            )
            log.info(f"NSI: {nsi:.4f} (from {len(sentiments)} headlines)")

        # Information Entropy
        if categories:
            cat_counts = Counter(categories)
            total = sum(cat_counts.values())
            probs = [c / total for c in cat_counts.values()]
            entropy = -sum(p * math.log2(p) for p in probs if p > 0)
            entropy = round(entropy, 4)

            derived_events.append(
                Event(
                    timestamp_utc=now_utc,
                    timestamp_local=now_utc,
                    timezone_offset="-0500",
                    source_module="world.derived",
                    event_type="information_entropy",
                    value_numeric=entropy,
                    value_json=safe_json(
                        {
                            "category_counts": dict(cat_counts),
                            "num_categories": len(cat_counts),
                        }
                    ),
                    confidence=0.9,
                    parser_version=self.version,
                )
            )
            log.info(
                f"Information entropy: {entropy:.4f} ({len(cat_counts)} categories)"
            )

        # Insert derived events
        if derived_events:
            inserted, skipped = db.insert_events_for_module("world", derived_events)
            log.info(f"Derived metrics: {inserted} inserted, {skipped} skipped")

    def get_daily_summary(self, db, date_str: str) -> dict | None:
        """Return daily summary metrics for the report generator."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt,
                   AVG(value_numeric) as avg_val
            FROM events
            WHERE source_module LIKE 'world.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        for row in rows:
            src, evt, cnt, avg_val = row
            key = f"{src}.{evt}"
            summary[key] = {
                "count": cnt,
                "avg_value": round(avg_val, 4) if avg_val is not None else None,
            }

        if not summary:
            return None

        # Extract key metrics for top-level display
        nsi_row = summary.get("world.derived.news_sentiment_index", {})
        entropy_row = summary.get("world.derived.information_entropy", {})

        return {
            "event_counts": summary,
            "news_sentiment_index": nsi_row.get("avg_value"),
            "information_entropy": entropy_row.get("avg_value"),
            "total_world_events": sum(v["count"] for v in summary.values()),
        }


def create_module(config: dict | None = None) -> WorldModule:
    """Factory function called by the orchestrator."""
    return WorldModule(config)
