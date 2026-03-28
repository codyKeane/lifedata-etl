"""Tests for scripts/fetch_rss.py — RSS feed fetcher with VADER sentiment."""

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


class _FeedEntry(dict):
    """Dict subclass that supports both .get() and attribute access like feedparser."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def _make_feed_entries(n: int) -> list:
    """Build *n* fake feedparser entry dicts."""
    return [
        _FeedEntry(
            title=f"Article {i}",
            link=f"https://example.com/{i}",
            published="Mon, 01 Jan 2024 00:00:00 GMT",
            summary=f"Summary {i}",
        )
        for i in range(n)
    ]


def _mock_feedparser_result(entries: list) -> MagicMock:
    result = MagicMock()
    result.entries = entries
    return result


SAMPLE_FEEDS = [
    {"name": "TestFeed", "url": "https://example.com/rss", "category": "tech"},
]


@patch("scripts.fetch_rss.feedparser.parse")
def test_parses_feed_entries(mock_parse):
    """feedparser entries are converted to article dicts."""
    from scripts.fetch_rss import fetch_rss_feeds

    mock_parse.return_value = _mock_feedparser_result(_make_feed_entries(3))

    articles = fetch_rss_feeds(SAMPLE_FEEDS)

    assert len(articles) == 3
    assert articles[0]["title"] == "Article 0"
    assert articles[0]["link"] == "https://example.com/0"
    assert articles[0]["feed_name"] == "TestFeed"
    assert articles[0]["category"] == "tech"
    mock_parse.assert_called_once_with("https://example.com/rss")


@patch("scripts.fetch_rss.feedparser.parse")
def test_sentiment_computed(mock_parse):
    """Each article must carry a numeric 'sentiment' key (VADER compound)."""
    from scripts.fetch_rss import fetch_rss_feeds

    mock_parse.return_value = _mock_feedparser_result(_make_feed_entries(1))

    articles = fetch_rss_feeds(SAMPLE_FEEDS)

    assert len(articles) == 1
    assert "sentiment" in articles[0]
    assert isinstance(articles[0]["sentiment"], float)


@patch("scripts.fetch_rss.feedparser.parse")
def test_malformed_feed_handled(mock_parse):
    """An empty/error feed must not crash — returns zero articles for that feed."""
    from scripts.fetch_rss import fetch_rss_feeds

    # feedparser returns an object with an empty entries list on error
    mock_parse.return_value = _mock_feedparser_result([])

    articles = fetch_rss_feeds(SAMPLE_FEEDS)

    assert articles == []


@patch("scripts.fetch_rss.feedparser.parse")
def test_max_items_per_feed(mock_parse):
    """No more than MAX_ITEMS_PER_FEED (15) articles per feed."""
    from scripts.fetch_rss import MAX_ITEMS_PER_FEED, fetch_rss_feeds

    # Provide 30 entries — only 15 should be kept
    mock_parse.return_value = _mock_feedparser_result(_make_feed_entries(30))

    articles = fetch_rss_feeds(SAMPLE_FEEDS)

    assert len(articles) <= MAX_ITEMS_PER_FEED
    assert len(articles) == 15


@patch("scripts.fetch_rss.feedparser.parse")
def test_skips_unconfigured_url(mock_parse):
    """Feeds with url starting with 'CONFIGURE' are skipped."""
    from scripts.fetch_rss import fetch_rss_feeds

    feeds = [{"name": "Placeholder", "url": "CONFIGURE_ME", "category": "x"}]
    articles = fetch_rss_feeds(feeds)

    assert articles == []
    mock_parse.assert_not_called()


@patch("scripts.fetch_rss.feedparser.parse")
def test_exception_in_feed_does_not_crash(mock_parse):
    """A feed that raises an exception is skipped gracefully."""
    from scripts.fetch_rss import fetch_rss_feeds

    mock_parse.side_effect = Exception("network failure")

    articles = fetch_rss_feeds(SAMPLE_FEEDS)

    assert articles == []


# ---------------------------------------------------------------------------
# Integration test — actually hits RSS endpoints (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_fetch_rss():
    """Integration: fetch real RSS feeds and verify structure."""
    from scripts.fetch_rss import fetch_rss_feeds

    feeds = [
        {
            "name": "BBC",
            "url": "http://feeds.bbci.co.uk/news/rss.xml",
            "category": "news",
        }
    ]
    articles = fetch_rss_feeds(feeds)

    # BBC feed should return at least one article
    assert len(articles) > 0
    first = articles[0]
    assert "title" in first
    assert "sentiment" in first
    assert isinstance(first["sentiment"], float)
