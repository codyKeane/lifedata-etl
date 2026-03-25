"""
LifeData V4 — World Module Parsers
modules/world/parsers.py

Parses JSON files produced by the fetch scripts in scripts/:
  - headlines_*.json  → world.news events
  - markets_*.json    → world.markets events
  - feeds_*.json      → world.rss events
  - events_*.json     → world.gdelt events
"""

import json
from datetime import UTC, datetime

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_json

log = get_logger("lifedata.world.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def _iso_to_utc_local(iso_str: str) -> tuple[str, str]:
    """Convert an ISO timestamp to (utc_iso, local_iso) pair.

    Falls back to parse_timestamp if ISO parsing fails.
    """
    if not iso_str:
        now = datetime.now(UTC)
        return now.isoformat(), now.isoformat()
    try:
        return parse_timestamp(iso_str, DEFAULT_TZ_OFFSET)
    except (ValueError, TypeError):
        now = datetime.now(UTC)
        return now.isoformat(), now.isoformat()


def _fetch_time_to_ts(fetched_utc: str) -> tuple[str, str]:
    """Use the fetched_utc timestamp from the JSON as the event timestamp."""
    return _iso_to_utc_local(fetched_utc)


def parse_news_json(file_path: str) -> list[Event]:
    """Parse NewsAPI headlines JSON → world.news events.

    Each article becomes an event with:
      - source_module: world.news
      - event_type: headline
      - value_text: headline title
      - value_numeric: sentiment score (-1 to +1)
      - value_json: category, source, url, sentiment_detail
    """
    events = []
    try:
        with open(file_path, encoding="utf-8") as f:
            articles = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read {file_path}: {e}")
        return []

    if not isinstance(articles, list):
        return []

    for art in articles:
        try:
            title = art.get("title", "").strip()
            if not title or title == "[Removed]":
                continue

            ts_utc, ts_local = _fetch_time_to_ts(
                art.get("published_at") or art.get("fetched_utc", "")
            )
            sentiment = safe_float(art.get("sentiment", 0))

            extra = {
                "category": art.get("category", ""),
                "source_name": art.get("source_name", ""),
                "url": art.get("url", ""),
            }
            if art.get("sentiment_detail"):
                extra["sentiment_detail"] = art["sentiment_detail"]

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="world.news",
                    event_type="headline",
                    value_numeric=sentiment,
                    value_text=title[:500],
                    value_json=safe_json(extra),
                    confidence=0.9,
                    parser_version=PARSER_VERSION,
                )
            )
        except Exception as e:
            log.warning(f"news parse error: {e}")
            continue

    return events


def parse_markets_json(file_path: str) -> list[Event]:
    """Parse market indicators JSON → world.markets events.

    Each indicator becomes an event:
      - bitcoin → value_numeric = USD price
      - gas_price_avg → value_numeric = USD/gallon
    """
    events = []
    try:
        with open(file_path, encoding="utf-8") as f:
            indicators = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read {file_path}: {e}")
        return []

    if not isinstance(indicators, list):
        return []

    for ind in indicators:
        try:
            indicator_name = ind.get("indicator", "unknown")
            ts_utc, ts_local = _fetch_time_to_ts(ind.get("fetched_utc", ""))
            value = safe_float(ind.get("value_usd"))

            if value is None:
                continue

            extra = {}
            if ind.get("change_24h_pct") is not None:
                extra["change_24h_pct"] = ind["change_24h_pct"]
            if ind.get("period"):
                extra["period"] = ind["period"]

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="world.markets",
                    event_type=indicator_name,
                    value_numeric=value,
                    value_json=safe_json(extra) if extra else None,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                )
            )
        except Exception as e:
            log.warning(f"markets parse error: {e}")
            continue

    return events


def parse_rss_json(file_path: str) -> list[Event]:
    """Parse RSS feeds JSON → world.rss events.

    Each article becomes an event:
      - value_text: article title
      - value_numeric: sentiment score
      - value_json: feed_name, category, url
    """
    events = []
    try:
        with open(file_path, encoding="utf-8") as f:
            articles = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read {file_path}: {e}")
        return []

    if not isinstance(articles, list):
        return []

    for art in articles:
        try:
            title = art.get("title", "").strip()
            if not title:
                continue

            ts_utc, ts_local = _fetch_time_to_ts(
                art.get("published") or art.get("fetched_utc", "")
            )
            sentiment = safe_float(art.get("sentiment", 0))

            extra = {
                "feed_name": art.get("feed_name", ""),
                "category": art.get("category", ""),
                "url": art.get("link", ""),
            }

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="world.rss",
                    event_type="article",
                    value_numeric=sentiment,
                    value_text=title[:500],
                    value_json=safe_json(extra),
                    confidence=0.85,
                    parser_version=PARSER_VERSION,
                )
            )
        except Exception as e:
            log.warning(f"rss parse error: {e}")
            continue

    return events


def parse_gdelt_json(file_path: str) -> list[Event]:
    """Parse GDELT articles JSON → world.gdelt events.

    Each article becomes an event:
      - value_text: article title
      - value_numeric: tone score (-10 to +10)
      - value_json: source, country, themes, url
    """
    events = []
    try:
        with open(file_path, encoding="utf-8") as f:
            articles = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"Failed to read {file_path}: {e}")
        return []

    if not isinstance(articles, list):
        return []

    for art in articles:
        try:
            title = art.get("title", "").strip()
            if not title:
                continue

            ts_utc, ts_local = _fetch_time_to_ts(
                art.get("seendate") or art.get("fetched_utc", "")
            )
            tone = safe_float(art.get("tone", 0))

            extra = {
                "source": art.get("source", ""),
                "source_country": art.get("source_country", ""),
                "url": art.get("url", ""),
                "query_name": art.get("query_name", ""),
            }

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="world.gdelt",
                    event_type="global_event",
                    value_numeric=tone,
                    value_text=title[:500],
                    value_json=safe_json(extra),
                    confidence=0.8,
                    parser_version=PARSER_VERSION,
                )
            )
        except Exception as e:
            log.warning(f"gdelt parse error: {e}")
            continue

    return events


# Parser registry: filename prefix → parser function
PARSER_REGISTRY = {
    "headlines_": parse_news_json,
    "markets_": parse_markets_json,
    "feeds_": parse_rss_json,
    "events_": parse_gdelt_json,
}
