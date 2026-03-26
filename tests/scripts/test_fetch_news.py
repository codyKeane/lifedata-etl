"""Tests for scripts/fetch_news.py — NewsAPI headline fetcher."""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.fetch_news import CATEGORIES, fetch_news


def _make_newsapi_response(articles=None, status="ok"):
    """Build a mock response matching NewsAPI JSON shape."""
    if articles is None:
        articles = [
            {
                "title": "Tech breakthrough announced",
                "description": "A major advance in AI research was published today.",
                "source": {"name": "TechNews"},
                "url": "https://example.com/article1",
                "publishedAt": "2026-03-25T12:00:00Z",
            },
            {
                "title": "Markets rally on optimism",
                "description": "Stocks rose sharply.",
                "source": {"name": "FinanceDaily"},
                "url": "https://example.com/article2",
                "publishedAt": "2026-03-25T13:00:00Z",
            },
        ]
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status": status, "articles": articles}
    resp.raise_for_status.return_value = None
    return resp


class TestFetchNews:
    """Unit tests for fetch_news()."""

    @patch("scripts.fetch_news.retry_get")
    def test_parses_newsapi_response(self, mock_get):
        mock_get.return_value = _make_newsapi_response()
        articles = fetch_news("fake-api-key")
        assert len(articles) > 0
        assert all("title" in a for a in articles)
        assert all("category" in a for a in articles)

    @patch("scripts.fetch_news.retry_get")
    def test_sentiment_attached(self, mock_get):
        mock_get.return_value = _make_newsapi_response()
        articles = fetch_news("fake-api-key")
        for a in articles:
            assert "sentiment" in a, "Missing 'sentiment' key"
            assert "sentiment_detail" in a, "Missing 'sentiment_detail' key"
            assert isinstance(a["sentiment"], float)
            detail = a["sentiment_detail"]
            assert "pos" in detail
            assert "neg" in detail
            assert "neu" in detail

    @patch("scripts.fetch_news.retry_get")
    def test_five_categories_fetched(self, mock_get):
        """retry_get should be called once per category (5 times)."""
        mock_get.return_value = _make_newsapi_response()
        fetch_news("fake-api-key")
        assert mock_get.call_count == len(CATEGORIES)
        assert mock_get.call_count == 5

    @patch("scripts.fetch_news.retry_get")
    def test_api_error_status_handled(self, mock_get):
        """A non-ok status in the JSON body should skip that category gracefully."""
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"status": "error", "message": "apiKeyInvalid"}
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        articles = fetch_news("bad-key")
        assert articles == []

    @patch("scripts.fetch_news.retry_get")
    def test_http_error_handled(self, mock_get):
        """A 401 HTTP error should be caught and not crash."""
        resp = MagicMock(status_code=401)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
        mock_get.return_value = resp
        articles = fetch_news("bad-key")
        assert articles == []

    def test_missing_api_key_returns_empty(self):
        """An empty API key should return [] without making any HTTP calls."""
        articles = fetch_news("")
        assert articles == []

    @patch("scripts.fetch_news.retry_get")
    def test_articles_have_required_fields(self, mock_get):
        mock_get.return_value = _make_newsapi_response()
        articles = fetch_news("fake-api-key")
        required_fields = {
            "title", "description", "source_name", "url",
            "published_at", "category", "sentiment",
            "sentiment_detail", "fetched_utc",
        }
        for a in articles:
            assert required_fields.issubset(a.keys()), (
                f"Missing fields: {required_fields - a.keys()}"
            )

    @patch("scripts.fetch_news.retry_get")
    def test_null_title_handled(self, mock_get):
        """Articles with None title should not crash sentiment analysis."""
        mock_get.return_value = _make_newsapi_response(
            articles=[{"title": None, "description": None, "source": None, "url": "", "publishedAt": ""}]
        )
        articles = fetch_news("fake-api-key")
        assert len(articles) > 0
        assert articles[0]["title"] == ""


@pytest.mark.integration
class TestFetchNewsIntegration:
    """Live API integration tests — skipped if NEWS_API_KEY is not set."""

    @pytest.fixture(autouse=True)
    def _require_api_key(self):
        key = os.environ.get("NEWS_API_KEY", "")
        if not key:
            pytest.skip("NEWS_API_KEY not set — skipping integration test")
        self.api_key = key

    def test_live_newsapi_fetch(self):
        """Fetch real headlines from NewsAPI and validate structure."""
        articles = fetch_news(self.api_key)
        assert isinstance(articles, list)
        assert len(articles) > 0, "Expected at least one article from live API"
        first = articles[0]
        assert "title" in first
        assert "sentiment" in first
        assert isinstance(first["sentiment"], float)
