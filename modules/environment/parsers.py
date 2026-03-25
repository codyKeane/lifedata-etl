"""
LifeData V4 — Environment Module Parsers
modules/environment/parsers.py

Parses Tasker-generated CSV files for environment data:
  - hourly_*.csv     → environment.hourly (multi-line records with WiFi scan data)
  - geofence_*.csv   → environment.location
  - astro_*.csv      → environment.astro
"""

from __future__ import annotations

import re
from typing import Any

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.environment.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def parse_hourly(file_path: str) -> list[Event]:
    """Parse hourly environment snapshot CSV.

    Format: epoch,date,time,temperature_f,humidity,lat,lon,accuracy,wifi_data...
    The WiFi data after the CSV line is multi-line text containing scan results.
    We extract only the structured CSV fields (first line of each record).

    The multi-line WiFi blocks are separated by the next epoch line.
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Split on lines that start with an epoch timestamp (10+ digits)
    # Each such line begins a new record
    lines = content.split("\n")
    csv_lines = [
        line for line in lines if line.strip() and re.match(r"^\d{10,}", line.strip())
    ]

    for line in csv_lines:
        try:
            # The CSV portion is everything up to the first multi-line WiFi data
            # Format: epoch,date,time,temp_f,humidity,lat,lon,accuracy,wifi_conn_info
            # The wifi_conn_info starts with ">>> CONNECTION <<<" and continues multi-line
            # We only need the first part
            fields = line.strip().split(",")
            if len(fields) < 5:
                continue

            epoch_str = fields[0].strip()
            if not epoch_str.isdigit():
                continue

            ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
            temp_f = safe_float(fields[3])
            humidity = safe_float(fields[4])
            lat = safe_float(fields[5]) if len(fields) > 5 else None
            lon = safe_float(fields[6]) if len(fields) > 6 else None
            accuracy = safe_float(fields[7]) if len(fields) > 7 else None

            extra = {}
            if temp_f is not None:
                extra["temp_f"] = temp_f
                extra["temp_c"] = round((temp_f - 32) * 5 / 9, 1)
            if humidity is not None:
                extra["humidity_pct"] = humidity
            if accuracy is not None:
                extra["gps_accuracy_m"] = accuracy

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="environment.hourly",
                    event_type="snapshot",
                    value_numeric=temp_f,
                    value_json=safe_json(extra) if extra else None,
                    location_lat=lat,
                    location_lon=lon,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                )
            )

        except Exception as e:
            log.warning(f"{file_path}: hourly parse error: {e}")
            continue

    return events


def parse_geofence(file_path: str) -> list[Event]:
    """Parse location/geofence CSV.

    Format: epoch,lat,lon,accuracy,?,cell_id_flag,?
    No date/time columns — only epoch.
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
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

                lat = safe_float(fields[1])
                lon = safe_float(fields[2])
                accuracy = safe_float(fields[3]) if len(fields) > 3 else None

                if lat is None or lon is None:
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)

                extra = {}
                if accuracy is not None:
                    extra["accuracy_m"] = accuracy

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="environment.location",
                        event_type="geofence",
                        value_numeric=accuracy,
                        value_json=safe_json(extra) if extra else None,
                        location_lat=lat,
                        location_lon=lon,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: geofence parse error: {e}")
                continue

    return events


