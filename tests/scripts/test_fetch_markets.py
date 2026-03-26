"""Tests for scripts/fetch_markets.py — market data fetcher."""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.fetch_markets import fetch_bitcoin, fetch_gas_price


def _make_coingecko_response(price=67432.12, change=-1.23):
    """Build a mock CoinGecko response."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "bitcoin": {
            "usd": price,
            "usd_24h_change": change,
        }
    }
    resp.raise_for_status.return_value = None
    return resp


def _make_eia_response(value="3.456", period="2026-03-17"):
    """Build a mock EIA gas price response."""
    resp = MagicMock(status_code=200)
    resp.json.return_value = {
        "response": {
            "data": [
                {"value": value, "period": period}
            ]
        }
    }
    resp.raise_for_status.return_value = None
    return resp


class TestFetchBitcoin:
    """Unit tests for fetch_bitcoin()."""

    @patch("scripts.fetch_markets.retry_get")
    def test_parses_coingecko_response(self, mock_get):
        mock_get.return_value = _make_coingecko_response(price=67432.12, change=-1.23)
        result = fetch_bitcoin()
        assert result is not None
        assert result["indicator"] == "bitcoin"
        assert result["value_usd"] == 67432.12
        assert result["change_24h_pct"] == -1.23
        assert "fetched_utc" in result

    @patch("scripts.fetch_markets.retry_get")
    def test_bitcoin_handles_500_error(self, mock_get):
        resp = MagicMock(status_code=500)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500 Server Error")
        mock_get.return_value = resp
        result = fetch_bitcoin()
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_bitcoin_handles_connection_error(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("No route to host")
        result = fetch_bitcoin()
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_bitcoin_missing_price_returns_none(self, mock_get):
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"bitcoin": {}}
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        result = fetch_bitcoin()
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_bitcoin_none_change_handled(self, mock_get):
        """24h change may be None; should still return result."""
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"bitcoin": {"usd": 50000.0, "usd_24h_change": None}}
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        result = fetch_bitcoin()
        assert result is not None
        assert result["value_usd"] == 50000.0
        assert result["change_24h_pct"] is None


class TestFetchGasPrice:
    """Unit tests for fetch_gas_price()."""

    @patch("scripts.fetch_markets.retry_get")
    def test_parses_eia_response(self, mock_get):
        mock_get.return_value = _make_eia_response(value="3.456", period="2026-03-17")
        result = fetch_gas_price("fake-eia-key")
        assert result is not None
        assert result["indicator"] == "gas_price_avg"
        assert result["value_usd"] == 3.456
        assert result["period"] == "2026-03-17"
        assert "fetched_utc" in result

    def test_gas_price_missing_key_returns_none(self):
        """Empty API key should return None without HTTP calls."""
        result = fetch_gas_price("")
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_gas_price_handles_http_error(self, mock_get):
        resp = MagicMock(status_code=403)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("403 Forbidden")
        mock_get.return_value = resp
        result = fetch_gas_price("bad-key")
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_gas_price_empty_data(self, mock_get):
        """EIA returns valid JSON but empty data array."""
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"response": {"data": []}}
        resp.raise_for_status.return_value = None
        mock_get.return_value = resp
        result = fetch_gas_price("fake-key")
        assert result is None

    @patch("scripts.fetch_markets.retry_get")
    def test_gas_price_params_forwarded(self, mock_get):
        """Verify EIA API key and params are passed to retry_get."""
        mock_get.return_value = _make_eia_response()
        fetch_gas_price("my-eia-key")
        call_kwargs = mock_get.call_args
        assert call_kwargs.kwargs.get("params", {}).get("api_key") == "my-eia-key" or \
               call_kwargs[1].get("params", {}).get("api_key") == "my-eia-key"


@pytest.mark.integration
class TestFetchMarketsIntegration:
    """Live API integration tests."""

    def test_live_bitcoin_fetch(self):
        """Fetch real Bitcoin price from CoinGecko (no key needed)."""
        result = fetch_bitcoin()
        # CoinGecko may rate-limit; skip rather than fail
        if result is None:
            pytest.skip("CoinGecko returned None (possible rate limit)")
        assert result["indicator"] == "bitcoin"
        assert isinstance(result["value_usd"], float)
        assert result["value_usd"] > 0

    def test_live_gas_price_fetch(self):
        """Fetch real gas price from EIA — skipped if key not set."""
        key = os.environ.get("EIA_API_KEY", "")
        if not key:
            pytest.skip("EIA_API_KEY not set — skipping integration test")
        result = fetch_gas_price(key)
        if result is None:
            pytest.skip("EIA returned None (possible API issue)")
        assert result["indicator"] == "gas_price_avg"
        assert isinstance(result["value_usd"], float)
        assert result["value_usd"] > 0
