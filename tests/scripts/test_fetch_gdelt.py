"""Tests for scripts/fetch_gdelt.py — GDELT DOC 2.0 API fetcher."""

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gdelt_response(articles: list[dict], status: int = 200) -> MagicMock:
    """Build a mock requests.Response with a GDELT-shaped JSON body."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"articles": articles}
    resp.raise_for_status = MagicMock()
    if status >= 400:
        import requests

        resp.raise_for_status.side_effect = requests.HTTPError(
            response=resp
        )
    return resp


def _make_articles(n: int, url_prefix: str = "https://example.com/") -> list[dict]:
    return [
        {
            "title": f"Article {i}",
            "url": f"{url_prefix}{i}",
            "domain": "example.com",
            "sourcecountry": "US",
            "language": "English",
            "tone": -2.5 + i,
            "seendate": "20240101T000000Z",
            "socialimage": "",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@patch("scripts.fetch_gdelt.time.sleep")  # skip real delays
@patch("scripts.fetch_gdelt.requests.get")
def test_parses_gdelt_response(mock_get, _mock_sleep):
    """Valid GDELT JSON with articles is parsed correctly."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    mock_get.return_value = _gdelt_response(_make_articles(3))

    articles = fetch_gdelt_events()

    assert len(articles) >= 3
    first = articles[0]
    assert "title" in first
    assert "url" in first
    assert "query_name" in first
    assert "fetched_utc" in first


@patch("scripts.fetch_gdelt.time.sleep")
@patch("scripts.fetch_gdelt.requests.get")
def test_deduplicates_by_url(mock_get, _mock_sleep):
    """Articles with the same URL across queries are deduplicated."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    # All three queries return the same 2 articles (same URLs)
    shared = _make_articles(2)
    mock_get.return_value = _gdelt_response(shared)

    articles = fetch_gdelt_events()

    urls = [a["url"] for a in articles]
    assert len(urls) == len(set(urls)), "Duplicate URLs found in output"
    # Only 2 unique URLs despite 3 query batches
    assert len(articles) == 2


@patch("scripts.fetch_gdelt.time.sleep")
@patch("scripts.fetch_gdelt.requests.get")
def test_tone_parsed(mock_get, _mock_sleep):
    """Tone field is converted to a float."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    arts = [
        {
            "title": "Test",
            "url": "https://a.com/1",
            "domain": "a.com",
            "tone": "-3.14",  # string tone — should be parsed
            "seendate": "",
            "sourcecountry": "",
            "language": "",
            "socialimage": "",
        }
    ]
    mock_get.return_value = _gdelt_response(arts)

    articles = fetch_gdelt_events()

    tones = [a["tone"] for a in articles if a["url"] == "https://a.com/1"]
    assert len(tones) >= 1
    assert isinstance(tones[0], float)
    assert tones[0] == pytest.approx(-3.14, abs=0.01)


@patch("scripts.fetch_gdelt.time.sleep")
@patch("scripts.fetch_gdelt.requests.get")
def test_three_query_profiles(mock_get, _mock_sleep):
    """requests.get is called at least 3 times (one per QUERIES entry)."""
    from scripts.fetch_gdelt import QUERIES, fetch_gdelt_events

    mock_get.return_value = _gdelt_response([])

    fetch_gdelt_events()

    assert mock_get.call_count >= len(QUERIES)


@patch("scripts.fetch_gdelt.time.sleep")
@patch("scripts.fetch_gdelt.requests.get")
def test_retry_on_rate_limit(mock_get, mock_sleep):
    """A 429 triggers retry; eventual 200 succeeds."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    rate_limited = MagicMock()
    rate_limited.status_code = 429

    ok = _gdelt_response(_make_articles(1, url_prefix="https://retry.com/"))

    # First query: 429 then 200; remaining queries: 200 immediately
    mock_get.side_effect = [rate_limited, ok, ok, ok, ok, ok]

    articles = fetch_gdelt_events()

    # Should have retried (sleep called for backoff, beyond just QUERY_DELAY)
    assert mock_get.call_count >= 4  # at least one retry + 3 queries


@patch("scripts.fetch_gdelt.time.sleep")
@patch("scripts.fetch_gdelt.requests.get")
def test_empty_response_yields_empty_list(mock_get, _mock_sleep):
    """All queries returning no articles yields an empty list."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    mock_get.return_value = _gdelt_response([])

    articles = fetch_gdelt_events()

    assert articles == []


# ---------------------------------------------------------------------------
# Integration test — actually hits GDELT (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_gdelt_fetch():
    """Integration: fetch real GDELT articles."""
    from scripts.fetch_gdelt import fetch_gdelt_events

    articles = fetch_gdelt_events()

    # GDELT should return at least something
    assert isinstance(articles, list)
    if articles:
        first = articles[0]
        assert "title" in first
        assert "tone" in first
        assert isinstance(first["tone"], float)
