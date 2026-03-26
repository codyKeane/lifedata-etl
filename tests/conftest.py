"""
Shared pytest fixtures for LifeData test suite.

Provides:
- In-memory SQLite database with schema
- Temporary CSV file builders for each Tasker format
- Pre-built valid Event objects
- Comprehensive sample_config, sample_events, sample_csv_dir fixtures
- Populated database fixture for integration tests
"""

import json
import os
import sys

import pytest

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present, and ensure PII_HMAC_KEY is set for tests.
# This must happen before any module import (social parsers checks at import time).
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"), override=False)
if not os.environ.get("PII_HMAC_KEY"):
    os.environ["PII_HMAC_KEY"] = "test-only-hmac-key-not-for-production"

from core.event import Event
from core.database import Database
from core.config_schema import (
    LifeDataConfig,
    SecurityConfig,
    ModulesConfig,
    AnalysisConfig,
    RetentionConfig,
    ScheduleConfig,
)


# ──────────────────────────────────────────────────────────────
# Timestamps — realistic dates within the past week (America/Chicago)
# Base: 2026-03-20 08:00 CDT  (UTC-5 during CDT)
# ──────────────────────────────────────────────────────────────

_BASE_EPOCH = 1742475600  # 2026-03-20T13:00:00Z = 2026-03-20T08:00:00-05:00
_TZ_OFFSET = "-0500"


def _ts(offset_minutes: int = 0) -> tuple[str, str]:
    """Return (timestamp_utc, timestamp_local) offset from base by minutes."""
    from datetime import datetime, timedelta, timezone as tz

    utc_dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=tz.utc) + timedelta(
        minutes=offset_minutes
    )
    local_dt = utc_dt - timedelta(hours=5)
    return (
        utc_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        local_dt.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
    )


def _epoch(offset_minutes: int = 0) -> str:
    """Return epoch string offset from base by minutes."""
    return str(_BASE_EPOCH + offset_minutes * 60)


