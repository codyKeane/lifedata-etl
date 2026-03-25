"""
LifeData V4 — Social Module Parsers
modules/social/parsers.py

Parses Tasker-generated CSV files for social/communication data:
  - notifications_*.csv → social.notification
  - calls_*.csv         → social.call
  - sms_*.csv           → social.sms
  - app_usage_*.csv     → social.app_usage
  - wifi_*.csv          → social.wifi (network/connectivity events)
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from core.event import Event
from core.logger import get_logger
from core.utils import parse_timestamp, safe_float, safe_json

log = get_logger("lifedata.social.parsers")

DEFAULT_TZ_OFFSET = "-0500"
PARSER_VERSION = "1.0.0"

# Per-installation HMAC key for PII hashing. Uses PII_HMAC_KEY from .env if
# available, otherwise falls back to a machine-specific key derived from
# the hostname. This prevents rainbow-table reversal of hashed contacts.
_PII_HMAC_KEY: bytes = os.environ.get(
    "PII_HMAC_KEY",
    f"lifedata-pii-{os.uname().nodename}",
).encode("utf-8")


def _hash_contact(name: str) -> str:
    """Hash a contact name for privacy (THETA spec requirement).

    Uses HMAC-SHA256 with a per-installation key, truncated to 16 hex chars.
    The HMAC key prevents rainbow-table reversal if the DB is exposed.
    """
    if not name or name.startswith("%"):
        return "unknown"
    return hmac.new(_PII_HMAC_KEY, name.encode("utf-8"), hashlib.sha256).hexdigest()[
        :16
    ]


def _hash_phone(number: str) -> str:
    """Hash a phone number for privacy.

    Uses HMAC-SHA256 with a per-installation key, truncated to 16 hex chars.
    Phone numbers have a small input space (~10B US numbers), so the HMAC
    key is essential to prevent brute-force reversal.
    """
    if not number or number.startswith("%"):
        return "unknown"
    # Normalize: strip spaces, dashes, parens
    clean = "".join(c for c in number if c.isdigit() or c == "+")
    return hmac.new(_PII_HMAC_KEY, clean.encode("utf-8"), hashlib.sha256).hexdigest()[
        :16
    ]


def parse_notifications(file_path: str) -> list[Event]:
    """Parse notification log CSV.

    Format: epoch,date,time,app_package,notification_text
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                # Split on comma, but the notification text may contain commas
                # So split on first 4 commas only
                parts = line.split(",", 4)
                if len(parts) < 4:
                    continue

                epoch_str = parts[0].strip()
                if not epoch_str.isdigit():
                    continue

                app_package = parts[3].strip()
                notif_text = parts[4].strip() if len(parts) > 4 else ""

                ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)

                # Extract app name from package (last segment)
                app_short = (
                    app_package.rsplit(".", 1)[-1]
                    if "." in app_package
                    else app_package
                )

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="social.notification",
                        event_type="received",
                        value_text=notif_text[:500],  # Truncate long notification text
                        value_json=safe_json(
                            {"app": app_package, "app_short": app_short}
                        ),
                        tags=app_short,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: notification parse error: {e}")
                continue

    return events


def parse_calls(file_path: str) -> list[Event]:
    """Parse call log CSV.

    Format: epoch,date,time,call,phone_number,contact_name,%CDUR
    Contact names and phone numbers are hashed for privacy.
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

                call_type = fields[3].strip() if len(fields) > 3 else "call"
                phone_raw = fields[4].strip() if len(fields) > 4 else ""
                contact_raw = fields[5].strip() if len(fields) > 5 else ""
                duration_raw = fields[6].strip() if len(fields) > 6 else ""

                # Hash PII
                phone_hash = _hash_phone(phone_raw)
                contact_hash = _hash_contact(contact_raw)

                extra: dict[str, Any] = {
                    "contact_hash": contact_hash,
                    "phone_hash": phone_hash,
                }

                # Duration might be unresolved Tasker variable
                duration = (
                    safe_float(duration_raw)
                    if not duration_raw.startswith("%")
                    else None
                )
                if duration is not None:
                    extra["duration_sec"] = duration

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="social.call",
                        event_type=call_type,
                        value_numeric=duration,
                        value_json=safe_json(extra),
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: call parse error: {e}")
                continue

    return events


def parse_sms(file_path: str) -> list[Event]:
    """Parse SMS log CSV.

    Format: epoch,date,time,sms_in|sms_out,phone_number
    Phone numbers are hashed for privacy.
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

                sms_type = fields[3].strip() if len(fields) > 3 else "sms"
                phone_raw = fields[4].strip() if len(fields) > 4 else ""

                phone_hash = _hash_phone(phone_raw)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="social.sms",
                        event_type=sms_type,
                        value_text=phone_hash,
                        value_json=safe_json({"phone_hash": phone_hash}),
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: sms parse error: {e}")
                continue

    return events


def parse_app_usage(file_path: str) -> list[Event]:
    """Parse app usage CSV.

    Format: epoch,date,time,app_name,%APP
    The %APP Tasker variable may be unresolved.
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
                app_name = fields[3].strip()

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="social.app_usage",
                        event_type="foreground",
                        value_text=app_name,
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )

            except Exception as e:
                log.warning(f"{file_path}:{line_num}: app_usage parse error: {e}")
                continue

    return events


def parse_wifi(file_path: str) -> list[Event]:
    """Parse WiFi connection CSV.

    Format: epoch,date,time,connected|disconnected,wifi_data...
    Multi-line WiFi data follows — we only parse the CSV summary line.
    """
    events = []
    with open(file_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    import re

    # Only parse lines starting with epoch timestamps
    lines = content.split("\n")
    csv_lines = [
        line for line in lines if line.strip() and re.match(r"^\d{10,}", line.strip())
    ]

    for line in csv_lines:
        try:
            fields = line.strip().split(",")
            if len(fields) < 4:
                continue

            epoch_str = fields[0].strip()
            if not epoch_str.isdigit():
                continue

            ts_utc, ts_local = parse_timestamp(epoch_str, DEFAULT_TZ_OFFSET)
            state = fields[3].strip().lower()

            if state not in ("connected", "disconnected"):
                continue

            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset=DEFAULT_TZ_OFFSET,
                    source_module="social.wifi",
                    event_type=state,
                    value_text=state,
                    confidence=1.0,
                    parser_version=PARSER_VERSION,
                )
            )

        except Exception as e:
            log.warning(f"{file_path}: wifi parse error: {e}")
            continue

    return events


PARSER_REGISTRY = {
    "notifications_": parse_notifications,
    "calls_": parse_calls,
    "sms_": parse_sms,
    "app_usage_": parse_app_usage,
    "wifi_": parse_wifi,
}
