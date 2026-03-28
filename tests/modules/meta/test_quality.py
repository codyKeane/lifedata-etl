"""
Tests for modules/meta/quality.py — data quality validators.

Covers: future timestamps, numeric range violations, suspicious duplicates,
time gap detection, and exception handling for all check paths.
"""

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from modules.meta.quality import (
    _check_future_timestamps,
    _check_numeric_ranges,
    _check_suspicious_duplicates,
    _check_time_gaps,
    detect_time_gaps,
    validate_events,
)

# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def mem_db():
    """Create an in-memory SQLite database with the events table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            timestamp_utc TEXT NOT NULL,
            timestamp_local TEXT NOT NULL,
            timezone_offset TEXT,
            source_module TEXT NOT NULL,
            event_type TEXT,
            value_numeric REAL,
            value_text TEXT,
            value_json TEXT,
            tags TEXT,
            confidence REAL,
            parser_version TEXT,
            raw_source_id TEXT
        )
    """)
    conn.commit()

    # Wrap in a mock that behaves like core.database.Database
    db = MagicMock()
    db.execute = lambda sql, params=None: conn.execute(sql, params or [])
    db._conn = conn

    # Helper to insert test events
    def insert(event_id, ts_utc, ts_local, source, value_numeric=None):
        conn.execute(
            "INSERT INTO events (event_id, timestamp_utc, timestamp_local, "
            "source_module, value_numeric) VALUES (?, ?, ?, ?, ?)",
            [event_id, ts_utc, ts_local, source, value_numeric],
        )
        conn.commit()

    db.insert = insert
    yield db
    conn.close()


DATE_STR = "2026-03-20"


# ──────────────────────────────────────────────────────────────
# validate_events — integration
# ──────────────────────────────────────────────────────────────


class TestValidateEvents:
    def test_clean_data_returns_empty(self, mem_db):
        """No data on date → no issues."""
        issues = validate_events(mem_db, DATE_STR)
        assert issues == []

    def test_returns_issues_when_found(self, mem_db):
        """Insert out-of-range data and verify issues are returned."""
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "mind.mood", 15.0)  # Out of range (1-10)
        issues = validate_events(mem_db, DATE_STR)
        assert len(issues) >= 1
        assert any(i["type"] == "numeric_out_of_range" for i in issues)


# ──────────────────────────────────────────────────────────────
# Future timestamps
# ──────────────────────────────────────────────────────────────


class TestFutureTimestamps:
    def test_no_future_timestamps(self, mem_db):
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "device.screen")
        issues = _check_future_timestamps(mem_db)
        assert issues == []

    def test_future_timestamp_detected(self, mem_db):
        future = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
        mem_db.insert("e1", future, future, "device.screen")
        issues = _check_future_timestamps(mem_db)
        assert len(issues) == 1
        assert issues[0]["type"] == "future_timestamps"
        assert issues[0]["count"] > 0

    def test_exception_handled(self):
        """Database error should be caught and return empty list."""
        db = MagicMock()
        db.execute.side_effect = Exception("db error")
        issues = _check_future_timestamps(db)
        assert issues == []


# ──────────────────────────────────────────────────────────────
# Numeric range checks
# ──────────────────────────────────────────────────────────────


class TestNumericRanges:
    def test_in_range_no_issues(self, mem_db):
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "mind.mood", 7.0)
        issues = _check_numeric_ranges(mem_db, DATE_STR)
        assert issues == []

    def test_out_of_range_detected(self, mem_db):
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "mind.mood", 15.0)
        issues = _check_numeric_ranges(mem_db, DATE_STR)
        assert len(issues) >= 1
        mood_issues = [i for i in issues if i["source"] == "mind.mood"]
        assert mood_issues[0]["count"] == 1

    def test_below_range_detected(self, mem_db):
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "device.battery", -5.0)
        issues = _check_numeric_ranges(mem_db, DATE_STR)
        batt_issues = [i for i in issues if i["source"] == "device.battery"]
        assert len(batt_issues) == 1

    def test_exception_handled(self):
        db = MagicMock()
        db.execute.side_effect = Exception("db error")
        issues = _check_numeric_ranges(db, DATE_STR)
        assert issues == []


# ──────────────────────────────────────────────────────────────
# Suspicious duplicates
# ──────────────────────────────────────────────────────────────