# ──────────────────────────────────────────────────────────────
# Config fixture
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def sample_config(tmp_path):
    """Return a valid LifeDataConfig pointing to tmp_path directories."""
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    raw_dir = tmp_path / "raw" / "LifeData"
    raw_dir.mkdir(parents=True)
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    return LifeDataConfig(
        version="4.0",
        timezone="America/Chicago",
        db_path=str(db_dir / "lifedata.db"),
        raw_base=str(raw_dir),
        media_base=str(media_dir),
        reports_dir=str(reports_dir),
        log_path=str(logs_dir / "etl.log"),
        security=SecurityConfig(
            syncthing_relay_enabled=False,
            module_allowlist=[
                "device",
                "environment",
                "body",
                "mind",
                "social",
            ],
        ),
        modules=ModulesConfig(),
        analysis=AnalysisConfig(),
        retention=RetentionConfig(),
        schedule=ScheduleConfig(),
    )


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
def tmp_database(tmp_path):
    """Fresh SQLite database with full schema (events, modules, media,
    daily_summaries, correlations, events_fts). Tears down after use."""
    db_path = str(tmp_path / "lifedata_test.db")
    database = Database(db_path)
    database.ensure_schema()

    # Verify all six tables exist
    tables = {
        row[0]
        for row in database.conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }
    expected = {"events", "modules", "media", "daily_summaries", "correlations"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"

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


@pytest.fixture
def sample_events():
    """Return 20 realistic Event objects spanning multiple modules.

    Distribution:
    - 5 device.screen events (mix of on/off, varying battery levels)
    - 3 device.battery pulse events (15 min apart)
    - 3 environment.weather events
    - 2 environment.geomagnetic events (Kp=2 and Kp=5)
    - 3 mind.mood check_ins (values 4, 7, 8)
    - 2 social.notification events
    - 1 body.caffeine event
    - 1 mind.synchronicity event with value_text
    """
    events = []

    # ── 5 device.screen events (on/off alternating) ──────────
    screen_states = [
        ("screen_on", "on", 92.0),
        ("screen_off", "off", 91.0),
        ("screen_on", "on", 88.0),
        ("screen_off", "off", 87.0),
        ("screen_on", "on", 85.0),
    ]
    for i, (etype, text, batt) in enumerate(screen_states):
        utc, local = _ts(offset_minutes=i * 12)  # ~12 min apart
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="device.screen",
                event_type=etype,
                value_numeric=batt,
                value_text=text,
                tags="screen,device",
                confidence=1.0,
                parser_version="1.0.0",
            )
        )

    # ── 3 device.battery pulse events (15 min apart) ─────────
    battery_levels = [91.0, 89.0, 87.0]
    for i, batt in enumerate(battery_levels):
        utc, local = _ts(offset_minutes=120 + i * 15)
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="device.battery",
                event_type="pulse",
                value_numeric=batt,
                value_json=json.dumps(
                    {
                        "temp_c": 28.5 + i * 0.3,
                        "mem_free_mb": 4096 - i * 50,
                        "uptime_sec": 123456 + i * 900,
                    }
                ),
                tags="battery,device",
                confidence=1.0,
                parser_version="1.0.0",
            )
        )

    # ── 3 environment.weather events ─────────────────────────
    weather_data = [
        (72.5, 45, "partly cloudy"),
        (74.0, 42, "sunny"),
        (68.3, 58, "overcast"),
    ]
    for i, (temp_f, humidity, condition) in enumerate(weather_data):
        utc, local = _ts(offset_minutes=180 + i * 60)
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="environment.weather",
                event_type="snapshot",
                value_numeric=temp_f,
                value_text=condition,
                value_json=json.dumps(
                    {
                        "temp_f": temp_f,
                        "temp_c": round((temp_f - 32) * 5 / 9, 1),
                        "humidity_pct": humidity,
                    }
                ),
                location_lat=32.7767,
                location_lon=-96.7970,
                tags="weather,environment",
                confidence=1.0,
                parser_version="1.0.0",
            )
        )

    # ── 2 environment.geomagnetic events (Kp=2 and Kp=5) ────
    for i, kp in enumerate([2.0, 5.0]):
        utc, local = _ts(offset_minutes=360 + i * 180)
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="environment.geomagnetic",
                event_type="kp_index",
                value_numeric=kp,
                value_json=json.dumps({"kp": kp, "source": "noaa"}),
                tags="geomagnetic,space_weather",
                confidence=0.9,
                parser_version="1.0.0",
            )
        )

    # ── 3 mind.mood check_ins (values 4, 7, 8) ──────────────
    mood_data = [
        (4.0, "morning", 480),
        (7.0, "afternoon", 780),
        (8.0, "evening", 1320),
    ]
    for value, period, offset_min in mood_data:
        utc, local = _ts(offset_minutes=offset_min)
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="mind.mood",
                event_type="check_in",
                value_numeric=value,
                value_text=period,
                tags=f"check_in,{period},manual",
                confidence=1.0,
                parser_version="1.0.0",
            )
        )

    # ── 2 social.notification events ─────────────────────────
    notif_data = [
        ("com.slack.android", "3 new messages in #general"),
        ("com.google.android.gm", "New email from Alice"),
    ]
    for i, (app, text) in enumerate(notif_data):
        utc, local = _ts(offset_minutes=200 + i * 30)
        events.append(
            Event(
                timestamp_utc=utc,
                timestamp_local=local,
                timezone_offset=_TZ_OFFSET,
                source_module="social.notification",
                event_type="received",
                value_text=text,
                value_json=json.dumps(
                    {"app": app, "app_short": app.split(".")[-1]}
                ),
                tags="notification,social",
                confidence=1.0,
                parser_version="1.0.0",
            )
        )

    # ── 1 body.caffeine event ────────────────────────────────
    utc, local = _ts(offset_minutes=90)
    events.append(
        Event(
            timestamp_utc=utc,
            timestamp_local=local,
            timezone_offset=_TZ_OFFSET,
            source_module="body.caffeine",
            event_type="intake",
            value_numeric=200.0,
            value_json=json.dumps({"unit": "mg"}),
            tags="caffeine,body,quicklog",
            confidence=1.0,
            parser_version="1.0.0",
        )
    )

    # ── 1 mind.synchronicity event with value_text ───────────
    utc, local = _ts(offset_minutes=600)
    events.append(
        Event(
            timestamp_utc=utc,
            timestamp_local=local,
            timezone_offset=_TZ_OFFSET,
            source_module="mind.synchronicity",
            event_type="observation",
            value_text="Saw 11:11 on clock, then received call from person I was thinking about",
            tags="synchronicity,mind",
            confidence=0.8,
            parser_version="1.0.0",
        )
    )

    assert len(events) == 20, f"Expected 20 events, got {len(events)}"
    return events


# ──────────────────────────────────────────────────────────────
# Populated database fixture
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def populated_database(tmp_database, sample_events):
    """Database with all 20 sample_events inserted. Returns the Database object."""
    inserted, skipped = tmp_database.insert_events_for_module(
        "test_fixture", sample_events
    )
    assert inserted == 20, f"Expected 20 inserted, got {inserted} (skipped {skipped})"
    return tmp_database


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


