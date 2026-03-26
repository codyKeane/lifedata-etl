#!/usr/bin/env python3
"""
LifeData V4 — Schumann Resonance Fetcher
scripts/fetch_schumann.py

Attempts to pull Schumann resonance data from available public sources.
Priority: HeartMath GCMS > secondary sources.

This is inherently fragile — sources go offline, change formats, etc.
The script is designed to fail gracefully: log the failure, emit no data,
and try again next cycle.

No API keys required.

Cron: 0 */1 * * *  (hourly)
Output: raw/api/schumann/schumann_YYYY-MM-DD_HH.json
"""

import json
import os
import re
import sys
from datetime import UTC, datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "raw", "api", "schumann")

# Attempt to import requests; skip gracefully if unavailable
try:
    import requests  # noqa: F401 — import probe for availability
except ImportError:
    print("requests not installed — cannot fetch Schumann data.")
    sys.exit(0)

from scripts._http import retry_get

SOURCES = [
    {
        "name": "heartmath_gcms",
        "url": "https://www.heartmath.org/research/global-coherence/gcms-live-data/",
    },
    {
        "name": "spaceweatherlive",
        "url": "https://www.spaceweatherlive.com/",
    },
]


def parse_heartmath(resp) -> dict | None:
    """Extract Schumann fundamental frequency from HeartMath page.

    Looks for spectral power data or summary statistics in the HTML.
    Returns dict with fundamental_hz and amplitude if found.
    """
    text = resp.text
    # Look for frequency data patterns in the page
    # HeartMath often embeds data in JavaScript or data attributes
    # This is best-effort parsing — page structure may change

    # Pattern: look for numbers near "7.83" or "Schumann" in the text
    freq_pattern = re.findall(r"(\d+(?:\.\d+)?)\s*(?:Hz|hz)", text)
    if freq_pattern:
        for freq_str in freq_pattern:
            freq = float(freq_str)
            # Schumann fundamental is typically 7.0-8.5 Hz
            if 7.0 <= freq <= 8.5:
                return {
                    "fundamental_hz": round(freq, 4),
                    "amplitude": None,
                    "q_factor": None,
                    "harmonics": [],
                    "quality": "degraded",
                }

    return None


def fetch_schumann() -> dict | None:
    """Try each source in priority order."""
    for source in SOURCES:
        try:
            resp = retry_get(
                source["url"],
                timeout=15,
                headers={"User-Agent": "LifeData/4.0 (personal research)"},
            )
            if resp.status_code != 200:
                print(f"  {source['name']}: HTTP {resp.status_code}")
                continue

            if source["name"] == "heartmath_gcms":
                data = parse_heartmath(resp)
                if data:
                    data["source"] = source["name"]
                    data["fetched_utc"] = datetime.now(UTC).isoformat()
                    return data

        except Exception as e:
            print(f"  {source['name']} failed: {e}")
            continue

    return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now = datetime.now(UTC)
    print(f"Fetching Schumann resonance data at {now.isoformat()}")

    data = fetch_schumann()

    if data is None:
        print("  No Schumann data available from any source.")
        print("  This is expected — public sources are unreliable.")
        return

    filename = f"schumann_{now.strftime('%Y-%m-%d_%H')}.json"
    output_path = os.path.join(OUTPUT_DIR, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"  Saved: {output_path}")
    print(f"  Fundamental: {data.get('fundamental_hz')} Hz")
    print(f"  Source: {data.get('source')}")


if __name__ == "__main__":
    main()
