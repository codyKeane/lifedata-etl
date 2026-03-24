#!/usr/bin/env python3
"""
LifeData V4 — Sensor Logger Pre-processor
scripts/process_sensors.py

Reads raw high-frequency sensor CSVs from Sensor Logger (Android) and produces
5-minute windowed summary CSVs that the ETL body and environment modules ingest.

Usage:
    python scripts/process_sensors.py
    python scripts/process_sensors.py --input <session_dir> --window 5
    python scripts/process_sensors.py --all

Input:  raw_base/logs/sensors/<session_dir>/*.csv
Output: raw_base/logs/sensors/<session_dir>/summaries/*_summary.csv

The raw CSVs can be enormous (1+ GB each). This script streams them in chunks
to avoid loading everything into memory.
"""

import argparse
import csv
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path for config loading
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

DEFAULT_WINDOW_MIN = 5
NANOSECONDS_PER_SECOND = 1_000_000_000
DEFAULT_TZ_OFFSET = "-0500"

# Which sensors to process (skipping uncalibrated variants)
SENSOR_FILES = {
    "Accelerometer.csv":  "accelerometer",
    "Gravity.csv":        "gravity",
    "Barometer.csv":      "barometer",
    "Light.csv":          "light",
    "Magnetometer.csv":   "magnetometer",
    "Pedometer.csv":      "pedometer",
    "Activity.csv":       "activity",
}


# ──────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────

def ns_to_epoch_sec(ns_timestamp: int) -> float:
    """Convert nanosecond timestamp to epoch seconds."""
    return ns_timestamp / NANOSECONDS_PER_SECOND