@pytest.fixture
def sample_csv_dir(tmp_path):
    """Create a tmp_path directory structure mimicking raw/LifeData/LifeData/logs/
    with realistic CSV files for each module's expected format.

    Includes:
    - Well-formed screen CSV (10 rows)
    - Well-formed battery CSV (5 rows)
    - Malformed CSV (truncated mid-line, simulating Syncthing mid-sync)
    - CSV with a future timestamp
    - CSV with an empty row
    - CSV with non-UTF8 characters
    - Zero-byte file

    Returns the path to the logs directory.
    """
    logs_dir = tmp_path / "raw" / "LifeData" / "LifeData" / "logs"
    logs_dir.mkdir(parents=True)

    # ── Well-formed screen CSV — 10 rows (v4 format) ─────────
    screen_rows = []
    for i in range(10):
        epoch = _BASE_EPOCH + i * 720  # 12 min apart
        state = "on" if i % 2 == 0 else "off"
        batt = 95 - i
        screen_rows.append(f"{epoch},3-20-26,{8 + i // 5}:{(i * 12) % 60:02d},-0500,{state},{batt}")
    screen_path = logs_dir / "screen_2026-03-20.csv"
    screen_path.write_text("\n".join(screen_rows) + "\n", encoding="utf-8")

    # ── Well-formed battery CSV — 5 rows (v4 format) ─────────
    battery_rows = []
    for i in range(5):
        epoch = _BASE_EPOCH + i * 900  # 15 min apart
        batt = 90 - i * 2
        temp = 28.0 + i * 0.5
        mem = 4096 - i * 100
        uptime = 100000 + i * 900
        battery_rows.append(
            f"{epoch},3-20-26,{8 + i // 4}:{(i * 15) % 60:02d},-0500,{batt},{temp},{mem},{uptime}"
        )
    battery_path = logs_dir / "battery_2026-03-20.csv"
    battery_path.write_text("\n".join(battery_rows) + "\n", encoding="utf-8")

    # ── Malformed CSV (truncated mid-line) ────────────────────
    malformed_path = logs_dir / "screen_2026-03-19_malformed.csv"
    malformed_content = (
        f"{_BASE_EPOCH - 86400},3-19-26,10:00,-0500,on,85\n"
        f"{_BASE_EPOCH - 85680},3-19-26,10:12,-0500,off,84\n"
        f"{_BASE_EPOCH - 84960},3-19-26,10:24,-0500,on"  # truncated — no newline, missing battery
    )
    malformed_path.write_text(malformed_content, encoding="utf-8")

    # ── CSV with a future timestamp ───────────────────────────
    future_path = logs_dir / "screen_2026-04-01_future.csv"
    future_epoch = _BASE_EPOCH + 86400 * 30  # 30 days in the future
    future_content = f"{future_epoch},4-19-26,10:00,-0500,on,75\n"
    future_path.write_text(future_content, encoding="utf-8")

    # ── CSV with an empty row ─────────────────────────────────
    empty_row_path = logs_dir / "battery_2026-03-19_emptyrow.csv"
    empty_row_content = (
        f"{_BASE_EPOCH - 86400},3-19-26,09:00,-0500,88,27.5,4200,99000\n"
        "\n"
        f"{_BASE_EPOCH - 85500},3-19-26,09:15,-0500,87,27.8,4150,99900\n"
    )
    empty_row_path.write_text(empty_row_content, encoding="utf-8")

    # ── CSV with non-UTF8 characters ──────────────────────────
    non_utf8_path = logs_dir / "notifications_2026-03-20_badenc.csv"
    non_utf8_content = (
        f"{_BASE_EPOCH},3-20-26,10:00,com.slack.android,Hello world\n"
        f"{_BASE_EPOCH + 300},3-20-26,10:05,com.test.app,"
    )
    non_utf8_path.write_bytes(
        non_utf8_content.encode("utf-8") + b"\xff\xfe Bad bytes\n"
    )

    # ── Zero-byte file ────────────────────────────────────────
    zero_path = logs_dir / "screen_2026-03-18_empty.csv"
    zero_path.write_bytes(b"")

    return logs_dir


# ──────────────────────────────────────────────────────────────
# CSV sample constants — used by module parser tests
# ──────────────────────────────────────────────────────────────

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

# Body CSV samples
QUICKLOG_CAFFEINE_LINES = [
    "1711278000,3-24-26,07:00,1,200,home",
]

QUICKLOG_MEAL_LINES = [
    "1711303200,3-24-26,10:00,10,Oatmeal with blueberries,home",
]
