"""
Tests for WorldModule.post_ingest() derived metrics.

Derived metrics tested:
  - world.derived/news_sentiment_index: average sentiment of news/RSS headlines
  - world.derived/information_entropy: Shannon entropy of news categories
"""

import json
import math

import pytest

from core.event import Event
from modules.world import create_module

DATE = "2026-03-20"
DAY_TS = f"{DATE}T23:59:00+00:00"

CONFIG = {
    "lifedata": {
        "modules": {
            "world": {
                "enabled": True,
            }
        }
    }
}


def _world_config() -> dict:
    return CONFIG["lifedata"]["modules"]["world"]


def _make_event(
    source_module: str,
    event_type: str,
    timestamp_utc: str = f"{DATE}T12:00:00+00:00",
    timestamp_local: str = f"{DATE}T07:00:00-05:00",
    value_numeric: float | None = None,
    value_text: str | None = None,
    value_json: str | None = None,
) -> Event:
    return Event(
        timestamp_utc=timestamp_utc,
        timestamp_local=timestamp_local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        value_json=value_json,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _query_derived(db, event_type: str):
    """Return all derived events of a given type for the test date."""
    rows = db.execute(
        """
        SELECT value_numeric, value_json FROM events
        WHERE source_module = 'world.derived'
          AND event_type = ?
          AND timestamp_utc = ?
        """,
        (event_type, DAY_TS),
    ).fetchall()
    return rows


# ──────────────────────────────────────────────────────────────
# TestNewsSentimentIndex
# ──────────────────────────────────────────────────────────────


class TestNewsSentimentIndex:
    """Tests for world.derived/news_sentiment_index."""

    def test_average_correct(self, db):
        """Average of news + RSS sentiment values."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_text="Tech company announces breakthrough",
                value_json=json.dumps({"category": "technology"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.3,
                value_text="Markets rise on positive outlook",
                value_json=json.dumps({"category": "business"}),
            ),
            _make_event(
                "world.rss",
                "article",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                value_numeric=-0.3,
                value_text="New study raises concerns",
                value_json=json.dumps({"category": "science"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "news_sentiment_index")
        assert len(rows) == 1

        # Average: (0.5 + 0.3 + (-0.3)) / 3 = 0.1667
        expected = round((0.5 + 0.3 - 0.3) / 3, 4)
        assert rows[0][0] == pytest.approx(expected, abs=0.001)

        meta = json.loads(rows[0][1])
        assert meta["sample_size"] == 3

    def test_no_news_no_event(self, db):
        """No news/RSS events should produce no sentiment index event."""
        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "news_sentiment_index")
        assert len(rows) == 0

    def test_all_same_sentiment(self, db):
        """All headlines with the same sentiment produce that value as average."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T{10 + i}:00:00+00:00",
                value_numeric=0.75,
                value_json=json.dumps({"category": "technology"}),
            )
            for i in range(4)
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "news_sentiment_index")
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.75, abs=0.001)

    def test_value_json_contains_min_max(self, db):
        """Verify value_json contains sample_size, min, and max fields."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=-0.8,
                value_json=json.dumps({"category": "politics"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.9,
                value_json=json.dumps({"category": "technology"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "news_sentiment_index")
        assert len(rows) == 1
        meta = json.loads(rows[0][1])
        assert meta["sample_size"] == 2
        assert meta["min"] == pytest.approx(-0.8, abs=0.001)
        assert meta["max"] == pytest.approx(0.9, abs=0.001)


# ──────────────────────────────────────────────────────────────
# TestInformationEntropy
# ──────────────────────────────────────────────────────────────


class TestInformationEntropy:
    """Tests for world.derived/information_entropy."""

    def test_multiple_categories_high_entropy(self, db):
        """Multiple evenly distributed categories should yield high entropy."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "technology"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.3,
                value_json=json.dumps({"category": "science"}),
            ),
            _make_event(
                "world.rss",
                "article",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                value_numeric=-0.1,
                value_json=json.dumps({"category": "politics"}),
            ),
            _make_event(
                "world.rss",
                "article",
                timestamp_utc=f"{DATE}T13:00:00+00:00",
                value_numeric=0.2,
                value_json=json.dumps({"category": "health"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 1

        # 4 categories, each with probability 0.25
        # entropy = -4 * (0.25 * log2(0.25)) = 2.0
        expected = 2.0
        assert rows[0][0] == pytest.approx(expected, abs=0.001)

        meta = json.loads(rows[0][1])
        assert meta["num_categories"] == 4

    def test_single_category_zero_entropy(self, db):
        """All headlines in one category should yield zero entropy."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "technology"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.8,
                value_json=json.dumps({"category": "technology"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 1
        # Single category => entropy = -1 * (1.0 * log2(1.0)) = 0.0
        assert rows[0][0] == 0.0

    def test_no_categories_no_event(self, db):
        """No news events should produce no entropy event."""
        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 0

    def test_uniform_distribution_maximum_entropy(self, db):
        """N equally distributed categories yield log2(N) entropy."""
        categories = ["tech", "science", "politics", "health", "sports", "business", "entertainment", "world"]
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T{10 + i}:00:00+00:00",
                value_numeric=0.1 * i,
                value_json=json.dumps({"category": cat}),
            )
            for i, cat in enumerate(categories)
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 1

        # 8 categories, uniform -> entropy = log2(8) = 3.0
        expected = math.log2(len(categories))
        assert rows[0][0] == pytest.approx(expected, abs=0.001)

        meta = json.loads(rows[0][1])
        assert meta["num_categories"] == 8

    def test_skewed_distribution_lower_entropy(self, db):
        """A skewed distribution has lower entropy than uniform."""
        # 5 tech, 1 science, 1 politics, 1 health -> skewed toward tech
        cats = ["technology"] * 5 + ["science", "politics", "health"]
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T{10 + i}:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": cat}),
            )
            for i, cat in enumerate(cats)
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 1

        # Max entropy for 4 categories = log2(4) = 2.0
        # Skewed distribution should be less than that
        max_entropy = math.log2(4)
        assert rows[0][0] < max_entropy
        assert rows[0][0] > 0.0

        meta = json.loads(rows[0][1])
        assert meta["num_categories"] == 4
        cat_counts = meta["category_counts"]
        assert cat_counts["technology"] == 5

    def test_category_counts_in_value_json(self, db):
        """Verify category_counts and num_categories in value_json."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.3,
                value_json=json.dumps({"category": "tech"}),
            ),
            _make_event(
                "world.rss",
                "article",
                timestamp_utc=f"{DATE}T12:00:00+00:00",
                value_numeric=-0.2,
                value_json=json.dumps({"category": "sports"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        rows = _query_derived(db, "information_entropy")
        assert len(rows) == 1
        meta = json.loads(rows[0][1])
        assert meta["num_categories"] == 2
        assert meta["category_counts"]["tech"] == 2
        assert meta["category_counts"]["sports"] == 1
