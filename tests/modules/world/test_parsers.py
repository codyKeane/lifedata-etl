"""
Tests for modules/world/parsers.py — news JSON, markets JSON, RSS JSON, GDELT JSON.
"""

import json

from modules.world.parsers import (
    parse_gdelt_json,
    parse_markets_json,
    parse_news_json,
    parse_rss_json,
)

# ──────────────────────────────────────────────────────────────
# News JSON parser
# ──────────────────────────────────────────────────────────────


class TestParseNewsJson:
    def test_happy_path(self, tmp_path):
        data = [
            {
                "title": "Major breakthrough in quantum computing",
                "published_at": "2026-03-24T10:00:00Z",
                "sentiment": 0.6,
                "source_name": "TechCrunch",
                "category": "technology",
                "url": "https://example.com/article1",
            },
            {
                "title": "Markets rally on economic data",
                "published_at": "2026-03-24T11:00:00Z",
                "sentiment": 0.3,
                "source_name": "Bloomberg",
                "category": "business",
                "url": "https://example.com/article2",
            },
        ]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert len(events) == 2
        assert events[0].source_module == "world.news"
        assert events[0].event_type == "headline"
        assert events[0].value_text == "Major breakthrough in quantum computing"
        assert events[0].value_numeric == 0.6

    def test_sentiment_detail_included(self, tmp_path):
        data = [
            {
                "title": "Test headline",
                "published_at": "2026-03-24T10:00:00Z",
                "sentiment": 0.5,
                "sentiment_detail": {"pos": 0.6, "neg": 0.1, "neu": 0.3},
            }
        ]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        extra = json.loads(events[0].value_json)
        assert "sentiment_detail" in extra

    def test_removed_title_skipped(self, tmp_path):
        data = [{"title": "[Removed]", "published_at": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert len(events) == 0

    def test_empty_title_skipped(self, tmp_path):
        data = [{"title": "", "published_at": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert len(events) == 0

    def test_malformed_json_returns_empty(self, tmp_path):
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text("{bad json")
        events = parse_news_json(str(path))
        assert events == []

    def test_not_a_list_returns_empty(self, tmp_path):
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps({"title": "single object"}))
        events = parse_news_json(str(path))
        assert events == []

    def test_title_truncated_to_500(self, tmp_path):
        data = [{"title": "x" * 1000, "published_at": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert len(events[0].value_text) <= 500

    def test_fallback_to_fetched_utc(self, tmp_path):
        data = [{"title": "No pub date", "fetched_utc": "2026-03-24T15:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert len(events) == 1
        assert "2026-03-24" in events[0].timestamp_utc

    def test_events_valid(self, tmp_path):
        data = [
            {
                "title": "Test headline",
                "published_at": "2026-03-24T10:00:00Z",
                "sentiment": 0.5,
            }
        ]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_news_json(str(path)):
            assert e.is_valid

    def test_deterministic(self, tmp_path):
        data = [{"title": "Test", "published_at": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        ids1 = [e.event_id for e in parse_news_json(str(path))]
        ids2 = [e.event_id for e in parse_news_json(str(path))]
        assert ids1 == ids2

    def test_timezone_offset_applied(self, tmp_path):
        """World parsers use DEFAULT_TZ_OFFSET — verify it's set consistently."""
        data = [{"title": "Test", "published_at": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "headlines_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_news_json(str(path))
        assert events[0].timezone_offset == "-0500"


# ──────────────────────────────────────────────────────────────
# Markets JSON parser
# ──────────────────────────────────────────────────────────────


class TestParseMarketsJson:
    def test_happy_path(self, tmp_path):
        data = [
            {
                "indicator": "bitcoin",
                "value_usd": 67500.50,
                "fetched_utc": "2026-03-24T10:00:00Z",
                "change_24h_pct": 2.3,
            },
            {
                "indicator": "gas_price_avg",
                "value_usd": 3.45,
                "fetched_utc": "2026-03-24T10:00:00Z",
            },
        ]
        path = tmp_path / "markets_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_markets_json(str(path))
        assert len(events) == 2
        assert events[0].source_module == "world.markets"
        assert events[0].event_type == "bitcoin"
        assert events[0].value_numeric == 67500.50
        assert events[1].event_type == "gas_price_avg"

    def test_null_value_skipped(self, tmp_path):
        data = [{"indicator": "bitcoin", "value_usd": None, "fetched_utc": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "markets_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_markets_json(str(path))
        assert len(events) == 0

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "markets_2026-03-24.json"
        path.write_text("not json at all")
        assert parse_markets_json(str(path)) == []

    def test_events_valid(self, tmp_path):
        data = [{"indicator": "btc", "value_usd": 100.0, "fetched_utc": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "markets_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_markets_json(str(path)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# GDELT JSON parser
# ──────────────────────────────────────────────────────────────


class TestParseGdeltJson:
    def test_happy_path(self, tmp_path):
        data = [
            {
                "title": "Diplomatic summit yields agreement",
                "seendate": "2026-03-24T10:00:00Z",
                "tone": -3.5,
                "source": "Reuters",
                "source_country": "US",
                "url": "https://example.com/event1",
                "query_name": "diplomacy",
            }
        ]
        path = tmp_path / "events_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_gdelt_json(str(path))
        assert len(events) == 1
        assert events[0].source_module == "world.gdelt"
        assert events[0].event_type == "global_event"
        assert events[0].value_numeric == -3.5
        assert events[0].value_text == "Diplomatic summit yields agreement"

    def test_empty_title_skipped(self, tmp_path):
        data = [{"title": "", "seendate": "2026-03-24T10:00:00Z", "tone": 0}]
        path = tmp_path / "events_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_gdelt_json(str(path))
        assert len(events) == 0

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "events_2026-03-24.json"
        path.write_text("{broken")
        assert parse_gdelt_json(str(path)) == []

    def test_events_valid(self, tmp_path):
        data = [{"title": "Test", "seendate": "2026-03-24T10:00:00Z", "tone": 1.0}]
        path = tmp_path / "events_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_gdelt_json(str(path)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# RSS JSON parser
# ──────────────────────────────────────────────────────────────


class TestParseRssJson:
    def test_happy_path(self, tmp_path):
        data = [
            {
                "title": "New study on sleep patterns",
                "published": "2026-03-24T10:00:00Z",
                "sentiment": 0.2,
                "feed_name": "ScienceDaily",
                "category": "health",
                "link": "https://example.com/rss1",
            }
        ]
        path = tmp_path / "feeds_2026-03-24.json"
        path.write_text(json.dumps(data))
        events = parse_rss_json(str(path))
        assert len(events) == 1
        assert events[0].source_module == "world.rss"
        assert events[0].event_type == "article"
        assert events[0].value_numeric == 0.2
        extra = json.loads(events[0].value_json)
        assert extra["feed_name"] == "ScienceDaily"

    def test_empty_title_skipped(self, tmp_path):
        data = [{"title": "", "published": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "feeds_2026-03-24.json"
        path.write_text(json.dumps(data))
        assert parse_rss_json(str(path)) == []

    def test_malformed_json(self, tmp_path):
        path = tmp_path / "feeds_2026-03-24.json"
        path.write_text("nope")
        assert parse_rss_json(str(path)) == []

    def test_events_valid(self, tmp_path):
        data = [{"title": "Test", "published": "2026-03-24T10:00:00Z"}]
        path = tmp_path / "feeds_2026-03-24.json"
        path.write_text(json.dumps(data))
        for e in parse_rss_json(str(path)):
            assert e.is_valid
