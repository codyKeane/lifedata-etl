#!/usr/bin/env python3
"""
LifeData V4 — GDELT Event Fetcher
scripts/fetch_gdelt.py

Queries the GDELT DOC 2.0 API for high-impact global articles.
GDELT is the world's largest open dataset of news events,
tracking tone, themes, and geographic context.

No API key required. No rate-limit concerns for daily use.

Cron: 0 */6 * * *
Output: raw/api/gdelt/events_YYYY-MM-DD_HH.json
"""

import json
import os
import sys
import time
from datetime import UTC, datetime

import requests

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"

# Queries to run — each returns a different slice of global events
QUERIES = [
    {
        "name": "top_global",
        "params": {
            "query": "theme:GENERAL",
            "mode": "ArtList",
            "maxrecords": "25",
            "format": "json",
            "sort": "ToneDesc",
            "timespan": "24h",
        },
    },
    {
        "name": "conflict",
        "params": {
            "query": "conflict OR crisis OR protest",
            "mode": "ArtList",
            "maxrecords": "15",
            "format": "json",
            "sort": "DateDesc",
            "timespan": "24h",
        },
    },
    {
        "name": "us_domestic",
        "params": {
            "query": "sourcelang:eng domain:reuters.com OR domain:apnews.com",
            "mode": "ArtList",
            "maxrecords": "15",
            "format": "json",
            "sort": "DateDesc",
            "timespan": "24h",
        },
    },
]

# Seconds between API calls to avoid rate limiting
QUERY_DELAY = 3


def fetch_gdelt_events() -> list[dict]:
    """Fetch articles from GDELT DOC 2.0 API across multiple queries."""
    all_articles = []
    seen_urls = set()

    for i, query_def in enumerate(QUERIES):
        name = query_def["name"]
        params = query_def["params"]

        try:
            if i > 0:
                time.sleep(QUERY_DELAY)

            # Retry with exponential backoff for 429s
            resp = None
            for attempt in range(3):
                resp = requests.get(GDELT_DOC_API, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = QUERY_DELAY * (2**attempt)
                    print(f"  [{name}] Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                break
            else:
                print(f"  [{name}] Still rate limited after 3 retries, skipping")
                continue
            data = resp.json()
            articles = data.get("articles", [])
            print(f"  [{name}] {len(articles)} articles")

            for art in articles:
                url = art.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                # GDELT provides tone as a float (negative = negative sentiment)
                tone = art.get("tone", 0.0)
                if isinstance(tone, str):
                    try:
                        tone = float(tone)
                    except ValueError:
                        tone = 0.0

                article = {
                    "title": art.get("title", "").strip(),
                    "url": url,
                    "source": art.get("domain", ""),
                    "source_country": art.get("sourcecountry", ""),
                    "language": art.get("language", ""),
                    "tone": round(tone, 2),
                    "seendate": art.get("seendate", ""),
                    "socialimage": art.get("socialimage", ""),
                    "query_name": name,
                    "fetched_utc": datetime.now(UTC).isoformat(),
                }
                all_articles.append(article)

        except requests.exceptions.RequestException as e:
            print(f"  [{name}] ERROR: {e}")
            continue
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  [{name}] Parse error: {e}")
            continue

    return all_articles


def main():
    now = datetime.now(UTC)

    print("Fetching GDELT events...")
    articles = fetch_gdelt_events()

    if not articles:
        print("No GDELT articles fetched.")
        return

    # Save to raw/api/gdelt/
    out_dir = os.path.join(PROJECT_ROOT, "raw", "api", "gdelt")
    os.makedirs(out_dir, exist_ok=True)

    filename = f"events_{now.strftime('%Y-%m-%d_%H')}.json"
    out_path = os.path.join(out_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(articles)} articles → {out_path}")


if __name__ == "__main__":
    main()
