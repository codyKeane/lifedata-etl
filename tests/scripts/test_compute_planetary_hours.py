"""Tests for scripts/compute_planetary_hours.py — planetary hours calculator,
including main() execution, file I/O, load_config, and edge cases."""

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure scripts directory is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from compute_planetary_hours import (
    CHALDEAN_ORDER,
    compute_planetary_hours,
    load_config,
    main,
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


# ──────────────────────────────────────────────────────────────
# All weekday rulers
# ──────────────────────────────────────────────────────────────


class TestAllDayRulers:
    """Test planetary hour first-hour ruler for every day of the week."""

    @pytest.mark.parametrize(
        "date,expected_ruler",
        [
            (datetime(2026, 3, 16), "Moon"),      # Monday
            (datetime(2026, 3, 17), "Mars"),      # Tuesday
            (datetime(2026, 3, 19), "Jupiter"),   # Thursday
            (datetime(2026, 3, 20), "Venus"),     # Friday
            (datetime(2026, 3, 21), "Saturn"),    # Saturday
        ],
    )
    def test_day_ruler(self, date, expected_ruler):
        hours = compute_planetary_hours(LAT, LON, date)
        assert hours[0]["ruling_planet"] == expected_ruler


# ──────────────────────────────────────────────────────────────
# load_config
# ──────────────────────────────────────────────────────────────


class TestLoadConfig:
    def test_loads_real_config(self):
        """load_config() should return a dict with lifedata key."""
        config = load_config()
        assert isinstance(config, dict)
        assert "lifedata" in config

    def test_loads_timezone(self):
        config = load_config()
        tz = config.get("lifedata", {}).get("timezone", "")
        assert tz  # Non-empty timezone


# ──────────────────────────────────────────────────────────────
# main() — full execution path
# ──────────────────────────────────────────────────────────────


class TestMain:
    def test_main_creates_output_file(self, tmp_path):
        """main() should create a hours_YYYY-MM-DD.json file."""
        import compute_planetary_hours as cph

        config = {
            "lifedata": {
                "timezone": "America/Chicago",
                "modules": {
                    "oracle": {"home_lat": LAT, "home_lon": LON},
                },
            },
        }

        with patch.object(cph, "OUTPUT_DIR", str(tmp_path)):
            with patch.object(cph, "load_config", return_value=config):
                main()

        # Should have created exactly one JSON file
        json_files = list(tmp_path.glob("hours_*.json"))
        assert len(json_files) == 1

        data = json.loads(json_files[0].read_text())
        assert "date" in data
        assert "day_ruler" in data
        assert "hours" in data
        assert len(data["hours"]) == 24

    def test_main_warns_zero_coordinates(self, tmp_path, capsys):
        """main() should warn when lat/lon are 0.0 (not configured)."""
        import compute_planetary_hours as cph

        config = {
            "lifedata": {
                "timezone": "UTC",
                "modules": {
                    "oracle": {"home_lat": 0.0, "home_lon": 0.0},
                },
            },
        }

        with patch.object(cph, "OUTPUT_DIR", str(tmp_path)):
            with patch.object(cph, "load_config", return_value=config):
                main()

        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "home_lat" in captured.out

    def test_main_default_coordinates(self, tmp_path):
        """main() should use defaults when oracle config is missing."""
        import compute_planetary_hours as cph

        config = {
            "lifedata": {
                "timezone": "UTC",
                "modules": {},
            },
        }

        with patch.object(cph, "OUTPUT_DIR", str(tmp_path)):
            with patch.object(cph, "load_config", return_value=config):
                main()

        json_files = list(tmp_path.glob("hours_*.json"))
        assert len(json_files) == 1


# ──────────────────────────────────────────────────────────────
# High latitude — extreme day/night durations
# ──────────────────────────────────────────────────────────────


class TestHighLatitude:
    def test_high_latitude_computes(self):
        """Planetary hours should compute even at high latitudes (e.g. Oslo)."""
        # Summer solstice in Oslo — very long days
        date = datetime(2026, 6, 21)
        hours = compute_planetary_hours(59.9139, 10.7522, date, "Europe/Oslo")
        assert len(hours) == 24
        # Day hours should be much longer than night hours
        day_dur = hours[0]["duration_minutes"]
        night_dur = hours[12]["duration_minutes"]
        assert day_dur > night_dur

    def test_southern_hemisphere(self):
        """Winter in southern hemisphere — short days."""
        date = datetime(2026, 6, 21)
        hours = compute_planetary_hours(-33.8688, 151.2093, date, "Australia/Sydney")
        assert len(hours) == 24
        # Winter — night hours longer than day hours
        day_dur = hours[0]["duration_minutes"]
        night_dur = hours[12]["duration_minutes"]
        assert night_dur > day_dur
