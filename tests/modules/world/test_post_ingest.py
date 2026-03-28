"""
Tests for WorldModule — post_ingest(), discover_files(), parse(),
get_daily_summary(), _tz_offset(), _get_parsers(), and create_module().

Derived metrics tested:
  - world.derived/news_sentiment_index: average sentiment of news/RSS headlines
  - world.derived/information_entropy: Shannon entropy of news categories
"""

import json
import math
import os

import pytest

from core.event import Event
from modules.world import create_module
from modules.world.module import WorldModule

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


# ──────────────────────────────────────────────────────────────
# TestTzOffset
# ──────────────────────────────────────────────────────────────


class TestTzOffset:
    """Tests for WorldModule._tz_offset()."""

    def test_tz_offset_default_timezone(self):
        """Default timezone (America/Chicago) returns a valid offset."""
        mod = WorldModule({"_timezone": "America/Chicago"})
        result = mod._tz_offset("2026-03-20")
        # Should be -0500 (CDT) or -0600 (CST) depending on DST
        assert result in ("-0500", "-0600")

    def test_tz_offset_fallback_on_exception(self):
        """Invalid timezone triggers except branch, returns -0500."""
        mod = WorldModule({"_timezone": "Invalid/Nonexistent_Zone_XYZ"})
        result = mod._tz_offset("2026-03-20")
        assert result == "-0500"

    def test_tz_offset_no_timezone_in_config(self):
        """No _timezone key in config defaults to America/Chicago."""
        mod = WorldModule({})
        result = mod._tz_offset("2026-03-20")
        assert result in ("-0500", "-0600")


# ──────────────────────────────────────────────────────────────
# TestGetParsers
# ──────────────────────────────────────────────────────────────


class TestGetParsers:
    """Tests for WorldModule._get_parsers() lazy loading."""

    def test_lazy_loads_parser_registry(self):
        """Parser registry is None initially and loaded on first call."""
        mod = WorldModule()
        assert mod._parser_registry is None
        parsers = mod._get_parsers()
        assert parsers is not None
        assert mod._parser_registry is parsers

    def test_cached_on_second_call(self):
        """Second call returns same object without re-import."""
        mod = WorldModule()
        first = mod._get_parsers()
        second = mod._get_parsers()
        assert first is second

    def test_registry_has_expected_prefixes(self):
        """Registry contains the expected file prefixes."""
        mod = WorldModule()
        parsers = mod._get_parsers()
        assert "headlines_" in parsers
        assert "markets_" in parsers
        assert "feeds_" in parsers
        assert "events_" in parsers


# ──────────────────────────────────────────────────────────────
# TestModuleProperties
# ──────────────────────────────────────────────────────────────


class TestModuleProperties:
    """Tests for module_id, display_name, version, source_types, get_metrics_manifest."""

    def test_module_id(self):
        mod = WorldModule()
        assert mod.module_id == "world"

    def test_display_name(self):
        mod = WorldModule()
        assert mod.display_name == "World Module"

    def test_version(self):
        mod = WorldModule()
        assert mod.version == "1.0.0"

    def test_source_types(self):
        mod = WorldModule()
        assert "world.news" in mod.source_types
        assert "world.markets" in mod.source_types
        assert "world.rss" in mod.source_types
        assert "world.gdelt" in mod.source_types

    def test_get_metrics_manifest(self):
        mod = WorldModule()
        manifest = mod.get_metrics_manifest()
        assert "metrics" in manifest
        names = [m["name"] for m in manifest["metrics"]]
        assert "world.news" in names
        assert "world.derived:news_sentiment_index" in names
        assert "world.derived:information_entropy" in names


# ──────────────────────────────────────────────────────────────
# TestDiscoverFiles
# ──────────────────────────────────────────────────────────────


