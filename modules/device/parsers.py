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

Each parser uses safe_parse_rows() from core.parser_utils for standardized
per-row error handling, logging, and quarantine detection.
"""

from typing import Optional

from core.event import Event
from core.logger import get_logger
from core.parser_utils import ParseResult, safe_parse_rows
from core.utils import parse_timestamp, safe_float, safe_int, safe_json

log = get_logger("lifedata.device.parsers")

# Default timezone offset when v3 CSVs don't include %TIMEZONE
DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"


def _is_unresolved(value: str) -> bool:
    """Check if a Tasker variable was not resolved (still starts with %)."""
    return value.startswith("%") if value else True


# ──────────────────────────────────────────────────────────────
# Row-level parsers (called by safe_parse_rows)
# ──────────────────────────────────────────────────────────────


def _parse_battery_row(fields: list[str], line_num: int) -> Optional[Event]:
    """Parse a single battery CSV row → Event or None."""
    epoch_str = fields[0].strip()
    if not epoch_str.isdigit():
        return None  # non-epoch line (header, etc.)

    # Detect v4 format (has timezone field)
    tz_offset = DEFAULT_TZ_OFFSET
    if len(fields) >= 8 and not _is_unresolved(fields[3]):
        tz_offset = fields[3].strip()
        batt_pct = safe_float(fields[4])
        temp_str = fields[5].strip()
        mem_str = fields[6].strip()
        uptime_str = fields[7].strip() if len(fields) > 7 else None
    else:
        batt_pct = safe_float(fields[3])
        temp_str = fields[4].strip() if len(fields) > 4 else ""
        mem_str = fields[5].strip() if len(fields) > 5 else ""
        uptime_str = fields[6].strip() if len(fields) > 6 else None

    if batt_pct is None:
        return None  # no battery percentage — skip

    ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

    extra = {}
    temp = safe_float(temp_str) if not _is_unresolved(temp_str) else None
    mem_free = safe_int(mem_str) if not _is_unresolved(mem_str) else None
    uptime = (
        safe_int(uptime_str)
        if uptime_str and not _is_unresolved(uptime_str)
        else None
    )

    if temp is not None:
        extra["temp_c"] = temp
    if mem_free is not None:
        extra["mem_free_mb"] = mem_free
    if uptime is not None:
        extra["uptime_sec"] = uptime

    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=tz_offset,
        source_module="device.battery",
        event_type="pulse",
        value_numeric=batt_pct,
        value_json=safe_json(extra) if extra else None,
        confidence=1.0,
        parser_version=PARSER_VERSION,
    )


def _parse_screen_row(fields: list[str], line_num: int) -> Optional[Event]:
    """Parse a single screen CSV row → Event or None."""
    if len(fields) < 4:
        return None

    epoch_str = fields[0].strip()
    if not epoch_str.isdigit():
        return None

    tz_offset = DEFAULT_TZ_OFFSET
    if len(fields) >= 5 and fields[3].strip().lstrip("+-").isdigit():
        tz_offset = fields[3].strip()
        state = fields[4].strip().lower()
        batt_pct = safe_float(fields[5]) if len(fields) > 5 else None
    else:
        state = fields[3].strip().lower()
        batt_pct = safe_float(fields[4]) if len(fields) > 4 else None

    if state not in ("on", "off"):
        return None

    ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

    extra = {}
    if batt_pct is not None:
        extra["battery_pct"] = batt_pct

    return Event(
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
    )


def _parse_charging_row(fields: list[str], line_num: int) -> Optional[Event]:
    """Parse a single charging CSV row → Event or None."""
    if len(fields) < 4:
        return None

    epoch_str = fields[0].strip()
    if not epoch_str.isdigit():
        return None

    tz_offset = DEFAULT_TZ_OFFSET
    if len(fields) >= 5 and fields[3].strip().lstrip("+-").isdigit():
        tz_offset = fields[3].strip()
        state = fields[4].strip().lower()
        batt_pct = safe_float(fields[5]) if len(fields) > 5 else None
    else:
        state = fields[3].strip().lower()
        batt_pct = safe_float(fields[4]) if len(fields) > 4 else None

    if state not in ("charge_start", "charge_stop"):
        return None

    ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=tz_offset,
        source_module="device.charging",
        event_type=state,
        value_numeric=batt_pct,
        confidence=1.0,
        parser_version=PARSER_VERSION,
    )


def _parse_bluetooth_row(fields: list[str], line_num: int) -> Optional[Event]:
    """Parse a single bluetooth CSV row → Event or None."""
    if len(fields) < 4:
        return None

    epoch_str = fields[0].strip()
    if not epoch_str.isdigit():
        return None

    tz_offset = DEFAULT_TZ_OFFSET
    if len(fields) >= 6 and fields[3].strip().lstrip("+-").isdigit():
        tz_offset = fields[3].strip()
        bt_state = fields[5].strip().lower() if len(fields) > 5 else "on"
    else:
        bt_state = fields[4].strip().lower() if len(fields) > 4 else "on"

    ts_utc, ts_local = parse_timestamp(epoch_str, tz_offset)

    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=tz_offset,
        source_module="device.bluetooth",
        event_type="bt_event",
        value_text=bt_state,
        confidence=1.0,
        parser_version=PARSER_VERSION,
    )


# ──────────────────────────────────────────────────────────────
# Public parser functions (use safe_parse_rows)
# ──────────────────────────────────────────────────────────────


def parse_battery(file_path: str) -> list[Event]:
    """Parse battery pulse CSV.

    v3 format: epoch,date,time,battery_pct,%TEMP,%MFREE,uptime
    v4 format: epoch,date,time,timezone,battery_pct,temp,mem_free,uptime
    """
    result = safe_parse_rows(file_path, _parse_battery_row, "device")
    return result.events


def parse_screen(file_path: str) -> list[Event]:
    """Parse screen on/off CSV.

    v3 format: epoch,date,time,on|off,battery_pct
    v4 format: epoch,date,time,timezone,on|off,battery_pct
    """
    result = safe_parse_rows(file_path, _parse_screen_row, "device")
    return result.events


def parse_charging(file_path: str) -> list[Event]:
    """Parse charging start/stop CSV.

    v3 format: epoch,date,time,charge_start|charge_stop,battery_pct
    v4 format: epoch,date,time,timezone,charge_start|charge_stop,battery_pct
    """
    result = safe_parse_rows(file_path, _parse_charging_row, "device")
    return result.events


def parse_bluetooth(file_path: str) -> list[Event]:
    """Parse bluetooth event CSV.

    v3 format: epoch,date,time,bt_event,on|off
    v4 format: epoch,date,time,timezone,bt_event,on|off
    """
    result = safe_parse_rows(file_path, _parse_bluetooth_row, "device")
    return result.events


# ──────────────────────────────────────────────────────────────
# Extended API: return full ParseResult with quarantine info
# ──────────────────────────────────────────────────────────────


def parse_battery_safe(file_path: str) -> ParseResult:
    """Parse battery CSV, returning full ParseResult with quarantine status."""
    return safe_parse_rows(file_path, _parse_battery_row, "device")


def parse_screen_safe(file_path: str) -> ParseResult:
    """Parse screen CSV, returning full ParseResult with quarantine status."""
    return safe_parse_rows(file_path, _parse_screen_row, "device")


def parse_charging_safe(file_path: str) -> ParseResult:
    """Parse charging CSV, returning full ParseResult with quarantine status."""
    return safe_parse_rows(file_path, _parse_charging_row, "device")


def parse_bluetooth_safe(file_path: str) -> ParseResult:
    """Parse bluetooth CSV, returning full ParseResult with quarantine status."""
    return safe_parse_rows(file_path, _parse_bluetooth_row, "device")


# Parser registry: maps filename prefix to parser function
PARSER_REGISTRY = {
    "battery_": parse_battery,
    "screen_": parse_screen,
    "charging_": parse_charging,
    "bluetooth_": parse_bluetooth,
}

# Safe parser registry: returns ParseResult with quarantine info
SAFE_PARSER_REGISTRY = {
    "battery_": parse_battery_safe,
    "screen_": parse_screen_safe,
    "charging_": parse_charging_safe,
    "bluetooth_": parse_bluetooth_safe,
}