def ns_to_window_key(ns_timestamp: int, window_min: int) -> int:
    """Bucket a nanosecond timestamp into a window key (epoch seconds, floored)."""
    epoch_sec = ns_timestamp / NANOSECONDS_PER_SECOND
    window_sec = window_min * 60
    return int(epoch_sec // window_sec) * window_sec


def epoch_to_local(epoch_sec: float, tz_offset: str = DEFAULT_TZ_OFFSET) -> tuple:
    """Convert epoch seconds to (date_str, time_str, utc_iso, local_iso)."""
    dt_utc = datetime.fromtimestamp(epoch_sec, tz=timezone.utc)

    # Parse offset
    try:
        sign = 1 if tz_offset[0] == "+" else -1
        hours = int(tz_offset[1:3]) if len(tz_offset) >= 3 else 0
        minutes = int(tz_offset[3:5]) if len(tz_offset) >= 5 else 0
        offset = timedelta(hours=sign * hours, minutes=sign * minutes)
    except (ValueError, IndexError):
        offset = timedelta(hours=-5)

    dt_local = dt_utc.astimezone(timezone(offset))
    date_str = dt_local.strftime("%Y-%m-%d")
    time_str = dt_local.strftime("%H:%M:%S")
    return date_str, time_str, dt_utc.isoformat(), dt_local.isoformat()


def safe_float(val: str) -> float | None:
    """Parse string to float, None on failure."""
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (ValueError, TypeError):
        return None


def safe_int(val: str) -> int | None:
    """Parse string to int, None on failure."""
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


# ──────────────────────────────────────────────────────────────
# Activity Classification (per EPSILON spec)
# ──────────────────────────────────────────────────────────────

def classify_activity(accel_magnitude_std: float) -> str:
    """Classify activity from accelerometer magnitude standard deviation.

    Thresholds from LD_MODULE_EPSILON_V4.md lines 84–92.
    """
    if accel_magnitude_std < 0.3:
        return "stationary"
    elif accel_magnitude_std < 1.5:
        return "walking"
    elif accel_magnitude_std < 5.0:
        return "running"
    else:
        return "vehicle"


# ──────────────────────────────────────────────────────────────
# Stream Processors — one per sensor type
# ──────────────────────────────────────────────────────────────

def _stream_csv(filepath: str):
    """Stream rows from a CSV, yielding (nanosecond_ts, fields_dict) pairs.

    Handles the Sensor Logger format where the first column is a nanosecond
    timestamp and the header row defines column names.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts_raw = row.get("time", "").strip()
                if not ts_raw:
                    continue
                ts_ns = int(ts_raw)
                yield ts_ns, row
            except (ValueError, TypeError):
                continue


def process_accelerometer(filepath: str, window_min: int) -> dict:
    """Process Accelerometer.csv into windowed magnitude statistics.

    Returns: {window_key: {mean_mag, std_mag, min_mag, max_mag, count}}
    """
    windows = defaultdict(lambda: {"magnitudes": []})

    for ts_ns, row in _stream_csv(filepath):
        x = safe_float(row.get("x"))
        y = safe_float(row.get("y"))
        z = safe_float(row.get("z"))
        if x is None or y is None or z is None:
            continue

        mag = math.sqrt(x * x + y * y + z * z)
        wk = ns_to_window_key(ts_ns, window_min)
        windows[wk]["magnitudes"].append(mag)

    # Aggregate
    result = {}
    for wk, data in windows.items():
        mags = data["magnitudes"]
        n = len(mags)
        if n == 0:
            continue
        mean = sum(mags) / n
        variance = sum((m - mean) ** 2 for m in mags) / n if n > 1 else 0
        std = math.sqrt(variance)
        result[wk] = {
            "mean_mag": round(mean, 6),
            "std_mag": round(std, 6),
            "min_mag": round(min(mags), 6),
            "max_mag": round(max(mags), 6),
            "count": n,
            "activity": classify_activity(std),
        }

    return result


def process_barometer(filepath: str, window_min: int) -> dict:
    """Process Barometer.csv into windowed pressure averages.

    Returns: {window_key: {mean_pressure, min_pressure, max_pressure, mean_altitude, count}}
    """
    windows = defaultdict(lambda: {"pressures": [], "altitudes": []})

    for ts_ns, row in _stream_csv(filepath):
        pressure = safe_float(row.get("pressure"))
        altitude = safe_float(row.get("relativeAltitude"))
        if pressure is None:
            continue

        wk = ns_to_window_key(ts_ns, window_min)
        windows[wk]["pressures"].append(pressure)
        if altitude is not None:
            windows[wk]["altitudes"].append(altitude)

    result = {}
    for wk, data in windows.items():
        p = data["pressures"]
        a = data["altitudes"]
        n = len(p)
        if n == 0:
            continue
        result[wk] = {
            "mean_pressure": round(sum(p) / n, 4),
            "min_pressure": round(min(p), 4),
            "max_pressure": round(max(p), 4),
            "mean_altitude": round(sum(a) / len(a), 4) if a else 0.0,
            "count": n,
        }

    return result


def process_light(filepath: str, window_min: int) -> dict:
    """Process Light.csv into windowed lux statistics.

    Returns: {window_key: {mean_lux, min_lux, max_lux, count}}
    """
    windows = defaultdict(lambda: {"lux_values": []})

    for ts_ns, row in _stream_csv(filepath):
        lux = safe_float(row.get("lux"))
        if lux is None:
            continue

        wk = ns_to_window_key(ts_ns, window_min)
        windows[wk]["lux_values"].append(lux)

    result = {}
    for wk, data in windows.items():
        values = data["lux_values"]
        n = len(values)
        if n == 0:
            continue
        result[wk] = {
            "mean_lux": round(sum(values) / n, 2),
            "min_lux": round(min(values), 2),
            "max_lux": round(max(values), 2),
            "count": n,
        }

    return result


def process_magnetometer(filepath: str, window_min: int) -> dict:
    """Process Magnetometer.csv into windowed EMF magnitude statistics.

    Returns: {window_key: {mean_mag, std_mag, max_mag, count}}
    """
    windows = defaultdict(lambda: {"magnitudes": []})

    for ts_ns, row in _stream_csv(filepath):
        x = safe_float(row.get("x"))
        y = safe_float(row.get("y"))
        z = safe_float(row.get("z"))
        if x is None or y is None or z is None:
            continue

        mag = math.sqrt(x * x + y * y + z * z)
        wk = ns_to_window_key(ts_ns, window_min)
        windows[wk]["magnitudes"].append(mag)

    result = {}
    for wk, data in windows.items():
        mags = data["magnitudes"]
        n = len(mags)
        if n == 0:
            continue
        mean = sum(mags) / n
        variance = sum((m - mean) ** 2 for m in mags) / n if n > 1 else 0
        std = math.sqrt(variance)
        result[wk] = {
            "mean_mag_ut": round(mean, 4),
            "std_mag_ut": round(std, 4),
            "max_mag_ut": round(max(mags), 4),
            "count": n,
        }

    return result


def process_pedometer(filepath: str, window_min: int) -> dict:
    """Process Pedometer.csv into windowed step count deltas.

    Pedometer gives cumulative steps. We compute the delta per window.
    Returns: {window_key: {steps_delta, first_steps, last_steps}}
    """
    windows = defaultdict(lambda: {"first": None, "last": None})

    for ts_ns, row in _stream_csv(filepath):
        steps = safe_int(row.get("steps"))
        if steps is None:
            continue

        wk = ns_to_window_key(ts_ns, window_min)
        if windows[wk]["first"] is None:
            windows[wk]["first"] = steps
        windows[wk]["last"] = steps

    result = {}
    prev_last = None
    for wk in sorted(windows.keys()):
        data = windows[wk]
        first = data["first"]
        last = data["last"]
        if first is None or last is None:
            continue

        delta = last - first
        # Also account for gap from previous window
        if prev_last is not None and first > prev_last:
            delta = last - prev_last
        elif prev_last is None:
            delta = last - first

        if delta < 0:
            delta = 0  # Counter reset

        result[wk] = {
            "steps_delta": delta,
            "first_steps": first,
            "last_steps": last,
        }
        prev_last = last

    return result


def process_activity(filepath: str, window_min: int) -> dict:
    """Process Activity.csv into windowed activity mode.

    The Activity.csv has an 'activity' text column with values like
    'tilting', 'stationary', 'walking', 'running', 'in_vehicle', 'unknown'.
    We compute the dominant (most common) activity per window.

    Returns: {window_key: {dominant_activity, activity_counts}}
    """
    windows = defaultdict(lambda: defaultdict(int))

    for ts_ns, row in _stream_csv(filepath):
        activity = row.get("activity", "").strip().lower()
        if not activity:
            continue

        wk = ns_to_window_key(ts_ns, window_min)
        windows[wk][activity] += 1

    result = {}
    for wk, counts in windows.items():
        if not counts:
            continue
        dominant = max(counts, key=counts.get)
        result[wk] = {
            "dominant_activity": dominant,
            "activity_counts": dict(counts),
        }

    return result


# ──────────────────────────────────────────────────────────────
# Summary CSV Writers
# ──────────────────────────────────────────────────────────────

def _read_session_metadata(session_dir: str) -> dict:
    """Read Metadata.csv from the session directory for timezone info."""
    meta_path = os.path.join(session_dir, "Metadata.csv")
    meta = {"timezone_offset": DEFAULT_TZ_OFFSET, "device": "unknown"}
    if not os.path.exists(meta_path):
        return meta

    with open(meta_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tz_str = row.get("recording timezone", "").strip()
            if tz_str == "America/Chicago":
                meta["timezone_offset"] = "-0500"
            elif tz_str:
                # Try to resolve IANA to offset
                try:
                    from zoneinfo import ZoneInfo
                    from datetime import datetime as dt
                    tz = ZoneInfo(tz_str)
                    epoch_str = row.get("recording epoch time", "0")
                    epoch = int(epoch_str) / 1000 if len(epoch_str) > 10 else int(epoch_str)
                    offset = dt.fromtimestamp(epoch, tz=tz).strftime("%z")
                    meta["timezone_offset"] = offset
                except Exception:
                    pass
            meta["device"] = row.get("device name", "unknown")
            break

    return meta


def write_movement_summary(session_dir: str, accel_data: dict, tz_offset: str) -> str:
    """Write movement_summary.csv from accelerometer windowed data."""
    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "movement_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "mean_accel_mag", "std_accel_mag", "min_accel_mag", "max_accel_mag",
            "activity_class", "sample_count",
        ])
        for wk in sorted(accel_data.keys()):
            d = accel_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["mean_mag"], d["std_mag"], d["min_mag"], d["max_mag"],
                d["activity"], d["count"],
            ])

    return out_path


def write_barometer_summary(session_dir: str, baro_data: dict, tz_offset: str) -> str:
    """Write barometer_summary.csv from barometer windowed data."""
    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "barometer_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "mean_pressure_hpa", "min_pressure_hpa", "max_pressure_hpa",
            "mean_altitude_m", "sample_count",
        ])
        for wk in sorted(baro_data.keys()):
            d = baro_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["mean_pressure"], d["min_pressure"], d["max_pressure"],
                d["mean_altitude"], d["count"],
            ])

    return out_path


def write_light_summary(session_dir: str, light_data: dict, tz_offset: str) -> str:
    """Write light_summary.csv from light windowed data."""
    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "light_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "mean_lux", "min_lux", "max_lux", "sample_count",
        ])
        for wk in sorted(light_data.keys()):
            d = light_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["mean_lux"], d["min_lux"], d["max_lux"], d["count"],
            ])

    return out_path


def write_magnetometer_summary(session_dir: str, mag_data: dict, tz_offset: str) -> str:
    """Write magnetometer_summary.csv from magnetometer windowed data."""
    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "magnetometer_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "mean_mag_ut", "std_mag_ut", "max_mag_ut", "sample_count",
        ])
        for wk in sorted(mag_data.keys()):
            d = mag_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["mean_mag_ut"], d["std_mag_ut"], d["max_mag_ut"], d["count"],
            ])

    return out_path


def write_pedometer_summary(session_dir: str, ped_data: dict, tz_offset: str) -> str:
    """Write pedometer_summary.csv from pedometer windowed data."""
    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pedometer_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "steps_delta", "cumulative_steps",
        ])
        for wk in sorted(ped_data.keys()):
            d = ped_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["steps_delta"], d["last_steps"],
            ])

    return out_path


def write_activity_summary(session_dir: str, act_data: dict, tz_offset: str) -> str:
    """Write activity_summary.csv from activity windowed data."""
    import json

    out_dir = os.path.join(session_dir, "summaries")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "activity_summary.csv")

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "epoch", "date", "time", "timezone_offset",
            "dominant_activity", "activity_counts_json",
        ])
        for wk in sorted(act_data.keys()):
            d = act_data[wk]
            date_str, time_str, _, _ = epoch_to_local(wk, tz_offset)
            writer.writerow([
                wk, date_str, time_str, tz_offset,
                d["dominant_activity"],
                json.dumps(d["activity_counts"]),
            ])

    return out_path


# ──────────────────────────────────────────────────────────────
# Main Processing Pipeline
# ──────────────────────────────────────────────────────────────

def process_session(session_dir: str, window_min: int = DEFAULT_WINDOW_MIN) -> dict:
    """Process a single Sensor Logger session directory.

    Args:
        session_dir: Path to session directory containing raw CSVs.
        window_min: Window size in minutes for aggregation.

    Returns:
        Dict with summary file paths and row counts.
    """
    session_dir = os.path.abspath(session_dir)
    if not os.path.isdir(session_dir):
        print(f"ERROR: Session directory does not exist: {session_dir}")
        return {}

    meta = _read_session_metadata(session_dir)
    tz_offset = meta["timezone_offset"]
    print(f"\n{'='*60}")
    print(f"Processing session: {os.path.basename(session_dir)}")
    print(f"  Device: {meta['device']}")
    print(f"  Timezone: {tz_offset}")
    print(f"  Window: {window_min} minutes")
    print(f"{'='*60}")

    results = {}

    # --- Accelerometer → movement_summary ---
    accel_path = os.path.join(session_dir, "Accelerometer.csv")
    if os.path.exists(accel_path):
        print(f"\n  Processing Accelerometer.csv...")
        accel_data = process_accelerometer(accel_path, window_min)
        out = write_movement_summary(session_dir, accel_data, tz_offset)
        results["movement_summary"] = {"path": out, "windows": len(accel_data)}
        print(f"    → {len(accel_data)} windows written to movement_summary.csv")

    # --- Barometer → barometer_summary ---
    baro_path = os.path.join(session_dir, "Barometer.csv")
    if os.path.exists(baro_path):
        print(f"\n  Processing Barometer.csv...")
        baro_data = process_barometer(baro_path, window_min)
        out = write_barometer_summary(session_dir, baro_data, tz_offset)
        results["barometer_summary"] = {"path": out, "windows": len(baro_data)}
        print(f"    → {len(baro_data)} windows written to barometer_summary.csv")

    # --- Light → light_summary ---
    light_path = os.path.join(session_dir, "Light.csv")
    if os.path.exists(light_path):
        print(f"\n  Processing Light.csv...")
        light_data = process_light(light_path, window_min)
        out = write_light_summary(session_dir, light_data, tz_offset)
        results["light_summary"] = {"path": out, "windows": len(light_data)}
        print(f"    → {len(light_data)} windows written to light_summary.csv")

    # --- Magnetometer → magnetometer_summary ---
    mag_path = os.path.join(session_dir, "Magnetometer.csv")
    if os.path.exists(mag_path):
        print(f"\n  Processing Magnetometer.csv...")
        mag_data = process_magnetometer(mag_path, window_min)
        out = write_magnetometer_summary(session_dir, mag_data, tz_offset)
        results["magnetometer_summary"] = {"path": out, "windows": len(mag_data)}
        print(f"    → {len(mag_data)} windows written to magnetometer_summary.csv")

    # --- Pedometer → pedometer_summary ---
    ped_path = os.path.join(session_dir, "Pedometer.csv")
    if os.path.exists(ped_path):
        print(f"\n  Processing Pedometer.csv...")
        ped_data = process_pedometer(ped_path, window_min)
        out = write_pedometer_summary(session_dir, ped_data, tz_offset)
        results["pedometer_summary"] = {"path": out, "windows": len(ped_data)}
        print(f"    → {len(ped_data)} windows written to pedometer_summary.csv")

    # --- Activity → activity_summary ---
    act_path = os.path.join(session_dir, "Activity.csv")
    if os.path.exists(act_path):
        print(f"\n  Processing Activity.csv...")
        act_data = process_activity(act_path, window_min)
        out = write_activity_summary(session_dir, act_data, tz_offset)
        results["activity_summary"] = {"path": out, "windows": len(act_data)}
        print(f"    → {len(act_data)} windows written to activity_summary.csv")

    print(f"\n  ✓ Session complete. {len(results)} summary files generated.")
    return results


def find_sessions(sensors_dir: str) -> list:
    """Find all session directories under the sensors directory."""
    sensors_dir = os.path.abspath(sensors_dir)
    if not os.path.isdir(sensors_dir):
        return []

    sessions = []
    for entry in sorted(os.listdir(sensors_dir)):
        full_path = os.path.join(sensors_dir, entry)
        if os.path.isdir(full_path) and entry != "summaries":
            # Check if it contains any sensor CSVs
            csvs = [f for f in os.listdir(full_path) if f.endswith(".csv")]
            if csvs:
                sessions.append(full_path)

    return sessions


def main():
    parser = argparse.ArgumentParser(
        description="Process Sensor Logger raw data into windowed summaries"
    )
    parser.add_argument(
        "--input", "-i",
        help="Path to a specific session directory to process",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Process all sessions in the default sensor directory",
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=DEFAULT_WINDOW_MIN,
        help=f"Window size in minutes (default: {DEFAULT_WINDOW_MIN})",
    )
    parser.add_argument(
        "--sensors-dir",
        default=None,
        help="Override the sensors base directory (default: from config.yaml)",
    )
    args = parser.parse_args()

    # Determine sensors directory
    if args.sensors_dir:
        sensors_dir = os.path.expanduser(args.sensors_dir)
    else:
        # Load from config
        try:
            import yaml
            config_path = os.path.expanduser("~/LifeData/config.yaml")
            with open(config_path) as f:
                config = yaml.safe_load(f)
            raw_base = os.path.expanduser(config["lifedata"]["raw_base"])
            sensor_dir_rel = config["lifedata"]["modules"]["body"].get(
                "sensor_logger_dir", "logs/sensors"
            )
            sensors_dir = os.path.join(raw_base, sensor_dir_rel)
        except Exception as e:
            print(f"Warning: Could not load config.yaml: {e}")
            sensors_dir = os.path.expanduser(
                "~/LifeData/raw/LifeData/logs/sensors"
            )

    if args.input:
        # Process single session
        process_session(args.input, args.window)
    elif args.all:
        # Process all sessions
        sessions = find_sessions(sensors_dir)
        if not sessions:
            print(f"No session directories found in {sensors_dir}")
            sys.exit(1)

        print(f"Found {len(sessions)} session(s) in {sensors_dir}")
        for session in sessions:
            # Skip sessions that already have summaries (unless they're stale)
            summary_dir = os.path.join(session, "summaries")
            if os.path.isdir(summary_dir):
                summary_files = os.listdir(summary_dir)
                if len(summary_files) >= 4:
                    print(f"\n  Skipping {os.path.basename(session)} (already processed)")
                    continue

            process_session(session, args.window)
    else:
        # Default: process all unprocessed sessions
        sessions = find_sessions(sensors_dir)
        if not sessions:
            print(f"No session directories found in {sensors_dir}")
            print(f"  Searched: {sensors_dir}")
            sys.exit(1)

        unprocessed = []
        for session in sessions:
            summary_dir = os.path.join(session, "summaries")
            if not os.path.isdir(summary_dir) or len(os.listdir(summary_dir)) < 4:
                unprocessed.append(session)

        if not unprocessed:
            print("All sessions are already processed. Use --all to reprocess.")
            sys.exit(0)

        print(f"Found {len(unprocessed)} unprocessed session(s)")
        for session in unprocessed:
            process_session(session, args.window)

    print("\n✓ All processing complete.")


if __name__ == "__main__":
    main()
