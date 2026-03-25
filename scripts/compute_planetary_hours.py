#!/usr/bin/env python3
"""
LifeData V4 — Planetary Hours Calculator
scripts/compute_planetary_hours.py

Computes and stores planetary hours for today using astronomical calculations.
Uses home coordinates from config.yaml and the astral library.

No API keys required — purely deterministic astronomical computation.

Dependencies: pip install astral

Cron: 0 4 * * *  (4 AM daily, before sunrise)
Output: raw/api/planetary/hours_YYYY-MM-DD.json
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "raw", "api", "planetary")

try:
    from astral import LocationInfo
    from astral.sun import sun as astral_sun
except ImportError:
    print("astral not installed — run: pip install astral")
    sys.exit(1)

# Chaldean order of planets
CHALDEAN_ORDER = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]

# Day rulers: the first planetary hour of each day is ruled by the day's planet
DAY_RULERS = {
    0: "Moon",  # Monday
    1: "Mars",  # Tuesday
    2: "Mercury",  # Wednesday
    3: "Jupiter",  # Thursday
    4: "Venus",  # Friday
    5: "Saturn",  # Saturday
    6: "Sun",  # Sunday
}


def compute_planetary_hours(
    lat: float, lon: float, date: datetime, timezone_str: str = "America/Chicago"
) -> list[dict]:
    """Compute all 24 planetary hours for a given date and location.

    Returns list of 24 dicts, each with:
      - hour_number (1-12 day, 1-12 night)
      - is_night (bool)
      - ruling_planet
      - start_time (local ISO)
      - end_time (local ISO)
      - duration_minutes
    """
    tz = ZoneInfo(timezone_str)
    loc = LocationInfo(latitude=lat, longitude=lon, timezone=timezone_str)

    s_today = astral_sun(loc.observer, date=date, tzinfo=tz)
    s_tomorrow = astral_sun(loc.observer, date=date + timedelta(days=1), tzinfo=tz)

    sunrise = s_today["sunrise"]
    sunset = s_today["sunset"]
    next_sunrise = s_tomorrow["sunrise"]

    day_duration = (sunset - sunrise).total_seconds()
    night_duration = (next_sunrise - sunset).total_seconds()

    day_hour_sec = day_duration / 12
    night_hour_sec = night_duration / 12

    # Find starting planet for the day's first hour
    weekday = date.weekday()
    day_ruler = DAY_RULERS[weekday]
    start_idx = CHALDEAN_ORDER.index(day_ruler)

    hours = []

    # Day hours (sunrise to sunset)
    for i in range(12):
        planet_idx = (start_idx + i) % 7
        start = sunrise + timedelta(seconds=i * day_hour_sec)
        end = sunrise + timedelta(seconds=(i + 1) * day_hour_sec)
        hours.append(
            {
                "hour_number": i + 1,
                "is_night": False,
                "ruling_planet": CHALDEAN_ORDER[planet_idx],
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "duration_minutes": round(day_hour_sec / 60, 1),
            }
        )

    # Night hours (sunset to next sunrise)
    for i in range(12):
        planet_idx = (start_idx + 12 + i) % 7
        start = sunset + timedelta(seconds=i * night_hour_sec)
        end = sunset + timedelta(seconds=(i + 1) * night_hour_sec)
        hours.append(
            {
                "hour_number": i + 1,
                "is_night": True,
                "ruling_planet": CHALDEAN_ORDER[planet_idx],
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "duration_minutes": round(night_hour_sec / 60, 1),
            }
        )

    return hours


def load_config() -> dict:
    """Load config.yaml from project root."""
    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    config = load_config()
    oracle_config = config.get("lifedata", {}).get("modules", {}).get("oracle", {})
    tz_name = config.get("lifedata", {}).get("timezone", "America/Chicago")

    lat = oracle_config.get("home_lat", 0.0)
    lon = oracle_config.get("home_lon", 0.0)

    if lat == 0.0 and lon == 0.0:
        print("WARNING: home_lat/home_lon not set in config.yaml oracle section.")
        print("         Planetary hours will be computed for lat=0, lon=0 (equator).")
        print("         Set oracle.home_lat and oracle.home_lon for accurate results.")

    tz = ZoneInfo(tz_name)
    today = datetime.now(tz)
    date_str = today.strftime("%Y-%m-%d")

    print(f"Computing planetary hours for {date_str}")
    print(f"  Location: {lat}, {lon}")
    print(f"  Timezone: {tz_name}")

    hours = compute_planetary_hours(lat, lon, today, tz_name)

    day_ruler = DAY_RULERS[today.weekday()]
    output = {
        "date": date_str,
        "day_ruler": day_ruler,
        "weekday": today.strftime("%A"),
        "sunrise": hours[0]["start_time"],
        "sunset": hours[11]["end_time"],
        "hours": hours,
    }

    filename = f"hours_{date_str}.json"
    output_path = os.path.join(OUTPUT_DIR, filename)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"  Saved: {output_path}")
    print(f"  Day ruler: {day_ruler} ({today.strftime('%A')})")
    print(f"  Sunrise: {hours[0]['start_time']}")
    print(f"  Sunset: {hours[11]['end_time']}")
    print(f"  Day hour: {hours[0]['duration_minutes']} min")
    print(f"  Night hour: {hours[12]['duration_minutes']} min")


if __name__ == "__main__":
    main()
