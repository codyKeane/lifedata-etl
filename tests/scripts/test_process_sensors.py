"""Tests for scripts/process_sensors.py — sensor logger pre-processor."""

import math
import os
import sys
from pathlib import Path

import pytest

# Ensure scripts directory is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from process_sensors import (
    classify_activity,
    find_sessions,
    ns_to_epoch_sec,
    ns_to_window_key,
    process_accelerometer,
    process_barometer,
    process_light,
    process_pedometer,
    process_session,
    safe_float,
    safe_int,
)

# ──────────────────────────────────────────────────────────────
# Utility function tests
# ──────────────────────────────────────────────────────────────

# Base nanosecond timestamp: 2025-03-20 10:00:00 UTC = 1742475600 epoch sec
BASE_NS = 1742475600_000_000_000
BASE_EPOCH = 1742475600.0


class TestNsToEpochSec:
    def test_conversion(self):
        assert ns_to_epoch_sec(BASE_NS) == BASE_EPOCH

    def test_zero(self):
        assert ns_to_epoch_sec(0) == 0.0


class TestNsToWindowKey:
    def test_5min_bucket(self):
        # BASE_EPOCH = 1742475600 which is divisible by 300
        assert ns_to_window_key(BASE_NS, 5) == 1742475600

    def test_5min_bucket_mid_window(self):
        # 1742475600 + 150 seconds = mid-window, should still floor to 1742475600
        mid_ns = (1742475600 + 150) * 1_000_000_000
        assert ns_to_window_key(mid_ns, 5) == 1742475600

    def test_5min_bucket_next_window(self):
        # 1742475600 + 300 seconds = next window boundary
        next_ns = (1742475600 + 300) * 1_000_000_000
        assert ns_to_window_key(next_ns, 5) == 1742475900


class TestClassifyActivity:
    def test_stationary(self):
        assert classify_activity(0.1) == "stationary"
        assert classify_activity(0.29) == "stationary"

    def test_walking(self):
        assert classify_activity(0.3) == "walking"
        assert classify_activity(1.0) == "walking"
        assert classify_activity(1.49) == "walking"

    def test_running(self):
        assert classify_activity(1.5) == "running"
        assert classify_activity(3.0) == "running"
        assert classify_activity(4.99) == "running"

    def test_vehicle(self):
        assert classify_activity(5.0) == "vehicle"
        assert classify_activity(10.0) == "vehicle"


class TestSafeFloat:
    def test_valid(self):
        assert safe_float("3.14") == 3.14

    def test_invalid(self):
        assert safe_float("abc") is None

    def test_empty(self):
        assert safe_float("") is None

    def test_nan(self):
        assert safe_float("nan") is None

    def test_inf(self):
        assert safe_float("inf") is None


class TestSafeInt:
    def test_valid(self):
        assert safe_int("42") == 42

    def test_valid_float_string(self):
        assert safe_int("42.7") == 42

    def test_invalid(self):
        assert safe_int("abc") is None

    def test_empty(self):
        assert safe_int("") is None


# ──────────────────────────────────────────────────────────────
# Processing function tests (use tmp_path for synthetic CSVs)
# ──────────────────────────────────────────────────────────────


def _write_csv(path: Path, header: str, rows: list[str]) -> str:
    """Helper to write a synthetic CSV file."""
    content = header + "\n" + "\n".join(rows) + "\n"
    path.write_text(content, encoding="utf-8")
    return str(path)


class TestProcessAccelerometer:
    def test_known_csv(self, tmp_path):
        # Two readings in the same 5-min window, stationary (low variance)
        csv_path = tmp_path / "Accelerometer.csv"
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,x,y,z",
            [
                f"{BASE_NS},0.0,0.1,0.2,9.8",
                f"{BASE_NS + 1_000_000_000},1.0,0.15,0.25,9.75",
            ],
        )
        result = process_accelerometer(filepath, 5)
        assert len(result) == 1
        wk = list(result.keys())[0]
        data = result[wk]
        assert data["count"] == 2
        # Magnitude of (0.1, 0.2, 9.8) ~ 9.8024
        # Magnitude of (0.15, 0.25, 9.75) ~ 9.7540
        assert data["mean_mag"] > 9.0
        assert data["std_mag"] < 1.0  # Low variance -> stationary
        assert data["activity"] == "stationary"

    def test_multiple_windows(self, tmp_path):
        csv_path = tmp_path / "Accelerometer.csv"
        # Two different 5-min windows (300 seconds apart)
        ts2 = BASE_NS + 300 * 1_000_000_000
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,x,y,z",
            [
                f"{BASE_NS},0.0,1.0,0.0,0.0",
                f"{ts2},300.0,0.0,1.0,0.0",
            ],
        )
        result = process_accelerometer(filepath, 5)
        assert len(result) == 2


class TestProcessBarometer:
    def test_known_csv(self, tmp_path):
        csv_path = tmp_path / "Barometer.csv"
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,pressure,relativeAltitude",
            [
                f"{BASE_NS},0.0,1013.25,10.5",
                f"{BASE_NS + 1_000_000_000},1.0,1013.50,10.8",
            ],
        )
        result = process_barometer(filepath, 5)
        assert len(result) == 1
        wk = list(result.keys())[0]
        data = result[wk]
        assert data["count"] == 2
        assert abs(data["mean_pressure"] - 1013.375) < 0.01
        assert data["min_pressure"] == 1013.25
        assert data["max_pressure"] == 1013.50
        assert abs(data["mean_altitude"] - 10.65) < 0.01

    def test_missing_altitude(self, tmp_path):
        csv_path = tmp_path / "Barometer.csv"
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,pressure,relativeAltitude",
            [
                f"{BASE_NS},0.0,1013.25,",
            ],
        )
        result = process_barometer(filepath, 5)
        assert len(result) == 1
        wk = list(result.keys())[0]
        assert result[wk]["mean_altitude"] == 0.0  # No altitude data