class TestSuspiciousDuplicates:
    def test_no_duplicates(self, mem_db):
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "device.screen")
        issues = _check_suspicious_duplicates(mem_db, DATE_STR)
        assert issues == []

    def test_duplicates_detected(self, mem_db):
        """More than 5 events from same source at same second → flagged."""
        ts = "2026-03-20T10:00:00+00:00"
        ts_local = "2026-03-20T05:00:00-05:00"
        for i in range(7):
            mem_db.insert(f"e{i}", ts, ts_local, "device.screen")
        issues = _check_suspicious_duplicates(mem_db, DATE_STR)
        assert len(issues) == 1
        assert issues[0]["type"] == "suspicious_duplicates"
        assert issues[0]["count"] == 7

    def test_exception_handled(self):
        db = MagicMock()
        db.execute.side_effect = Exception("db error")
        issues = _check_suspicious_duplicates(db, DATE_STR)
        assert issues == []


# ──────────────────────────────────────────────────────────────
# Time gap detection
# ──────────────────────────────────────────────────────────────


class TestTimeGaps:
    def test_no_gaps(self, mem_db):
        """Events within normal interval → no gaps."""
        for i in range(5):
            ts = f"2026-03-20T{10 + i}:00:00+00:00"
            ts_local = f"2026-03-20T{5 + i}:00:00-05:00"
            mem_db.insert(f"e{i}", ts, ts_local, "device.battery", 80 - i)
        gaps = detect_time_gaps(mem_db, "device.battery", DATE_STR, max_gap_min=120)
        assert gaps == []

    def test_gap_detected(self, mem_db):
        """Events with a >3-hour gap → flagged."""
        mem_db.insert("e1", "2026-03-20T06:00:00+00:00", "2026-03-20T01:00:00-05:00",
                      "device.battery", 90)
        mem_db.insert("e2", "2026-03-20T12:00:00+00:00", "2026-03-20T07:00:00-05:00",
                      "device.battery", 85)
        gaps = detect_time_gaps(mem_db, "device.battery", DATE_STR, max_gap_min=45)
        assert len(gaps) == 1
        assert gaps[0]["gap_minutes"] == 360

    def test_single_event_no_gaps(self, mem_db):
        """Single event → no gap possible."""
        mem_db.insert("e1", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00",
                      "device.battery", 90)
        gaps = detect_time_gaps(mem_db, "device.battery", DATE_STR, max_gap_min=45)
        assert gaps == []

    def test_exception_handled(self):
        db = MagicMock()
        db.execute.side_effect = Exception("db error")
        gaps = detect_time_gaps(db, "device.battery", DATE_STR, max_gap_min=45)
        assert gaps == []

    def test_invalid_timestamp_skipped(self, mem_db):
        """Invalid timestamp format should be skipped, not crash."""
        conn = mem_db._conn
        conn.execute(
            "INSERT INTO events (event_id, timestamp_utc, timestamp_local, source_module) "
            "VALUES (?, ?, ?, ?)",
            ["e1", "not-a-timestamp", "2026-03-20T05:00:00-05:00", "device.battery"],
        )
        conn.execute(
            "INSERT INTO events (event_id, timestamp_utc, timestamp_local, source_module) "
            "VALUES (?, ?, ?, ?)",
            ["e2", "2026-03-20T10:00:00+00:00", "2026-03-20T05:00:00-05:00", "device.battery"],
        )
        conn.commit()
        # Should not crash — just skip the bad timestamp
        gaps = detect_time_gaps(mem_db, "device.battery", DATE_STR, max_gap_min=45)
        assert isinstance(gaps, list)


# ──────────────────────────────────────────────────────────────
# _check_time_gaps integration
# ──────────────────────────────────────────────────────────────


class TestCheckTimeGapsIntegration:
    def test_periodic_gap_produces_issue(self, mem_db):
        """Gap in a periodic source should produce an issue via _check_time_gaps."""
        mem_db.insert("e1", "2026-03-20T06:00:00+00:00", "2026-03-20T01:00:00-05:00",
                      "device.battery", 90)
        mem_db.insert("e2", "2026-03-20T12:00:00+00:00", "2026-03-20T07:00:00-05:00",
                      "device.battery", 85)
        issues = _check_time_gaps(mem_db, DATE_STR)
        gap_issues = [i for i in issues if i["type"] == "data_gap" and i["source"] == "device.battery"]
        assert len(gap_issues) >= 1
        assert gap_issues[0]["gap_minutes"] == 360
