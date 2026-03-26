"""Tests for scripts/_http.py — retry_get() with exponential backoff."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts._http import retry_get


class TestRetryGet:
    """Unit tests for retry_get()."""

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_success_first_try(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=200)
        resp = retry_get("http://example.com")
        assert resp.status_code == 200
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_retries_on_429(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            MagicMock(status_code=429),
            MagicMock(status_code=429),
            MagicMock(status_code=200),
        ]
        resp = retry_get("http://example.com")
        assert resp.status_code == 200
        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_retries_on_500(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            MagicMock(status_code=500),
            MagicMock(status_code=200),
        ]
        resp = retry_get("http://example.com")
        assert resp.status_code == 200
        assert mock_get.call_count == 2

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_exhausts_retries(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=500)
        resp = retry_get("http://example.com", max_retries=2)
        assert resp.status_code == 500
        assert mock_get.call_count == 3  # initial + 2 retries

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_connection_error_retries_then_raises(self, mock_get, mock_sleep):
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        with pytest.raises(requests.ConnectionError):
            retry_get("http://example.com", max_retries=2)
        assert mock_get.call_count == 3

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_timeout_error_retries(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            requests.Timeout("timed out"),
            MagicMock(status_code=200),
        ]
        resp = retry_get("http://example.com", max_retries=2)
        assert resp.status_code == 200
        assert mock_get.call_count == 2

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_custom_retry_codes(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            MagicMock(status_code=418),
            MagicMock(status_code=200),
        ]
        resp = retry_get("http://example.com", retry_on=(418,))
        assert resp.status_code == 200
        assert mock_get.call_count == 2

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_non_retryable_status_returned_immediately(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=401)
        resp = retry_get("http://example.com")
        assert resp.status_code == 401
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_backoff_sleep_durations(self, mock_get, mock_sleep):
        """Verify sleep is called with backoff_base^attempt for each retry."""
        mock_get.return_value = MagicMock(status_code=503)
        retry_get("http://example.com", max_retries=3, backoff_base=2.0)
        # Attempts: 0 (sleep 2^0=1), 1 (sleep 2^1=2), 2 (sleep 2^2=4), 3 (no sleep)
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(1.0)   # 2.0^0
        mock_sleep.assert_any_call(2.0)   # 2.0^1
        mock_sleep.assert_any_call(4.0)   # 2.0^2

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_headers_forwarded(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=200)
        custom_headers = {"Authorization": "Bearer token123"}
        retry_get("http://example.com", headers=custom_headers)
        mock_get.assert_called_once_with(
            "http://example.com",
            params=None,
            headers=custom_headers,
            timeout=15,
        )

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_params_forwarded(self, mock_get, mock_sleep):
        mock_get.return_value = MagicMock(status_code=200)
        params = {"q": "test", "page": "1"}
        retry_get("http://example.com", params=params)
        mock_get.assert_called_once_with(
            "http://example.com",
            params=params,
            headers=None,
            timeout=15,
        )

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_max_retries_zero(self, mock_get, mock_sleep):
        """With max_retries=0, return the first response even if retryable."""
        mock_get.return_value = MagicMock(status_code=500)
        resp = retry_get("http://example.com", max_retries=0)
        assert resp.status_code == 500
        assert mock_get.call_count == 1
        mock_sleep.assert_not_called()

    @patch("scripts._http.time.sleep")
    @patch("scripts._http.requests.get")
    def test_connection_error_then_success(self, mock_get, mock_sleep):
        """A transient connection error followed by success should recover."""
        mock_get.side_effect = [
            requests.ConnectionError("reset"),
            MagicMock(status_code=200),
        ]
        resp = retry_get("http://example.com", max_retries=2)
        assert resp.status_code == 200
        assert mock_get.call_count == 2