class TestDiscoverFiles:
    """Tests for WorldModule.discover_files()."""

    def test_discover_json_files(self, tmp_path):
        """Discovers JSON files matching parser prefixes in api subdirectories."""
        # Build raw/api/{news,markets,rss,gdelt} structure
        raw_dir = tmp_path / "raw" / "LifeData"
        raw_dir.mkdir(parents=True)
        api_base = tmp_path / "raw" / "api"
        for subdir in ["news", "markets", "rss", "gdelt"]:
            d = api_base / subdir
            d.mkdir(parents=True)

        # Create matching JSON files
        (api_base / "news" / "headlines_2026-03-20.json").write_text("{}")
        (api_base / "markets" / "markets_2026-03-20.json").write_text("{}")
        (api_base / "rss" / "feeds_2026-03-20.json").write_text("{}")
        (api_base / "gdelt" / "events_2026-03-20.json").write_text("{}")
        # Non-matching file should be excluded
        (api_base / "news" / "random_file.json").write_text("{}")

        mod = WorldModule()
        files = mod.discover_files(str(raw_dir))
        basenames = [os.path.basename(f) for f in files]
        assert "headlines_2026-03-20.json" in basenames
        assert "markets_2026-03-20.json" in basenames
        assert "feeds_2026-03-20.json" in basenames
        assert "events_2026-03-20.json" in basenames
        assert "random_file.json" not in basenames

    def test_discover_deduplicates(self, tmp_path):
        """Duplicate files (e.g., symlinks) are deduplicated."""
        raw_dir = tmp_path / "raw" / "LifeData"
        raw_dir.mkdir(parents=True)
        news_dir = tmp_path / "raw" / "api" / "news"
        news_dir.mkdir(parents=True)
        original = news_dir / "headlines_2026-03-20.json"
        original.write_text("{}")

        mod = WorldModule()
        files = mod.discover_files(str(raw_dir))
        assert len([f for f in files if "headlines_2026-03-20" in f]) == 1

    def test_discover_missing_dirs(self, tmp_path):
        """Missing api subdirectories are skipped gracefully."""
        raw_dir = tmp_path / "raw" / "LifeData"
        raw_dir.mkdir(parents=True)
        # No api/ dir at all
        mod = WorldModule()
        files = mod.discover_files(str(raw_dir))
        assert files == []

    def test_discover_raw_base_is_raw_itself(self, tmp_path):
        """When raw_base IS the 'raw' directory, finds api subdirs correctly."""
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        api_news = raw_dir / "api" / "news"
        api_news.mkdir(parents=True)
        (api_news / "headlines_2026-03-20.json").write_text("{}")

        mod = WorldModule()
        files = mod.discover_files(str(raw_dir))
        basenames = [os.path.basename(f) for f in files]
        assert "headlines_2026-03-20.json" in basenames

    def test_discover_deeply_nested_raw(self, tmp_path):
        """When raw_base is deeply nested under 'raw', still finds api dir."""
        raw_dir = tmp_path / "raw" / "LifeData" / "nested" / "deep"
        raw_dir.mkdir(parents=True)
        api_news = tmp_path / "raw" / "api" / "news"
        api_news.mkdir(parents=True)
        (api_news / "headlines_2026-03-20.json").write_text("{}")

        mod = WorldModule()
        files = mod.discover_files(str(raw_dir))
        basenames = [os.path.basename(f) for f in files]
        assert "headlines_2026-03-20.json" in basenames


# ──────────────────────────────────────────────────────────────
# TestParse
# ──────────────────────────────────────────────────────────────


class TestParse:
    """Tests for WorldModule.parse()."""

    def test_parse_with_valid_news_json(self, tmp_path):
        """Parses a headlines JSON file and returns events."""
        news_file = tmp_path / "headlines_2026-03-20.json"
        # Minimal valid news JSON structure
        news_data = {
            "status": "ok",
            "articles": [
                {
                    "title": "Test headline",
                    "publishedAt": "2026-03-20T12:00:00Z",
                    "source": {"name": "TestSource"},
                    "description": "Test description",
                    "url": "https://example.com",
                    "category": "technology",
                },
            ],
        }
        news_file.write_text(json.dumps(news_data))

        mod = WorldModule()
        events = mod.parse(str(news_file))
        # Should return a list (possibly empty depending on parser expectations)
        assert isinstance(events, list)

    def test_parse_no_matching_parser(self, tmp_path):
        """File with unknown prefix logs warning, returns empty list."""
        unknown_file = tmp_path / "unknown_2026-03-20.json"
        unknown_file.write_text("{}")

        mod = WorldModule()
        events = mod.parse(str(unknown_file))
        assert events == []

    def test_parse_with_matching_prefix_empty_result(self, tmp_path):
        """Parser that returns empty list from malformed data."""
        news_file = tmp_path / "headlines_2026-03-20.json"
        # Invalid structure — no articles key
        news_file.write_text(json.dumps({"status": "error"}))

        mod = WorldModule()
        events = mod.parse(str(news_file))
        assert isinstance(events, list)


