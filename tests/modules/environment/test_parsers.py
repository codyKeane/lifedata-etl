"""
Tests for modules/environment/parsers.py — hourly, geofence, astro,
barometer/light/magnetometer summary parsers.
"""

import json

import pytest

from modules.environment.parsers import (
    parse_astro,
    parse_barometer_summary,
    parse_geofence,
    parse_hourly,
    parse_light_summary,
    parse_magnetometer_summary,
)
from tests.conftest import ASTRO_LINES, GEOFENCE_LINES, HOURLY_LINES

# ──────────────────────────────────────────────────────────────
# Hourly parser
# ──────────────────────────────────────────────────────────────


class TestParseHourly:
    def test_valid_hourly(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", HOURLY_LINES)
        events = parse_hourly(path)
        assert len(events) == 2
        assert events[0].source_module == "environment.hourly"
        assert events[0].event_type == "snapshot"

    def test_temperature_stored(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", HOURLY_LINES)
        events = parse_hourly(path)
        assert events[0].value_numeric == 72.5
        data = json.loads(events[0].value_json)
        assert data["temp_f"] == 72.5
        assert "temp_c" in data

    def test_gps_coords(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", HOURLY_LINES)
        events = parse_hourly(path)
        assert events[0].location_lat == pytest.approx(32.7767, abs=0.001)
        assert events[0].location_lon == pytest.approx(-96.7970, abs=0.001)

    def test_multiline_wifi_ignored(self, csv_file_factory):
        """Multi-line WiFi data after the epoch line should be ignored."""
        lines = [
            "1711303200,3-24-26,10:00,72.5,45,32.77,-96.79,15",
            ">>> CONNECTION <<<",
            "SSID: MyWiFi",
            "BSSID: 00:11:22:33:44:55",
            "1711306800,3-24-26,11:00,74.0,42,32.77,-96.79,12",
        ]
        path = csv_file_factory("hourly_2026.csv", lines)
        events = parse_hourly(path)
        assert len(events) == 2

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,72.5"]
        path = csv_file_factory("hourly_2026.csv", lines)
        events = parse_hourly(path)
        assert len(events) == 0  # < 5 fields → skipped

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", [])
        assert parse_hourly(path) == []

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", HOURLY_LINES)
        for e in parse_hourly(path):
            assert e.is_valid

    def test_deterministic(self, csv_file_factory):
        path = csv_file_factory("hourly_2026.csv", HOURLY_LINES)
        ids1 = [e.event_id for e in parse_hourly(path)]
        ids2 = [e.event_id for e in parse_hourly(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# Geofence parser
# ──────────────────────────────────────────────────────────────


class TestParseGeofence:
    def test_valid_geofence(self, csv_file_factory):
        path = csv_file_factory("geofence_2026.csv", GEOFENCE_LINES)
        events = parse_geofence(path)
        assert len(events) == 2
        assert events[0].source_module == "environment.location"
        assert events[0].event_type == "geofence"

    def test_lat_lon_stored(self, csv_file_factory):
        path = csv_file_factory("geofence_2026.csv", GEOFENCE_LINES)
        events = parse_geofence(path)
        assert events[0].location_lat == pytest.approx(32.7767, abs=0.001)
        assert events[0].location_lon == pytest.approx(-96.7970, abs=0.001)

    def test_accuracy_in_json(self, csv_file_factory):
        path = csv_file_factory("geofence_2026.csv", GEOFENCE_LINES)
        events = parse_geofence(path)
        data = json.loads(events[0].value_json)
        assert data["accuracy_m"] == 15.0

    def test_missing_lat_lon_skipped(self, csv_file_factory):
        lines = ["1711303200,bad,bad,15"]
        path = csv_file_factory("geofence_2026.csv", lines)
        events = parse_geofence(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,32.7767"]
        path = csv_file_factory("geofence_2026.csv", lines)
        events = parse_geofence(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("geofence_2026.csv", [])
        assert parse_geofence(path) == []

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("geofence_2026.csv", GEOFENCE_LINES)
        for e in parse_geofence(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Astro parser
# ──────────────────────────────────────────────────────────────


class TestParseAstro:
    def test_valid_astro(self, csv_file_factory):
        path = csv_file_factory("astro_2026.csv", ASTRO_LINES)
        events = parse_astro(path)
        assert len(events) == 2
        assert events[0].source_module == "environment.astro"
        assert events[0].event_type == "daily"

    def test_moon_data(self, csv_file_factory):
        path = csv_file_factory("astro_2026.csv", ASTRO_LINES)
        events = parse_astro(path)
        assert events[0].value_text == "Waxing Gibbous"
        assert events[0].value_numeric == 85.3
        data = json.loads(events[0].value_json)
        assert data["moon_day"] == 15
        assert data["sun_hours"] == 12.1

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,15"]
        path = csv_file_factory("astro_2026.csv", lines)
        events = parse_astro(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("astro_2026.csv", [])
        assert parse_astro(path) == []

    def test_events_valid(self, csv_file_factory):
        path = csv_file_factory("astro_2026.csv", ASTRO_LINES)
        for e in parse_astro(path):
            assert e.is_valid

    def test_deterministic(self, csv_file_factory):
        path = csv_file_factory("astro_2026.csv", ASTRO_LINES)
        ids1 = [e.event_id for e in parse_astro(path)]
        ids2 = [e.event_id for e in parse_astro(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# Barometer summary parser
# ──────────────────────────────────────────────────────────────


class TestParseBarometerSummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "barometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_pressure_hpa,min_pressure_hpa,"
            "max_pressure_hpa,mean_altitude_m,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,1013.25,1012.80,1013.70,150.5,60\n"
        )
        events = parse_barometer_summary(str(csv))
        assert len(events) == 1
        assert events[0].source_module == "environment.pressure"
        assert events[0].event_type == "local_barometer"
        assert events[0].value_numeric == 1013.25

    def test_timezone_offset_from_row(self, tmp_path):
        csv = tmp_path / "barometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_pressure_hpa,min_pressure_hpa,"
            "max_pressure_hpa,mean_altitude_m,sample_count\n"
            "1711303200,3-24-26,10:00,-0700,1013.25,1012.80,1013.70,150.5,60\n"
        )
        events = parse_barometer_summary(str(csv))
        assert events[0].timezone_offset == "-0700"

    def test_missing_pressure_skipped(self, tmp_path):
        csv = tmp_path / "barometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_pressure_hpa,min_pressure_hpa,"
            "max_pressure_hpa,mean_altitude_m,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,,,,150.5,60\n"
        )
        events = parse_barometer_summary(str(csv))
        assert len(events) == 0

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "barometer_summary.csv"
        csv.write_text("")
        assert parse_barometer_summary(str(csv)) == []

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "barometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_pressure_hpa,min_pressure_hpa,"
            "max_pressure_hpa,mean_altitude_m,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,1013.25,1012.80,1013.70,150.5,60\n"
        )
        for e in parse_barometer_summary(str(csv)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Light summary parser
# ──────────────────────────────────────────────────────────────


class TestParseLightSummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "light_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_lux,min_lux,max_lux,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,350.5,200.0,500.0,60\n"
        )
        events = parse_light_summary(str(csv))
        assert len(events) == 1
        assert events[0].source_module == "environment.light"
        assert events[0].event_type == "lux_reading"
        assert events[0].value_numeric == 350.5

    def test_timezone_offset_from_row(self, tmp_path):
        csv = tmp_path / "light_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_lux,min_lux,max_lux,sample_count\n"
            "1711303200,3-24-26,10:00,+0530,350.5,200.0,500.0,60\n"
        )
        events = parse_light_summary(str(csv))
        assert events[0].timezone_offset == "+0530"

    def test_missing_lux_skipped(self, tmp_path):
        csv = tmp_path / "light_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_lux,min_lux,max_lux,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,,,500.0,60\n"
        )
        events = parse_light_summary(str(csv))
        assert len(events) == 0

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "light_summary.csv"
        csv.write_text("")
        assert parse_light_summary(str(csv)) == []

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "light_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_lux,min_lux,max_lux,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,350.5,200.0,500.0,60\n"
        )
        for e in parse_light_summary(str(csv)):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Magnetometer summary parser
# ──────────────────────────────────────────────────────────────


class TestParseMagnetometerSummary:
    def test_happy_path(self, tmp_path):
        csv = tmp_path / "magnetometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_mag_ut,std_mag_ut,max_mag_ut,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,48.5,2.1,55.0,60\n"
        )
        events = parse_magnetometer_summary(str(csv))
        assert len(events) == 1
        assert events[0].source_module == "environment.emf"
        assert events[0].event_type == "magnetometer"
        assert events[0].value_numeric == 48.5

    def test_timezone_offset_from_row(self, tmp_path):
        csv = tmp_path / "magnetometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_mag_ut,std_mag_ut,max_mag_ut,sample_count\n"
            "1711303200,3-24-26,10:00,-0600,48.5,2.1,55.0,60\n"
        )
        events = parse_magnetometer_summary(str(csv))
        assert events[0].timezone_offset == "-0600"

    def test_missing_mag_skipped(self, tmp_path):
        csv = tmp_path / "magnetometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_mag_ut,std_mag_ut,max_mag_ut,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,,2.1,55.0,60\n"
        )
        events = parse_magnetometer_summary(str(csv))
        assert len(events) == 0

    def test_empty_file(self, tmp_path):
        csv = tmp_path / "magnetometer_summary.csv"
        csv.write_text("")
        assert parse_magnetometer_summary(str(csv)) == []

    def test_events_valid(self, tmp_path):
        csv = tmp_path / "magnetometer_summary.csv"
        csv.write_text(
            "epoch,date,time,timezone_offset,mean_mag_ut,std_mag_ut,max_mag_ut,sample_count\n"
            "1711303200,3-24-26,10:00,-0500,48.5,2.1,55.0,60\n"
        )
        for e in parse_magnetometer_summary(str(csv)):
            assert e.is_valid
