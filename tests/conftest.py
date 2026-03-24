"""
Shared pytest fixtures for LifeData test suite.

Provides:
- In-memory SQLite database with schema
- Temporary CSV file builders for each Tasker format
- Pre-built valid Event objects
"""

import os

import pytest

# Ensure project root is importable
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event import Event
from core.database import Database


# ──────────────────────────────────────────────────────────────
# Database fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def db(tmp_path):
    """Provide a fresh Database with schema initialized."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    database.ensure_schema()
    yield database
    database.close()


@pytest.fixture
def db_conn(db):
    """Direct sqlite3 connection for low-level assertions."""
    return db.conn


# ──────────────────────────────────────────────────────────────
# Event fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def valid_event():
    """A minimal valid Event for testing."""
    return Event(
        timestamp_utc="2026-03-24T15:00:00+00:00",
        timestamp_local="2026-03-24T10:00:00-05:00",
        timezone_offset="-0500",
        source_module="device.battery",
        event_type="pulse",
        value_numeric=85.0,
        confidence=1.0,
        parser_version="1.0.0",
    )


@pytest.fixture
def valid_event_factory():
    """Factory fixture: call with overrides to create events."""

    def _make(**kwargs):
        defaults = dict(
            timestamp_utc="2026-03-24T15:00:00+00:00",
            timestamp_local="2026-03-24T10:00:00-05:00",
            timezone_offset="-0500",
            source_module="device.battery",
            event_type="pulse",
            value_numeric=85.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        defaults.update(kwargs)
        return Event(**defaults)

    return _make


# ──────────────────────────────────────────────────────────────
# CSV file fixtures — realistic Tasker formats
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def csv_file_factory(tmp_path):
    """Write a CSV file with given lines. Returns the file path."""

    def _make(filename, lines):
        path = tmp_path / filename
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    return _make


# Device CSV samples
BATTERY_V3_LINES = [
    "1711303200,3-24-26,10:00,85,%TEMP,%MFREE,123456",
    "1711306800,3-24-26,11:00,82,%TEMP,%MFREE,127000",
]

BATTERY_V4_LINES = [
    "1711303200,3-24-26,10:00,-0500,85,28.5,4096,123456",
    "1711306800,3-24-26,11:00,-0500,82,29.0,4000,127000",
]

SCREEN_V3_LINES = [
    "1711303200,3-24-26,10:00,on,85",
    "1711303500,3-24-26,10:05,off,84",
    "1711304100,3-24-26,10:15,on,84",
]

SCREEN_V4_LINES = [
    "1711303200,3-24-26,10:00,-0500,on,85",
    "1711303500,3-24-26,10:05,-0500,off,84",
    "1711304100,3-24-26,10:15,-0500,on,84",
]

CHARGING_V4_LINES = [
    "1711303200,3-24-26,10:00,-0500,charge_start,45",
    "1711310400,3-24-26,12:00,-0500,charge_stop,90",
]

BLUETOOTH_V4_LINES = [
    "1711303200,3-24-26,10:00,-0500,bt_event,on",
    "1711306800,3-24-26,11:00,-0500,bt_event,off",
]

# Environment CSV samples
HOURLY_LINES = [
    "1711303200,3-24-26,10:00,72.5,45,32.7767,-96.7970,15",
    "1711306800,3-24-26,11:00,74.0,42,32.7767,-96.7970,12",
]

GEOFENCE_LINES = [
    "1711303200,32.7767,-96.7970,15,0,1,0",
    "1711306800,32.7800,-96.7950,10,0,1,0",
]

ASTRO_LINES = [
    "1711303200,15,Waxing Gibbous,85.3,12.1",
    "1711389600,16,Waxing Gibbous,91.0,12.2",
]

# Mind CSV samples
MORNING_LINES = [
    "1711278000,3-24-26,07:00,8,1,7,6",
    "1711364400,3-25-26,07:00,6,0,5,4",
]

EVENING_LINES = [
    "1711321200,3-24-26,22:00,7,3,8,6",
    "1711407600,3-25-26,22:00,8,2,7,7",
]

# Social CSV samples
NOTIFICATION_LINES = [
    "1711303200,3-24-26,10:00,com.slack.android,5 messages received",
    "1711303500,3-24-26,10:05,com.google.android.gm,New email from Bob",
]

CALL_LINES = [
    "1711303200,3-24-26,10:00,call,+15551234567,John Doe,180",
    "1711306800,3-24-26,11:00,call,+15559876543,Jane Doe,60",
]

SMS_LINES = [
    "1711303200,3-24-26,10:00,sms_in,+15551234567",
    "1711306800,3-24-26,11:00,sms_out,+15559876543",
]

APP_USAGE_LINES = [
    "1711303200,3-24-26,10:00,com.slack.android,%APP",
    "1711303500,3-24-26,10:05,com.google.chrome,%APP",
]