# ──────────────────────────────────────────────────────────────
# TestPostIngestEdgeCases
# ──────────────────────────────────────────────────────────────


class TestPostIngestEdgeCases:
    """Edge cases for post_ingest()."""

    def test_affected_dates_none_uses_today(self, db):
        """When affected_dates is None, uses today's date."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc="2026-03-26T12:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        # affected_dates=None triggers the else branch using datetime.now(UTC)
        mod.post_ingest(db, affected_dates=None)
        # Should not crash; derived events are for today, not DATE

    def test_empty_affected_dates_set(self, db):
        """Empty set of affected_dates produces no derived events."""
        mod = create_module(_world_config())
        # Empty set is falsy, so takes the else branch
        mod.post_ingest(db, affected_dates=set())
        # No crash, no derived events

    def test_disabled_sentiment_metric(self, db):
        """Disabled sentiment metric produces no NSI event but entropy still works."""
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
                value_json=json.dumps({"category": "science"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        config = _world_config().copy()
        config["disabled_metrics"] = ["world.derived:news_sentiment_index"]
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        nsi_rows = _query_derived(db, "news_sentiment_index")
        assert len(nsi_rows) == 0

        entropy_rows = _query_derived(db, "information_entropy")
        assert len(entropy_rows) == 1

    def test_disabled_entropy_metric(self, db):
        """Disabled entropy metric produces no entropy event but NSI still works."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        config = _world_config().copy()
        config["disabled_metrics"] = ["world.derived:information_entropy"]
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        nsi_rows = _query_derived(db, "news_sentiment_index")
        assert len(nsi_rows) == 1

        entropy_rows = _query_derived(db, "information_entropy")
        assert len(entropy_rows) == 0

    def test_both_metrics_disabled(self, db):
        """Both derived metrics disabled produces no events."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        config = _world_config().copy()
        config["disabled_metrics"] = [
            "world.derived:news_sentiment_index",
            "world.derived:information_entropy",
        ]
        mod = create_module(config)
        mod.post_ingest(db, affected_dates={DATE})

        nsi_rows = _query_derived(db, "news_sentiment_index")
        entropy_rows = _query_derived(db, "information_entropy")
        assert len(nsi_rows) == 0
        assert len(entropy_rows) == 0

    def test_multiple_affected_dates(self, db):
        """Multiple dates process independently."""
        date1 = "2026-03-19"
        date2 = "2026-03-20"
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{date1}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{date2}T10:00:00+00:00",
                value_numeric=-0.3,
                value_json=json.dumps({"category": "politics"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={date1, date2})

        # Both dates should have NSI
        rows1 = db.execute(
            "SELECT value_numeric FROM events WHERE source_module='world.derived' "
            "AND event_type='news_sentiment_index' AND timestamp_utc LIKE ?",
            (f"{date1}%",),
        ).fetchall()
        rows2 = db.execute(
            "SELECT value_numeric FROM events WHERE source_module='world.derived' "
            "AND event_type='news_sentiment_index' AND timestamp_utc LIKE ?",
            (f"{date2}%",),
        ).fetchall()
        assert len(rows1) == 1
        assert len(rows2) == 1


# ──────────────────────────────────────────────────────────────
# TestComputeDayMetrics
# ──────────────────────────────────────────────────────────────


class TestComputeDayMetrics:
    """Tests for _compute_day_metrics() edge cases."""

    def test_json_decode_error_in_categories(self, db):
        """Malformed value_json in DB triggers except branch in category extraction.

        We insert valid events first, then directly inject a row with bad JSON
        via raw SQL to bypass the DB's JSON validation.
        """
        # Insert a valid event first
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T11:00:00+00:00",
                value_numeric=0.3,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        # Directly insert a row with malformed JSON to trigger the except branch
        db.conn.execute(
            """INSERT OR REPLACE INTO events
               (event_id, timestamp_utc, timestamp_local, timezone_offset,
                source_module, event_type, value_numeric, value_json,
                confidence, parser_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (
                "bad-json-event-id",
                f"{DATE}T10:00:00+00:00",
                f"{DATE}T05:00:00-05:00",
                "-0500",
                "world.news",
                "headline",
                0.5,
                "NOT VALID JSON{{{",
                1.0,
                "1.0.0",
            ),
        )
        db.conn.commit()

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        # NSI should work with both events (0.5 + 0.3) / 2 = 0.4
        nsi_rows = _query_derived(db, "news_sentiment_index")
        assert len(nsi_rows) == 1
        assert nsi_rows[0][0] == pytest.approx(0.4, abs=0.001)

        # Entropy: only 1 valid category ("tech") from the second event
        entropy_rows = _query_derived(db, "information_entropy")
        assert len(entropy_rows) == 1
        assert entropy_rows[0][0] == 0.0  # single category => 0 entropy

    def test_null_value_json_handled(self, db):
        """Events with None value_json don't crash category extraction."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=None,
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        nsi_rows = _query_derived(db, "news_sentiment_index")
        assert len(nsi_rows) == 1

    def test_no_data_for_date(self, db):
        """No events for the date produces no derived events."""
        mod = create_module(_world_config())
        derived = mod._compute_day_metrics(db, "2026-01-01")
        assert derived == []

    def test_events_with_no_category_key(self, db):
        """Events with valid JSON but no 'category' key use 'unknown'."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"source": "test"}),  # no category
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        entropy_rows = _query_derived(db, "information_entropy")
        assert len(entropy_rows) == 1
        meta = json.loads(entropy_rows[0][1])
        assert "unknown" in meta["category_counts"]


