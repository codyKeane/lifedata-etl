"""
LifeData V4 — Body Module Parsers
modules/body/parsers.py

Parses CSV files for physiological and biometric data:
  - quicklog_*.csv   → body.caffeine, body.meal, body.vape, body.exercise,
                        body.pain, body.weight, body.water, body.supplement,
                        body.blood_pressure
  - steps_*.csv      → body.steps
  - hr_*.csv         → body.heart_rate
  - health_*.csv     → body.steps / body.heart_rate / body.sleep / body.spo2
  - sleep_*.csv      → body.sleep (start/end triggers)
  - reaction_*.csv   → body.cognition (reaction time)
"""

from __future__ import annotations

import json
import os
from typing import Any

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.body.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"

# V3 quicklog category → (source_module, event_type) mapping
QUICKLOG_CATEGORIES = {
    "1": ("body.caffeine", "intake"),
    "10": ("body.meal", "logged"),
    "11": ("body.vape", "session"),
    "12": ("body.exercise", "session"),
    "13": ("body.pain", "report"),
    "17": ("body.weight", "measurement"),
    "18": ("body.blood_pressure", "measurement"),
    "19": ("body.water", "intake"),
    "20": ("body.supplement", "taken"),
}


def parse_quicklog(file_path: str) -> list[Event]:
    """Parse quicklog CSV → body.* events based on category codes.

    V3-compatible format: epoch,date,time,category,value,location
    Each category code maps to a specific body source_module and event_type.
    Non-body categories (e.g. mood=2) are silently skipped — they belong
    to the Mind module.
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 5:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                category = fields[3].strip()
                mapping = QUICKLOG_CATEGORIES.get(category)
                if mapping is None:
                    # Not a body category — skip silently
                    continue

                source_module, event_type = mapping
                value_str = fields[4].strip() if len(fields) > 4 else ""
                location = fields[5].strip() if len(fields) > 5 else ""

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)

                value_numeric = safe_float(value_str)
                value_text = None
                value_json_data: dict[str, Any] = {}

                if location:
                    value_json_data["location"] = location

                # Category-specific handling
                if category == "1":  # caffeine
                    value_json_data["unit"] = "mg"
                elif category == "12":  # exercise
                    value_json_data["unit"] = "minutes"
                    value_text = value_str if not value_numeric else None
                elif category == "13":  # pain
                    value_json_data["scale"] = "1-10"
                elif category == "17":  # weight
                    value_json_data["unit"] = "lbs"
                elif category == "18":  # blood pressure
                    # Value might be "120/80" format
                    value_text = value_str
                    value_numeric = None
                    if "/" in value_str:
                        parts = value_str.split("/")
                        systolic = safe_int(parts[0])
                        diastolic = safe_int(parts[1]) if len(parts) > 1 else None
                        value_json_data["systolic"] = systolic
                        value_json_data["diastolic"] = diastolic
                elif category == "19":  # water
                    value_json_data["unit"] = "oz"
                elif category == "20" or category == "10":  # supplement
                    value_text = value_str
                    value_numeric = None
                elif category == "11":  # vape
                    value_text = value_str or "session"
                    value_numeric = None

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module=source_module,
                        event_type=event_type,
                        value_numeric=value_numeric,
                        value_text=value_text,
                        value_json=safe_json(value_json_data)
                        if value_json_data
                        else None,
                        tags="quicklog,manual",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: quicklog parse error: {e}")
                continue

    return events


def parse_samsung_health(file_path: str) -> list[Event]:
    """Parse Samsung Health / Health Connect export CSVs.

    Detects the data type from filename prefix:
      - steps_*.csv   → body.steps / step_count
      - hr_*.csv      → body.heart_rate / measurement
      - health_*.csv  → auto-detect from column count

    Common format: epoch,date,time,value[,source]
    """
    events = []
    basename = os.path.basename(file_path).lower()

    # Determine source type from filename
    if basename.startswith("steps_"):
        source_module = "body.steps"
        event_type = "step_count_samsung"
    elif basename.startswith("hr_"):
        source_module = "body.heart_rate"
        event_type = "measurement"
    elif basename.startswith("spo2_"):
        source_module = "body.spo2"
        event_type = "measurement"
    elif basename.startswith("health_"):
        # Generic health export — will auto-detect per row
        source_module = "body.steps"
        event_type = "step_count_samsung"
    else:
        log.warning(f"Unknown health file type: {basename}")
        return []

    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 4:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    # Might be a header row
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
                value = safe_float(fields[3])
                source = fields[4].strip() if len(fields) > 4 else "samsung_health"

                if value is None:
                    continue

                extra = {"source": source}

                # For health_*.csv, try to identify the type from the data
                # (step counts are typically > 10, heart rate 40-200, SpO2 85-100)
                actual_source = source_module
                actual_event = event_type

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module=actual_source,
                        event_type=actual_event,
                        value_numeric=value,
                        value_json=safe_json(extra),
                        tags="automated,health",
                        confidence=0.95,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: health parse error: {e}")
                continue

    return events


def parse_sleep(file_path: str) -> list[Event]:
    """Parse sleep trigger CSVs → body.sleep events.

    Format: epoch,date,time,event(start|end),battery
    Emits individual sleep_start and sleep_end events.
    The post_ingest hook computes sleep duration by pairing them.
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 4:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
                event_name = fields[3].strip().lower()
                battery = safe_float(fields[4]) if len(fields) > 4 else None

                if event_name not in ("start", "end", "sleep_start", "sleep_end"):
                    continue

                event_type = "sleep_start" if "start" in event_name else "sleep_end"

                extra = {}
                if battery is not None:
                    extra["battery_pct"] = battery

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="body.sleep",
                        event_type=event_type,
                        value_numeric=battery,
                        value_json=safe_json(extra) if extra else None,
                        tags="sleep,automated",
                        confidence=0.9,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: sleep parse error: {e}")
                continue

    return events


