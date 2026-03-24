#!/usr/bin/env python3
"""
LifeData V4 — Market Data Fetcher
scripts/fetch_markets.py

Pulls daily market indicators:
  - Bitcoin: CoinGecko free API (no key)
  - Gas prices: EIA API (free key, graceful skip if missing)

Cron: 0 18 * * 1-5  (6 PM weekdays, after market close)
Output: raw/api/markets/markets_YYYY-MM-DD.json
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

# Project root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=False)

COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
EIA_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"


def fetch_bitcoin() -> dict | None:
    """Fetch Bitcoin price and 24h change from CoinGecko (no key)."""
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "ids": "bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        btc = data.get("bitcoin", {})
        price = btc.get("usd")
        change = btc.get("usd_24h_change")

        if price is not None:
            result = {
                "indicator": "bitcoin",
                "value_usd": round(price, 2),
                "change_24h_pct": round(change, 2) if change is not None else None,
                "fetched_utc": datetime.now(timezone.utc).isoformat(),
            }
            print(f"  [Bitcoin] ${result['value_usd']:,.2f} ({result['change_24h_pct']}%)")
            return result
    except Exception as e:
        print(f"  [Bitcoin] ERROR: {e}")
    return None


def fetch_gas_price(api_key: str) -> dict | None:
    """Fetch average US gas price from EIA (requires free key)."""
    if not api_key:
        print("  [Gas] Skipped — EIA_API_KEY not set")
        return None

    try:
        resp = requests.get(
            EIA_URL,
            params={
                "api_key": api_key,
                "frequency": "weekly",
                "data[0]": "value",
                "facets[product][]": "EPM0",
                "facets[duoarea][]": "NUS",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": "1",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("response", {}).get("data", [])

        if records:
            rec = records[0]
            value = float(rec.get("value", 0))
            period = rec.get("period", "")
            result = {
                "indicator": "gas_price_avg",
                "value_usd": round(value, 3),
                "period": period,
                "fetched_utc": datetime.now(timezone.utc).isoformat(),
            }
            print(f"  [Gas] ${result['value_usd']}/gal (week of {period})")
            return result
    except Exception as e:
        print(f"  [Gas] ERROR: {e}")
    return None


def main():
    now = datetime.now(timezone.utc)
    eia_key = os.environ.get("EIA_API_KEY", "")

    print("Fetching market data...")
    indicators = []

    btc = fetch_bitcoin()
    if btc:
        indicators.append(btc)

    gas = fetch_gas_price(eia_key)
    if gas:
        indicators.append(gas)

    if not indicators:
        print("No market data fetched.")
        return

    # Save to raw/api/markets/
    out_dir = os.path.join(PROJECT_ROOT, "raw", "api", "markets")
    os.makedirs(out_dir, exist_ok=True)

    filename = f"markets_{now.strftime('%Y-%m-%d')}.json"
    out_path = os.path.join(out_dir, filename)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(indicators, f, indent=2, ensure_ascii=False)

    print(f"Saved {len(indicators)} indicators → {out_path}")


if __name__ == "__main__":
    main()
