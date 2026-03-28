"""Tests for scripts/fetch_schumann.py — Schumann resonance fetcher."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(text: str, status_code: int = 200) -> SimpleNamespace:
    """Build a minimal object that quacks like requests.Response."""
    return SimpleNamespace(text=text, status_code=status_code)


# ---------------------------------------------------------------------------
# parse_heartmath tests
# ---------------------------------------------------------------------------


def test_extracts_decimal_frequency():
    """Regex captures decimal frequency like '7.83 Hz'."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("<p>Current reading: 7.83 Hz peak</p>")
    result = parse_heartmath(resp)

    assert result is not None
    assert result["fundamental_hz"] == pytest.approx(7.83, abs=0.001)


def test_extracts_integer_frequency():
    """Regex captures integer frequency like '8 Hz' (the regex fix)."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("<p>Detected 8 Hz resonance</p>")
    result = parse_heartmath(resp)

    assert result is not None
    assert result["fundamental_hz"] == pytest.approx(8.0, abs=0.001)


def test_frequency_in_range():
    """Only frequencies between 7.0 and 8.5 Hz are accepted."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("<div>7.50 Hz measured today</div>")
    result = parse_heartmath(resp)

    assert result is not None
    assert 7.0 <= result["fundamental_hz"] <= 8.5


def test_no_frequency_returns_none():
    """HTML without any Hz data returns None."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("<html><body>No resonance data here</body></html>")
    result = parse_heartmath(resp)

    assert result is None


def test_out_of_range_rejected():
    """Frequency outside 7.0-8.5 Hz range is rejected."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("<p>Signal at 100.5 Hz detected</p>")
    result = parse_heartmath(resp)

    assert result is None


def test_multiple_frequencies_picks_valid():
    """When multiple Hz values appear, the first in-range one is returned."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response(
        "<p>Noise at 50 Hz, Schumann at 7.83 Hz, harmonic at 14.3 Hz</p>"
    )
    result = parse_heartmath(resp)

    assert result is not None
    assert result["fundamental_hz"] == pytest.approx(7.83, abs=0.001)


def test_result_structure():
    """Returned dict has the expected keys."""
    from scripts.fetch_schumann import parse_heartmath

    resp = _fake_response("Reading: 7.83 Hz")
    result = parse_heartmath(resp)

    assert result is not None
    assert set(result.keys()) == {
        "fundamental_hz",
        "amplitude",
        "q_factor",
        "harmonics",
        "quality",
    }
    assert result["quality"] == "degraded"
    assert result["harmonics"] == []


# ---------------------------------------------------------------------------
# fetch_schumann tests
# ---------------------------------------------------------------------------


@patch("scripts.fetch_schumann.retry_get")
def test_fetch_schumann_returns_data_on_success(mock_retry_get):
    """Successful HTTP 200 with valid Hz data returns a dict."""
    from scripts.fetch_schumann import fetch_schumann

    mock_retry_get.return_value = _fake_response(
        "<p>Current: 7.83 Hz</p>", status_code=200
    )

    result = fetch_schumann()

    assert result is not None
    assert result["fundamental_hz"] == pytest.approx(7.83, abs=0.001)
    assert result["source"] == "heartmath_gcms"
    assert "fetched_utc" in result


@patch("scripts.fetch_schumann.retry_get")
def test_fetch_schumann_returns_none_on_failure(mock_retry_get):
    """HTTP 500 from all sources returns None."""
    from scripts.fetch_schumann import fetch_schumann

    mock_retry_get.return_value = _fake_response("", status_code=500)

    result = fetch_schumann()

    assert result is None


@patch("scripts.fetch_schumann.retry_get")
def test_fetch_schumann_handles_exception(mock_retry_get):
    """An exception from retry_get is caught gracefully."""
    from scripts.fetch_schumann import fetch_schumann

    mock_retry_get.side_effect = ConnectionError("network down")

    result = fetch_schumann()

    assert result is None


# ---------------------------------------------------------------------------
# Integration test — actually hits live endpoints (skipped by default)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_schumann_fetch():
    """Integration: attempt real Schumann resonance fetch.

    This may return None if sources are down — that is acceptable.
    We only verify the return type and structure if data is found.
    """
    from scripts.fetch_schumann import fetch_schumann

    result = fetch_schumann()

    # Result is either None (source unavailable) or a dict
    assert result is None or isinstance(result, dict)
    if result is not None:
        assert "fundamental_hz" in result
        assert 7.0 <= result["fundamental_hz"] <= 8.5
        assert "source" in result
