#!/usr/bin/env python3
"""
LifeData V4 — NewsAPI Headline Fetcher
scripts/fetch_news.py

Pulls top headlines from NewsAPI.org across 5 categories,
enriches each with VADER sentiment.

API: https://newsapi.org/v2/top-headlines
Free tier: 100 requests/day
Usage: 5 categories × 4 times/day = 20 req/day (well within limit)

Cron: 0 */4 * * *
Output: raw/api/news/headlines_YYYY-MM-DD_HH.json
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)

CATEGORIES = ["technology", "science", "health", "business", "general"]
NEWSAPI_URL = "https://newsapi.org/v2/top-headlines"
PAGE_SIZE = 10


def fetch_news(api_key: str, country: str = "us") -> list[dict]:
    """Fetch top headlines across categories with sentiment analysis."""
    if not api_key:
        print("NEWS_API_KEY not set — skipping NewsAPI fetch.")
        return []

    analyzer = SentimentIntensityAnalyzer()
    all_articles = []

    for category in CATEGORIES:
        try:
            resp = requests.get(
                NEWSAPI_URL,
                params={
                    "apiKey": api_key,
                    "country": country,
                    "category": category,
                    "pageSize": PAGE_SIZE,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "ok":
                print(f"  [{category}] API error: {data.get('message', 'unknown')}")
                continue

            articles = data.get("articles", [])
            print(f"  [{category}] {len(articles)} headlines")

            for a in articles:
                title = a.get("title", "") or ""
                description = a.get("description", "") or ""
                sentiment = analyzer.polarity_scores(title)

                article = {
                    "title": title.strip(),
                    "description": description[:300],
                    "source_name": (a.get("source") or {}).get("name", ""),
                    "url": a.get("url", ""),
                    "published_at": a.get("publishedAt", ""),
                    "category": category,
                    "sentiment": sentiment["compound"],
                    "sentiment_detail": {
                        "pos": sentiment["pos"],
                        "neg": sentiment["neg"],
                        "neu": sentiment["neu"],
                    },
                    "fetched_utc": datetime.now(timezone.utc).isoformat(),
                }
                all_articles.append(article)

        except requests.exceptions.RequestException as e:
            print(f"  [{category}] ERROR: {e}")
            continue

    return all_articles


def main():
    now = datetime.now(timezone.utc)
    api_key = os.environ.get("NEWS_API_KEY", "")

    print("Fetching NewsAPI headlines...")
    articles = fetch_news(api_key)

    if not articles:
        print("No news articles fetched (key may be missing).")
        return

    # Save to raw/api/news/
    out_dir = os.path.join(PROJECT_ROOT, "raw", "api", "news")
    os.makedirs(out_dir, exist_ok=True)

    filename = f"headlines_{now.strftime('%Y-%m-%d_%H')}.json"
    out_path = os.path.join(out_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(articles)} articles → {out_path}")


if __name__ == "__main__":
    main()