class TestProcessPedometer:
    def test_step_deltas(self, tmp_path):
        csv_path = tmp_path / "Pedometer.csv"
        # Three readings across two windows
        ts2 = BASE_NS + 300 * 1_000_000_000  # next 5-min window
        ts3 = BASE_NS + 600 * 1_000_000_000  # third window
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,steps",
            [
                f"{BASE_NS},0.0,100",
                f"{ts2},300.0,200",
                f"{ts3},600.0,350",
            ],
        )
        result = process_pedometer(filepath, 5)
        keys = sorted(result.keys())
        assert len(keys) == 3
        # First window: only one reading, delta = last - first = 0
        assert result[keys[0]]["steps_delta"] == 0
        # Second window: prev_last=100, last=200 -> delta=100
        assert result[keys[1]]["steps_delta"] == 100
        # Third window: prev_last=200, last=350 -> delta=150
        assert result[keys[2]]["steps_delta"] == 150

    def test_counter_reset_handled(self, tmp_path):
        """If step counter resets (goes down), delta should be 0."""
        csv_path = tmp_path / "Pedometer.csv"
        ts2 = BASE_NS + 300 * 1_000_000_000
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,steps",
            [
                f"{BASE_NS},0.0,500",
                f"{ts2},300.0,10",  # Counter reset
            ],
        )
        result = process_pedometer(filepath, 5)
        keys = sorted(result.keys())
        # The second window should have delta=0 (reset protection)
        # First window: delta = 500 - 500 = 0
        assert result[keys[0]]["steps_delta"] == 0
        # Second window: prev_last=500, first=10, last=10
        # Since first(10) < prev_last(500), delta = last - prev_last = -490 -> clamped to 0
        assert result[keys[1]]["steps_delta"] == 0


class TestProcessLight:
    def test_known_csv(self, tmp_path):
        csv_path = tmp_path / "Light.csv"
        filepath = _write_csv(
            csv_path,
            "time,seconds_elapsed,lux",
            [
                f"{BASE_NS},0.0,500.0",
                f"{BASE_NS + 1_000_000_000},1.0,600.0",
                f"{BASE_NS + 2_000_000_000},2.0,550.0",
            ],
        )
        result = process_light(filepath, 5)
        assert len(result) == 1
        wk = list(result.keys())[0]
        data = result[wk]
        assert data["count"] == 3
        assert abs(data["mean_lux"] - 550.0) < 0.1
        assert data["min_lux"] == 500.0
        assert data["max_lux"] == 600.0


class TestProcessSession:
    def test_full_session(self, tmp_path):
        session_dir = tmp_path / "session_001"
        session_dir.mkdir()

        # Write Accelerometer.csv
        _write_csv(
            session_dir / "Accelerometer.csv",
            "time,seconds_elapsed,x,y,z",
            [
                f"{BASE_NS},0.0,0.1,0.2,9.8",
                f"{BASE_NS + 1_000_000_000},1.0,0.15,0.25,9.75",
            ],
        )

        # Write Barometer.csv
        _write_csv(
            session_dir / "Barometer.csv",
            "time,seconds_elapsed,pressure,relativeAltitude",
            [
                f"{BASE_NS},0.0,1013.25,10.5",
            ],
        )

        # Write Pedometer.csv
        _write_csv(
            session_dir / "Pedometer.csv",
            "time,seconds_elapsed,steps",
            [
                f"{BASE_NS},0.0,100",
            ],
        )

        result = process_session(str(session_dir), window_min=5)
        assert "movement_summary" in result
        assert "barometer_summary" in result
        assert "pedometer_summary" in result
        # Verify summary files were created
        summary_dir = session_dir / "summaries"
        assert summary_dir.exists()
        assert (summary_dir / "movement_summary.csv").exists()
        assert (summary_dir / "barometer_summary.csv").exists()
        assert (summary_dir / "pedometer_summary.csv").exists()

    def test_nonexistent_dir_returns_empty(self):
        result = process_session("/nonexistent/path/session_999", window_min=5)
        assert result == {}


class TestFindSessions:
    def test_finds_session_directories(self, tmp_path):
        sensors_dir = tmp_path / "sensors"
        sensors_dir.mkdir()

        # Create two valid session dirs with CSV files
        s1 = sensors_dir / "session_001"
        s1.mkdir()
        (s1 / "Accelerometer.csv").write_text("time,x,y,z\n")

        s2 = sensors_dir / "session_002"
        s2.mkdir()
        (s2 / "Barometer.csv").write_text("time,pressure\n")

        # Create a dir without CSVs (should be excluded)
        empty = sensors_dir / "empty_dir"
        empty.mkdir()

        # Create a 'summaries' dir (should be excluded)
        summaries = sensors_dir / "summaries"
        summaries.mkdir()
        (summaries / "something.csv").write_text("data\n")

        sessions = find_sessions(str(sensors_dir))
        assert len(sessions) == 2
        basenames = [os.path.basename(s) for s in sessions]
        assert "session_001" in basenames
        assert "session_002" in basenames
        assert "empty_dir" not in basenames
        assert "summaries" not in basenames

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        sessions = find_sessions(str(tmp_path / "nonexistent"))
        assert sessions == []
