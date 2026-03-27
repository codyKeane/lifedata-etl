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

from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import get_utc_offset, glob_files, safe_float, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.world")


class WorldModule(ModuleInterface):
    """World module — captures exogenous context from news, markets, RSS, GDELT."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        # Lazy import to avoid circular dependencies at module load time
        self._parser_registry: dict[str, Any] | None = None

    def _tz_offset(self, date_str: str) -> str:
        """Get DST-aware UTC offset for a date from config timezone."""
        tz_name = self._config.get("_timezone", "America/Chicago")
        try:
            return get_utc_offset(tz_name, date_str)
        except Exception:
            return str(self._config.get("_default_tz_offset", "-0500"))

    def _get_parsers(self) -> dict[str, Any]:
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.world.parsers import PARSER_REGISTRY

            self._parser_registry = PARSER_REGISTRY
        assert self._parser_registry is not None
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

    def get_metrics_manifest(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "name": "world.news",
                    "display_name": "News Headlines",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "world.rss",
                    "display_name": "RSS Articles",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "world.derived:news_sentiment_index",
                    "display_name": "News Sentiment",
                    "unit": "score",
                    "aggregate": "AVG",
                    "event_type": "news_sentiment_index",
                    "trend_eligible": True,
                    "anomaly_eligible": True,
                },
                {
                    "name": "world.derived:information_entropy",
                    "display_name": "Topic Diversity",
                    "unit": "bits",
                    "aggregate": "AVG",
                    "event_type": "information_entropy",
                    "trend_eligible": False,
                    "anomaly_eligible": True,
                },
            ],
        }

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
                events: list[Event] = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for world file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Compute and store derived metrics after all world events are ingested.

        Derived metrics:
          - world.derived/news_sentiment_index: daily average sentiment
          - world.derived/information_entropy: topic diversity
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
            inserted, skipped = db.insert_events_for_module("world", all_derived)
            log.info(f"World derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db: Database, today: str) -> list[Event]:
        """Compute all derived world metrics for a single day."""
        derived_events: list[Event] = []
        # Deterministic timestamp for derived daily metrics (idempotent hashing)
        day_ts = f"{today}T23:59:00+00:00"

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

        # News Sentiment Index (NSI)
        if self.is_metric_enabled("world.derived:news_sentiment_index") and sentiments:
            nsi = round(sum(sentiments) / len(sentiments), 4)
            derived_events.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset=self._tz_offset(today),
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
        if self.is_metric_enabled("world.derived:information_entropy") and categories:
            cat_counts = Counter(categories)
            total = sum(cat_counts.values())
            probs = [c / total for c in cat_counts.values()]
            entropy = -sum(p * math.log2(p) for p in probs if p > 0)
            entropy = round(entropy, 4)

            derived_events.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset=self._tz_offset(today),
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

        return derived_events

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily summary metrics for the report generator.

        Respects disabled_metrics — bullets for disabled metrics are omitted.
        """
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

        bullets: list[str] = []
        if self.is_metric_enabled("world.derived:news_sentiment_index"):
            nsi_val = nsi_row.get("avg_value")
            if nsi_val is not None:
                bullets.append(f"- News sentiment index: {nsi_val:.4f}")
        if self.is_metric_enabled("world.derived:information_entropy"):
            entropy_val = entropy_row.get("avg_value")
            if entropy_val is not None:
                bullets.append(f"- Information entropy: {entropy_val:.4f}")

        return {
            "event_counts": summary,
            "news_sentiment_index": nsi_row.get("avg_value"),
            "information_entropy": entropy_row.get("avg_value"),
            "total_world_events": sum(v["count"] for v in summary.values()),
            "section_title": "World",
            "bullets": bullets,
        }


def create_module(config: dict[str, Any] | None = None) -> WorldModule:
    """Factory function called by the orchestrator."""
    return WorldModule(config)