def parse_astro(file_path: str) -> list[Event]:
    """Parse astronomy data CSV.

    Format: epoch,moon_day,moon_phase_name,moon_illumination_pct,sun_hours
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
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
                moon_day = safe_int(fields[1]) if len(fields) > 1 else None
                moon_phase = fields[2].strip() if len(fields) > 2 else None
                moon_illum = safe_float(fields[3]) if len(fields) > 3 else None
                sun_hours = safe_float(fields[4]) if len(fields) > 4 else None

                extra: dict[str, Any] = {}
                if moon_day is not None:
                    extra["moon_day"] = moon_day
                if moon_phase:
                    extra["moon_phase"] = moon_phase
                if moon_illum is not None:
                    extra["moon_illumination_pct"] = moon_illum
                if sun_hours is not None:
                    extra["sun_hours"] = sun_hours

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="environment.astro",
                        event_type="daily",
                        value_numeric=moon_illum,
                        value_text=moon_phase,
                        value_json=safe_json(extra) if extra else None,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: astro parse error: {e}")
                continue

    return events


PARSER_REGISTRY = {
    "hourly_": parse_hourly,
    "geofence_": parse_geofence,
    "astro_": parse_astro,
}


# ──────────────────────────────────────────────────────────────
# Sensor Logger Summary Parsers
# ──────────────────────────────────────────────────────────────


def parse_barometer_summary(file_path: str) -> list[Event]:
    """Parse barometer_summary.csv → environment.pressure / local_barometer events.

    Format: epoch,date,time,timezone_offset,mean_pressure_hpa,min_pressure_hpa,
            max_pressure_hpa,mean_altitude_m,sample_count
    """
    import csv as csv_mod

    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                mean_pressure = safe_float(row.get("mean_pressure_hpa"))
                if mean_pressure is None:
                    continue

                extra = {
                    "mean_pressure_hpa": mean_pressure,
                    "min_pressure_hpa": safe_float(row.get("min_pressure_hpa")),
                    "max_pressure_hpa": safe_float(row.get("max_pressure_hpa")),
                    "mean_altitude_m": safe_float(row.get("mean_altitude_m")),
                    "sample_count": safe_int(row.get("sample_count")),
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="environment.pressure",
                        event_type="local_barometer",
                        value_numeric=mean_pressure,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: barometer parse error: {e}")
                continue

    return events


def parse_light_summary(file_path: str) -> list[Event]:
    """Parse light_summary.csv → environment.light / lux_reading events.

    Format: epoch,date,time,timezone_offset,mean_lux,min_lux,max_lux,sample_count
    """
    import csv as csv_mod

    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                mean_lux = safe_float(row.get("mean_lux"))
                if mean_lux is None:
                    continue

                extra = {
                    "mean_lux": mean_lux,
                    "min_lux": safe_float(row.get("min_lux")),
                    "max_lux": safe_float(row.get("max_lux")),
                    "sample_count": safe_int(row.get("sample_count")),
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="environment.light",
                        event_type="lux_reading",
                        value_numeric=mean_lux,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: light parse error: {e}")
                continue

    return events


def parse_magnetometer_summary(file_path: str) -> list[Event]:
    """Parse magnetometer_summary.csv → environment.emf / magnetometer events.

    Format: epoch,date,time,timezone_offset,mean_mag_ut,std_mag_ut,max_mag_ut,sample_count
    """
    import csv as csv_mod

    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv_mod.DictReader(f)
        for line_num, row in enumerate(reader, 2):
            try:
                epoch_str = row.get("epoch", "").strip()
                if not epoch_str or not epoch_str.isdigit():
                    continue

                tz_off = row.get("timezone_offset", DEFAULT_TZ_OFFSET).strip()
                ts_utc, ts_local = parse_timestamp(epoch_str, tz_off)

                mean_mag = safe_float(row.get("mean_mag_ut"))
                if mean_mag is None:
                    continue

                extra = {
                    "mean_magnitude_ut": mean_mag,
                    "std_magnitude_ut": safe_float(row.get("std_mag_ut")),
                    "max_magnitude_ut": safe_float(row.get("max_mag_ut")),
                    "sample_count": safe_int(row.get("sample_count")),
                    "source": "sensor_logger",
                }

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=tz_off,
                        source_module="environment.emf",
                        event_type="magnetometer",
                        value_numeric=mean_mag,
                        value_json=safe_json(extra),
                        tags="sensor_logger,automated,5min_window",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: magnetometer parse error: {e}")
                continue

    return events


# Add sensor summary parsers to registry
PARSER_REGISTRY["barometer_summary"] = parse_barometer_summary
PARSER_REGISTRY["light_summary"] = parse_light_summary
PARSER_REGISTRY["magnetometer_summary"] = parse_magnetometer_summary