def parse_reaction(file_path: str) -> list[Event]:
    """Parse reaction time test CSVs → body.cognition events.

    Format: epoch,color,reaction_ms
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                fields = line.split(",")
                if len(fields) < 3:
                    continue

                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
                color = fields[1].strip()
                reaction_ms = safe_float(fields[2])

                if reaction_ms is None:
                    continue

                extra = {"color": color, "unit": "ms"}

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="body.cognition",
                        event_type="reaction_time",
                        value_numeric=reaction_ms,
                        value_text=color,
                        value_json=safe_json(extra),
                        tags="cognition,manual",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: reaction parse error: {e}")
                continue

    return events


# ──────────────────────────────────────────────────────────────
# Sensor Logger Summary Parsers
# ──────────────────────────────────────────────────────────────


def parse_movement_summary(file_path: str) -> list[Event]:
    """Parse movement_summary.csv → body.movement / accelerometer_summary events.

    Format: epoch,date,time,timezone_offset,mean_accel_mag,std_accel_mag,
            min_accel_mag,max_accel_mag,activity_class,sample_count
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        import csv as csv_mod

        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                mean_mag = safe_float(row.get("mean_accel_mag"))
                std_mag = safe_float(row.get("std_accel_mag"))
                activity = row.get("activity_class", "").strip()
                sample_count = safe_int(row.get("sample_count"))

                extra = {
                    "mean_accel_mag": mean_mag,
                    "std_accel_mag": std_mag,
                    "min_accel_mag": safe_float(row.get("min_accel_mag")),
                    "max_accel_mag": safe_float(row.get("max_accel_mag")),
                    "activity_class": activity,
                    "sample_count": sample_count,
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="body.movement",
                        event_type="accelerometer_summary",
                        value_numeric=std_mag,  # intensity proxy
                        value_text=activity,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=0.85,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: movement parse error: {e}")
                continue

    return events


def parse_activity_summary(file_path: str) -> list[Event]:
    """Parse activity_summary.csv → body.activity / classification events.

    Format: epoch,date,time,timezone_offset,dominant_activity,activity_counts_json
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        import csv as csv_mod

        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                dominant = row.get("dominant_activity", "").strip()
                counts_str = row.get("activity_counts_json", "{}")

                extra = {
                    "activity_type": dominant,
                    "counts": json.loads(counts_str) if counts_str else {},
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="body.activity",
                        event_type="classification",
                        value_text=dominant,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=0.7,  # threshold classifier per ALPHA spec
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: activity parse error: {e}")
                continue

    return events


def parse_pedometer_summary(file_path: str) -> list[Event]:
    """Parse pedometer_summary.csv → body.steps / step_count events.

    Format: epoch,date,time,timezone_offset,steps_delta,cumulative_steps
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        import csv as csv_mod

        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                steps_delta = safe_float(row.get("steps_delta"))
                cumulative = safe_int(row.get("cumulative_steps"))

                if steps_delta is None or steps_delta <= 0:
                    continue  # skip zero-step windows

                extra = {
                    "cumulative_steps": cumulative,
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="body.steps",
                        event_type="step_count_sensor",
                        value_numeric=steps_delta,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=0.85,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: pedometer parse error: {e}")
                continue

    return events


# Parser registry: filename prefix → parser function
PARSER_REGISTRY = {
    "quicklog_": parse_quicklog,
    "steps_": parse_samsung_health,
    "hr_": parse_samsung_health,
    "spo2_": parse_samsung_health,
    "health_": parse_samsung_health,
    "sleep_": parse_sleep,
    "reaction_": parse_reaction,
    "movement_summary": parse_movement_summary,
    "activity_summary": parse_activity_summary,
    "pedometer_summary": parse_pedometer_summary,
}
