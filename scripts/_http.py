"""
LifeData V4 — Shared HTTP Utilities for API Fetcher Scripts
scripts/_http.py

Provides retry_get() with exponential backoff and rate-limit handling.
Prevents API key bans from transient failures or misconfigured cron.
"""

import time

import requests


def retry_get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    max_retries: int = 3,
    backoff_base: float = 2.0,
    retry_on: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Response:
    """HTTP GET with exponential backoff on retryable status codes.

    Args:
        url: Request URL.
        params: Query parameters.
        headers: Request headers.
        timeout: Per-request timeout in seconds.
        max_retries: Maximum number of retry attempts.
        backoff_base: Base for exponential backoff (seconds).
        retry_on: HTTP status codes that trigger a retry.

    Returns:
        The final Response object (may still be an error if retries exhausted).

    Raises:
        requests.RequestException: On connection/timeout errors after all retries.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code not in retry_on:
                return resp
            # Retryable status — back off
            if attempt < max_retries:
                wait = backoff_base ** attempt
                print(f"  HTTP {resp.status_code} from {url[:60]}... retrying in {wait:.0f}s")
                time.sleep(wait)
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries:
                wait = backoff_base ** attempt
                print(f"  Request error: {e} — retrying in {wait:.0f}s")
                time.sleep(wait)

    # Exhausted retries — return last response or raise last exception
    if last_exc is not None:
        raise last_exc
    return resp  # type: ignore[possibly-undefined]
