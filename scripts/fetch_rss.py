#!/usr/bin/env python3
"""
LifeData V4 — RSS Feed Fetcher
scripts/fetch_rss.py

Fetches articles from curated RSS feeds defined in config.yaml,
enriches each with VADER sentiment, and saves to raw/api/rss/.

No API key required.

Cron: 0 */4 * * *
Output: raw/api/rss/feeds_YYYY-MM-DD_HH.json
"""

import json
import os
import sys
from datetime import datetime, timezone

import feedparser
import yaml
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Resolve ${ENV_VAR} in config
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)

MAX_ITEMS_PER_FEED = 15


def load_rss_feeds(config_path: str | None = None) -> list[dict]:
    """Load the RSS feed list from config.yaml."""
    if config_path is None:
        config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    feeds = (
        config.get("lifedata", {})
        .get("modules", {})
        .get("world", {})
        .get("rss_feeds", [])
    )
    return feeds


def fetch_rss_feeds(feeds: list[dict]) -> list[dict]:
    """Fetch and enrich articles from all configured RSS feeds."""
    analyzer = SentimentIntensityAnalyzer()
    all_articles = []

    for feed_def in feeds:
        name = feed_def.get("name", "unknown")
        url = feed_def.get("url", "")
        category = feed_def.get("category", "uncategorized")

        if not url or url.startswith("CONFIGURE"):
            continue

        try:
            parsed = feedparser.parse(url)
            entries = parsed.entries[:MAX_ITEMS_PER_FEED]
            print(f"  [{name}] {len(entries)} articles")

            for entry in entries:
                title = entry.get("title", "").strip()
                link = entry.get("link", "")
                published = entry.get("published", "")
                summary = entry.get("summary", "")[:300]

                # Sentiment on title
                sentiment = analyzer.polarity_scores(title)

                article = {
                    "title": title,
                    "link": link,
                    "published": published,
                    "summary": summary,
                    "feed_name": name,
                    "feed_url": url,
                    "category": category,
                    "sentiment": sentiment["compound"],
                    "fetched_utc": datetime.now(timezone.utc).isoformat(),
                }
                all_articles.append(article)

        except Exception as e:
            print(f"  [{name}] ERROR: {e}")
            continue

    return all_articles


def main():
    now = datetime.now(timezone.utc)

    feeds = load_rss_feeds()
    if not feeds:
        print("No RSS feeds configured in config.yaml — nothing to fetch.")
        return

    print(f"Fetching {len(feeds)} RSS feeds...")
    articles = fetch_rss_feeds(feeds)

    if not articles:
        print("No articles fetched.")
        return

    # Save to raw/api/rss/
    out_dir = os.path.join(PROJECT_ROOT, "raw", "api", "rss")
    os.makedirs(out_dir, exist_ok=True)

    filename = f"feeds_{now.strftime('%Y-%m-%d_%H')}.json"
    out_path = os.path.join(out_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(articles)} articles → {out_path}")


if __name__ == "__main__":
    main()