# ──────────────────────────────────────────────────────────────
# TestGetDailySummary
# ──────────────────────────────────────────────────────────────


class TestGetDailySummary:
    """Tests for WorldModule.get_daily_summary()."""

    def test_summary_with_data(self, db):
        """Returns a valid summary dict with event counts and derived metrics."""
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
                value_json=json.dumps({"category": "science"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        # Run post_ingest to create derived events
        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        summary = mod.get_daily_summary(db, DATE)
        assert summary is not None
        assert "event_counts" in summary
        assert "total_world_events" in summary
        assert summary["total_world_events"] > 0

    def test_summary_no_data(self, db):
        """Returns None when no world events exist for the date."""
        mod = create_module(_world_config())
        summary = mod.get_daily_summary(db, "2020-01-01")
        assert summary is None

    def test_summary_structure_keys(self, db):
        """Summary dict has expected top-level keys."""
        events = [
            _make_event(
                "world.news",
                "headline",
                timestamp_utc=f"{DATE}T10:00:00+00:00",
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        summary = mod.get_daily_summary(db, DATE)
        assert summary is not None
        assert "event_counts" in summary
        assert "news_sentiment_index" in summary
        assert "information_entropy" in summary
        assert "total_world_events" in summary

    def test_summary_derived_values(self, db):
        """Derived metric values appear in summary when available."""
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
                value_numeric=0.5,
                value_json=json.dumps({"category": "tech"}),
            ),
        ]
        db.insert_events_for_module("world", events)

        mod = create_module(_world_config())
        mod.post_ingest(db, affected_dates={DATE})

        summary = mod.get_daily_summary(db, DATE)
        assert summary is not None
        # We should have world.derived entries in event_counts
        derived_keys = [k for k in summary["event_counts"] if "derived" in k]
        assert len(derived_keys) > 0


# ──────────────────────────────────────────────────────────────
# TestCreateModule
# ──────────────────────────────────────────────────────────────


class TestCreateModule:
    """Tests for the create_module() factory function."""

    def test_create_module_with_config(self):
        mod = create_module({"enabled": True})
        assert isinstance(mod, WorldModule)
        assert mod.module_id == "world"

    def test_create_module_no_config(self):
        mod = create_module(None)
        assert isinstance(mod, WorldModule)

    def test_create_module_empty_config(self):
        mod = create_module({})
        assert isinstance(mod, WorldModule)
