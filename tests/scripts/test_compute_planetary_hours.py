"""Tests for scripts/compute_planetary_hours.py — planetary hours calculator."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

# Ensure scripts directory is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from compute_planetary_hours import (
    CHALDEAN_ORDER,
    DAY_RULERS,
    compute_planetary_hours,
)

# Known dates for deterministic testing
# 2026-03-20 is a Friday (weekday=4 -> Venus)
# 2026-03-18 is a Wednesday (weekday=2 -> Mercury)
# 2026-03-22 is a Sunday (weekday=6 -> Sun)

LAT = 32.7767  # Dallas, TX
LON = -96.7970


class TestReturns24Hours:
    def test_returns_24_hours(self):
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(LAT, LON, date)
        assert len(hours) == 24


class TestDayRulerWednesday:
    def test_day_ruler_wednesday_is_mercury(self):
        # 2026-03-18 is a Wednesday
        date = datetime(2026, 3, 18)
        assert date.weekday() == 2  # Confirm Wednesday
        hours = compute_planetary_hours(LAT, LON, date)
        assert hours[0]["ruling_planet"] == "Mercury"


class TestDayRulerSunday:
    def test_day_ruler_sunday_is_sun(self):
        # 2026-03-22 is a Sunday
        date = datetime(2026, 3, 22)
        assert date.weekday() == 6  # Confirm Sunday
        hours = compute_planetary_hours(LAT, LON, date)
        assert hours[0]["ruling_planet"] == "Sun"


class TestHourDurationsSumTo24h:
    def test_hour_durations_sum_to_24h(self):
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(LAT, LON, date)
        total_minutes = sum(h["duration_minutes"] for h in hours)
        # Day hours all same duration, night hours all same duration
        # 12 * day_dur + 12 * night_dur should approximate 1440
        assert abs(total_minutes - 1440) < 5.0, (
            f"Total duration {total_minutes} min is not close to 1440"
        )


class TestFirst12AreDayHours:
    def test_first_12_are_day_hours(self):
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(LAT, LON, date)
        for i in range(12):
            assert hours[i]["is_night"] is False, f"Hour {i} should be a day hour"


class TestLast12AreNightHours:
    def test_last_12_are_night_hours(self):
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(LAT, LON, date)
        for i in range(12, 24):
            assert hours[i]["is_night"] is True, f"Hour {i} should be a night hour"


class TestEquatorRoughlyEqual:
    def test_equator_roughly_equal(self):
        """At equator near equinox, day and night hours should be roughly equal."""
        # 2026-03-20 is near the vernal equinox
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(0.0, 0.0, date, timezone_str="UTC")
        day_total = sum(h["duration_minutes"] for h in hours[:12])
        night_total = sum(h["duration_minutes"] for h in hours[12:])
        ratio = day_total / night_total if night_total else 0
        assert 0.8 < ratio < 1.2, (
            f"Day/night ratio {ratio:.3f} exceeds 20% threshold "
            f"(day={day_total:.1f}, night={night_total:.1f})"
        )


class TestZeroCoordinatesStillComputes:
    def test_zero_coordinates_still_computes(self):
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(0.0, 0.0, date, timezone_str="UTC")
        assert len(hours) == 24
        # Each hour has required keys
        for h in hours:
            assert "hour_number" in h
            assert "is_night" in h
            assert "ruling_planet" in h
            assert "start_time" in h
            assert "end_time" in h
            assert "duration_minutes" in h


class TestChaldeanOrderCycles:
    def test_chaldean_order_cycles(self):
        """Consecutive hours should cycle through the Chaldean order."""
        date = datetime(2026, 3, 20)
        hours = compute_planetary_hours(LAT, LON, date)

        # Get the starting index for the first hour's planet
        first_planet = hours[0]["ruling_planet"]
        start_idx = CHALDEAN_ORDER.index(first_planet)

        for i, h in enumerate(hours):
            expected_planet = CHALDEAN_ORDER[(start_idx + i) % 7]
            assert h["ruling_planet"] == expected_planet, (
                f"Hour {i}: expected {expected_planet}, got {h['ruling_planet']}"
            )
