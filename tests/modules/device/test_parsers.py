"""
Tests for modules/device/parsers.py — battery, screen, charging, bluetooth.
"""

import json

from modules.device.parsers import (
    parse_battery,
    parse_bluetooth,
    parse_charging,
    parse_screen,
)
from tests.conftest import (
    BATTERY_V3_LINES,
    BATTERY_V4_LINES,
    BLUETOOTH_V4_LINES,
    CHARGING_V4_LINES,
    SCREEN_V3_LINES,
    SCREEN_V4_LINES,
)

# ──────────────────────────────────────────────────────────────
# Battery parser
# ──────────────────────────────────────────────────────────────


class TestParseBattery:
    def test_v3_format(self, csv_file_factory):
        path = csv_file_factory("battery_2026.csv", BATTERY_V3_LINES)
        events = parse_battery(path)
        assert len(events) == 2
        assert events[0].source_module == "device.battery"
        assert events[0].event_type == "pulse"
        assert events[0].value_numeric == 85.0

    def test_v4_format(self, csv_file_factory):
        path = csv_file_factory("battery_2026.csv", BATTERY_V4_LINES)
        events = parse_battery(path)
        assert len(events) == 2
        assert events[0].value_numeric == 85.0
        # v4 should have temp and mem in value_json
        data = json.loads(events[0].value_json)
        assert data["temp_c"] == 28.5
        assert data["mem_free_mb"] == 4096

    def test_unresolved_tasker_vars(self, csv_file_factory):
        """v3 %TEMP and %MFREE should be ignored, not stored."""
        path = csv_file_factory("battery_2026.csv", BATTERY_V3_LINES)
        events = parse_battery(path)
        for e in events:
            if e.value_json:
                data = json.loads(e.value_json)
                assert "temp_c" not in data  # %TEMP unresolved

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("battery_2026.csv", [])
        events = parse_battery(path)
        assert events == []

    def test_blank_lines_skipped(self, csv_file_factory):
        lines = ["", "  ", BATTERY_V4_LINES[0], "", BATTERY_V4_LINES[1]]
        path = csv_file_factory("battery_2026.csv", lines)
        events = parse_battery(path)
        assert len(events) == 2

    def test_header_line_skipped(self, csv_file_factory):
        lines = ["epoch,date,time,tz,pct,temp,mem,uptime"] + BATTERY_V4_LINES
        path = csv_file_factory("battery_2026.csv", lines)
        events = parse_battery(path)
        assert len(events) == 2  # header skipped because non-digit epoch

    def test_malformed_battery_pct(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,-0500,NOT_A_NUMBER,28.5,4096,123"]
        path = csv_file_factory("battery_2026.csv", lines)
        events = parse_battery(path)
        assert len(events) == 0  # None battery_pct → skip

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,3-24-26"]
        path = csv_file_factory("battery_2026.csv", lines)
        events = parse_battery(path)
        assert len(events) == 0

    def test_events_are_valid(self, csv_file_factory):
        path = csv_file_factory("battery_2026.csv", BATTERY_V4_LINES)
        events = parse_battery(path)
        for e in events:
            assert e.is_valid, f"Event invalid: {e.validate()}"


# ──────────────────────────────────────────────────────────────
# Screen parser
# ──────────────────────────────────────────────────────────────


class TestParseScreen:
    def test_v3_format(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", SCREEN_V3_LINES)
        events = parse_screen(path)
        assert len(events) == 3
        assert events[0].event_type == "screen_on"
        assert events[1].event_type == "screen_off"

    def test_v4_format(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", SCREEN_V4_LINES)
        events = parse_screen(path)
        assert len(events) == 3
        assert events[0].timezone_offset == "-0500"

    def test_happy_path_10_rows(self, csv_file_factory):
        """10 valid rows should produce 10 events."""
        lines = [
            f"171130{3200 + i * 300},3-24-26,{10 + i // 12}:{(i * 5) % 60:02d},-0500,{'on' if i % 2 == 0 else 'off'},{85 - i}"
            for i in range(10)
        ]
        path = csv_file_factory("screen_2026.csv", lines)
        events = parse_screen(path)
        assert len(events) == 10
        assert all(e.source_module == "device.screen" for e in events)

    def test_truncated_file(self, csv_file_factory):
        """File cut mid-line: complete rows parsed, partial row skipped."""
        lines = SCREEN_V4_LINES + ["1711304400,3-24-26,10:20,-05"]
        path = csv_file_factory("screen_2026.csv", lines)
        events = parse_screen(path)
        assert len(events) >= 3  # the 3 complete rows survive

    def test_zero_byte_file(self, tmp_path):
        """Zero-byte file returns empty list, no exception."""
        path = tmp_path / "screen_2026.csv"
        path.write_text("")
        events = parse_screen(str(path))
        assert events == []

    def test_missing_columns(self, csv_file_factory):
        """Row with fewer columns than expected should be skipped."""
        lines = ["1711303200,3-24-26"]
        path = csv_file_factory("screen_2026.csv", lines)
        events = parse_screen(path)
        assert len(events) == 0

    def test_bad_timestamp(self, csv_file_factory):
        """Non-numeric epoch should skip the row."""
        lines = ["not_a_number,3-24-26,10:00,on,85"]
        path = csv_file_factory("screen_2026.csv", lines)
        events = parse_screen(path)
        assert len(events) == 0

    def test_invalid_state_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,garbage,85"]
        path = csv_file_factory("screen_2026.csv", lines)
        events = parse_screen(path)
        assert len(events) == 0

    def test_battery_pct_stored(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", SCREEN_V3_LINES)
        events = parse_screen(path)
        assert events[0].value_numeric == 85.0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", [])
        assert parse_screen(path) == []

    def test_events_are_valid(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", SCREEN_V4_LINES)
        for e in parse_screen(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Charging parser
# ──────────────────────────────────────────────────────────────


class TestParseCharging:
    def test_charge_start_stop(self, csv_file_factory):
        path = csv_file_factory("charging_2026.csv", CHARGING_V4_LINES)
        events = parse_charging(path)
        assert len(events) == 2
        assert events[0].event_type == "charge_start"
        assert events[0].value_numeric == 45.0
        assert events[1].event_type == "charge_stop"
        assert events[1].value_numeric == 90.0

    def test_invalid_state_skipped(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00,-0500,unknown_state,50"]
        path = csv_file_factory("charging_2026.csv", lines)
        events = parse_charging(path)
        assert len(events) == 0

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200,3-24-26,10:00"]
        path = csv_file_factory("charging_2026.csv", lines)
        events = parse_charging(path)
        assert len(events) == 0

    def test_events_are_valid(self, csv_file_factory):
        path = csv_file_factory("charging_2026.csv", CHARGING_V4_LINES)
        for e in parse_charging(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Bluetooth parser
# ──────────────────────────────────────────────────────────────


class TestParseBluetooth:
    def test_bt_events(self, csv_file_factory):
        path = csv_file_factory("bluetooth_2026.csv", BLUETOOTH_V4_LINES)
        events = parse_bluetooth(path)
        assert len(events) == 2
        assert events[0].source_module == "device.bluetooth"
        assert events[0].event_type == "bt_event"
        assert events[0].value_text == "on"
        assert events[1].value_text == "off"

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("bluetooth_2026.csv", [])
        assert parse_bluetooth(path) == []

    def test_events_are_valid(self, csv_file_factory):
        path = csv_file_factory("bluetooth_2026.csv", BLUETOOTH_V4_LINES)
        for e in parse_bluetooth(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Cross-parser deduplication determinism
# ──────────────────────────────────────────────────────────────


class TestDeduplicationDeterminism:
    """Same CSV input parsed twice must produce identical event_ids."""

    def test_battery_deterministic(self, csv_file_factory):
        path = csv_file_factory("battery_2026.csv", BATTERY_V4_LINES)
        run1 = parse_battery(path)
        run2 = parse_battery(path)
        assert [e.event_id for e in run1] == [e.event_id for e in run2]

    def test_screen_deterministic(self, csv_file_factory):
        path = csv_file_factory("screen_2026.csv", SCREEN_V4_LINES)
        run1 = parse_screen(path)
        run2 = parse_screen(path)
        assert [e.event_id for e in run1] == [e.event_id for e in run2]

    def test_charging_deterministic(self, csv_file_factory):
        path = csv_file_factory("charging_2026.csv", CHARGING_V4_LINES)
        run1 = parse_charging(path)
        run2 = parse_charging(path)
        assert [e.event_id for e in run1] == [e.event_id for e in run2]
