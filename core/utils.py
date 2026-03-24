"""
LifeData V4 — Utility Functions
core/utils.py

Shared utilities for timestamp parsing, file discovery, safe type conversion,
and JSON serialization. Used by all modules and the orchestrator.
"""

import glob
import json
import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def parse_timestamp(
    raw: str, tz_offset: str = "-0500", local_tz: str = "America/Chicago"
) -> tuple[str, str]:
    """Parse various timestamp formats into (UTC ISO 8601, local ISO 8601).

    Handles:
        - Unix epoch seconds:     '1711100400'
        - Unix epoch milliseconds: '1711100400000'
        - ISO 8601 with tz:       '2026-03-22T14:30:00-05:00'
        - Local datetime string:  '2026-03-22 14:30:00'

    Args:
        raw: The raw timestamp string to parse.
        tz_offset: Timezone offset from Tasker %TIMEZONE, e.g. '-0500'.
        local_tz: Fallback IANA timezone name if tz_offset is unavailable.

    Returns:
        Tuple of (utc_iso_str, local_iso_str).

    Raises:
        ValueError: If the timestamp format cannot be parsed.
    """
    raw = raw.strip()
    dt_utc: datetime

    # Try epoch seconds / milliseconds
    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        epoch = int(raw)
        # If >10 digits, assume milliseconds
        if epoch > 9_999_999_999:
            epoch = epoch // 1000
        dt_utc = datetime.fromtimestamp(epoch, tz=timezone.utc)
    elif "T" in raw and ("+" in raw[10:] or raw.endswith("Z") or "-" in raw[10:]):
        # ISO 8601 with timezone info
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt_utc = datetime.fromisoformat(raw).astimezone(timezone.utc)
    else:
        # Assume local datetime string — use tz_offset to determine UTC
        try:
            offset_hours = int(tz_offset[:3])
            offset_minutes = int(tz_offset[0] + tz_offset[3:5])  # preserve sign
        except (ValueError, IndexError):
            offset_hours, offset_minutes = -5, 0  # CST fallback

        from datetime import timedelta

        tz_info = timezone(timedelta(hours=offset_hours, minutes=offset_minutes))

        try:
            dt_local = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt_local = datetime.strptime(raw, "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError(
                    f"Cannot parse timestamp: '{raw}' "
                    f"(tried epoch, ISO 8601, and local datetime formats)"
                )
        dt_local = dt_local.replace(tzinfo=tz_info)
        dt_utc = dt_local.astimezone(timezone.utc)

    # Compute local time from UTC using the provided offset
    local_dt = _utc_to_local(dt_utc, tz_offset)

    return dt_utc.isoformat(), local_dt.isoformat()


def _utc_to_local(dt_utc: datetime, tz_offset: str) -> datetime:
    """Convert a UTC datetime to local time using a Tasker-style offset string.

    Args:
        dt_utc: UTC datetime.
        tz_offset: Offset string like '-0500', '+0530'.

    Returns:
        Local datetime with the appropriate timezone.
    """
    from datetime import timedelta

    try:
        sign = 1 if tz_offset[0] == "+" else -1
        hours = int(tz_offset[1:3]) if len(tz_offset) >= 3 else 0
        minutes = int(tz_offset[3:5]) if len(tz_offset) >= 5 else 0
        offset = timedelta(hours=sign * hours, minutes=sign * minutes)
    except (ValueError, IndexError):
        offset = timedelta(hours=-5)  # CST fallback

    tz_info = timezone(offset)
    return dt_utc.astimezone(tz_info)


def format_offset(tz_offset: str) -> str:
    """Normalize a timezone offset string to the 4-char format used in the schema.

    Examples:
        '-0500' -> '-0500'
        '-5'    -> '-0500'
        '+0530' -> '+0530'
        '+05:30' -> '+0530'
    """
    tz_offset = tz_offset.strip().replace(":", "")
    if len(tz_offset) == 2:
        # e.g., '-5' -> '-0500'
        return f"{tz_offset[0]}0{tz_offset[1]}00"
    if len(tz_offset) == 3:
        # e.g., '-05' -> '-0500'
        return f"{tz_offset}00"
    return tz_offset


def glob_files(
    directory: str,
    pattern: str = "*.csv",
    recursive: bool = True,
) -> list[str]:
    """Find files matching a glob pattern within a directory.

    Args:
        directory: Base directory to search.
        pattern: Glob pattern (default: '*.csv').
        recursive: Whether to search subdirectories.

    Returns:
        Sorted list of absolute file paths.
    """
    expanded = os.path.expanduser(directory)
    if recursive:
        full_pattern = os.path.join(expanded, "**", pattern)
        files = glob.glob(full_pattern, recursive=True)
    else:
        full_pattern = os.path.join(expanded, pattern)
        files = glob.glob(full_pattern)
    return sorted(files)


def safe_float(value) -> Optional[float]:
    """Parse a value to float, returning None on failure.

    Handles strings, ints, floats, and None gracefully.
    Never raises an exception.
    """
    if value is None:
        return None
    try:
        result = float(value)
        # Reject NaN and Inf — these corrupt database queries
        if result != result or result == float("inf") or result == float("-inf"):
            return None
        return result
    except (ValueError, TypeError):
        return None


def safe_int(value) -> Optional[int]:
    """Parse a value to int, returning None on failure.

    Never raises an exception.
    """
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def safe_json(obj) -> str:
    """Serialize an object to a JSON string.

    Handles edge cases: None values, non-serializable types converted to str.
    """
    if obj is None:
        return "{}"
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps({"raw": str(obj)})


def today_local(tz_name: str = "America/Chicago") -> str:
    """Return today's date as YYYY-MM-DD in the given timezone."""
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).strftime("%Y-%m-%d")


def now_utc_iso() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
