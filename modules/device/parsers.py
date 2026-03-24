"""
LifeData V4 — Device Module Parsers
modules/device/parsers.py

Parses Tasker-generated CSV files for device events:
  - battery_*.csv  → device.battery
  - screen_*.csv   → device.screen
  - charging_*.csv → device.charging
  - bluetooth_*.csv → device.bluetooth

All parsers handle both v3 (no %TIMEZONE) and v4 (with %TIMEZONE) formats.
Unresolved Tasker variables (%TEMP, %MFREE, etc.) are treated as missing.
"""

import os
from typing import Optional

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.device.parsers")

# Default timezone offset when v3 CSVs don't include %TIMEZONE
DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def _is_unresolved(value: str) -> bool:
    """Check if a Tasker variable was not resolved (still starts with %)."""
    return value.startswith("%") if value else True


def _parse_csv_line(line: str) -> Optional[list[str]]:
    """Split a CSV line into fields, returning None for blank/malformed lines."""
    line = line.strip()
    if not line:
        return None
    return line.split(",")


def parse_battery(file_path: str) -> list[Event]:
    """Parse battery pulse CSV.

    v3 format: epoch,date,time,battery_pct,%TEMP,%MFREE,uptime
    v4 format: epoch,date,time,timezone,battery_pct,temp,mem_free,uptime

    The v3 format has %TEMP and %MFREE as unresolved Tasker variables.
    We detect this and store them as None.
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields:
                continue

            try:
                # Determine format by field count and presence of timezone
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    log.debug(f"{file_path}:{line_num}: skipping non-epoch line")
                    continue

                # Check if this is v4 format (has timezone field)
                # v3: epoch,date,time,pct,...  (date like "3-22-26")
                # v4: epoch,date,time,tz,pct,...
                tz_offset = DEFAULT_TZ_OFFSET
                if len(fields) >= 8 and not _is_unresolved(fields[3]):
                    # v4 format with timezone
                    tz_offset = fields[3].strip()
                    batt_pct = safe_float(fields[4])
                    temp_str = fields[5].strip()
                    mem_str = fields[6].strip()
                    uptime_str = fields[7].strip() if len(fields) > 7 else None
                else:
                    # v3 format (no timezone)
                    batt_pct = safe_float(fields[3])
                    temp_str = fields[4].strip() if len(fields) > 4 else ""
                    mem_str = fields[5].strip() if len(fields) > 5 else ""
                    uptime_str = fields[6].strip() if len(fields) > 6 else None

                if batt_pct is None:
                    log.debug(f"{file_path}:{line_num}: no battery percentage")
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                # Build value_json with available data
                extra = {}
                temp = safe_float(temp_str) if not _is_unresolved(temp_str) else None
                mem_free = safe_int(mem_str) if not _is_unresolved(mem_str) else None
                uptime = safe_int(uptime_str) if uptime_str and not _is_unresolved(uptime_str) else None

                if temp is not None:
                    extra["temp_c"] = temp
                if mem_free is not None:
                    extra["mem_free_mb"] = mem_free
                if uptime is not None:
                    extra["uptime_sec"] = uptime

                events.append(Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=tz_offset,
                    source_module="device.battery",
                    event_type="pulse",
                    value_numeric=batt_pct,
                    value_json=safe_json(extra) if extra else None,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                ))

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


def parse_screen(file_path: str) -> list[Event]:
    """Parse screen on/off CSV.

    v3 format: epoch,date,time,on|off,battery_pct
    v4 format: epoch,date,time,timezone,on|off,battery_pct
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields or len(fields) < 4:
                continue

            try:
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz_offset = DEFAULT_TZ_OFFSET
                # Detect v4 format: field[3] would be timezone, field[4] would be on/off
                if len(fields) >= 5 and fields[3].strip().lstrip("+-").isdigit():
                    tz_offset = fields[3].strip()
                    state = fields[4].strip().lower()
                    batt_pct = safe_float(fields[5]) if len(fields) > 5 else None
                else:
                    state = fields[3].strip().lower()
                    batt_pct = safe_float(fields[4]) if len(fields) > 4 else None

                if state not in ("on", "off"):
                    log.debug(f"{file_path}:{line_num}: unknown screen state '{state}'")
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                extra = {}
                if batt_pct is not None:
                    extra["battery_pct"] = batt_pct

                events.append(Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=tz_offset,
                    source_module="device.screen",
                    event_type=f"screen_{state}",
                    value_numeric=batt_pct,
                    value_text=state,
                    value_json=safe_json(extra) if extra else None,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                ))

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


def parse_charging(file_path: str) -> list[Event]:
    """Parse charging start/stop CSV.

    v3 format: epoch,date,time,charge_start|charge_stop,battery_pct
    v4 format: epoch,date,time,timezone,charge_start|charge_stop,battery_pct
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields or len(fields) < 4:
                continue

            try:
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz_offset = DEFAULT_TZ_OFFSET
                if len(fields) >= 5 and fields[3].strip().lstrip("+-").isdigit():
                    tz_offset = fields[3].strip()
                    state = fields[4].strip().lower()
                    batt_pct = safe_float(fields[5]) if len(fields) > 5 else None
                else:
                    state = fields[3].strip().lower()
                    batt_pct = safe_float(fields[4]) if len(fields) > 4 else None

                if state not in ("charge_start", "charge_stop"):
                    log.debug(
                        f"{file_path}:{line_num}: unknown charging state '{state}'"
                    )
                    continue

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                events.append(Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=tz_offset,
                    source_module="device.charging",
                    event_type=state,
                    value_numeric=batt_pct,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                ))

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


def parse_bluetooth(file_path: str) -> list[Event]:
    """Parse bluetooth event CSV.

    v3 format: epoch,date,time,bt_event,on|off
    v4 format: epoch,date,time,timezone,bt_event,on|off
    """
    events = []
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            fields = _parse_csv_line(line)
            if not fields or len(fields) < 4:
                continue

            try:
                epoch_str = fields[0].strip()
                if not epoch_str.isdigit():
                    continue

                tz_offset = DEFAULT_TZ_OFFSET
                if len(fields) >= 6 and fields[3].strip().lstrip("+-").isdigit():
                    tz_offset = fields[3].strip()
                    bt_state = fields[5].strip().lower() if len(fields) > 5 else "on"
                else:
                    bt_state = fields[4].strip().lower() if len(fields) > 4 else "on"

                ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

                events.append(Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=tz_offset,
                    source_module="device.bluetooth",
                    event_type="bt_event",
                    value_text=bt_state,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                ))

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: parse error: {e}")
                continue

    return events


# Parser registry: maps filename prefix to parser function
PARSER_REGISTRY = {
    "battery_": parse_battery,
    "screen_": parse_screen,
    "charging_": parse_charging,
    "bluetooth_": parse_bluetooth,
}
