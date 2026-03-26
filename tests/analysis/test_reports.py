"""
Tests for analysis/reports.py — daily report generation and sparkline helper.
"""

import os
from datetime import UTC, datetime, timedelta

from core.event import Event
from analysis.reports import generate_daily_report, _sparkline


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

_DATE_STR = "2026-03-20"


def _make_event(source_module, event_type="measurement", value_numeric=None,
                value_text=None, value_json=None, date_str=_DATE_STR,
                hour=12):
    """Create an Event on the given date at the given hour (CDT = UTC-5)."""
    utc = f"{date_str}T{hour + 5:02d}:00:00+00:00"
    local = f"{date_str}T{hour:02d}:00:00-05:00"
    return Event(
        timestamp_utc=utc,
        timestamp_local=local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        value_json=value_json,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _make_config(tmp_path):
    """Return a config dict with reports_dir pointing to tmp_path."""
    return {
        "lifedata": {
            "timezone": "America/Chicago",
            "reports_dir": str(tmp_path / "reports"),
        }
    }


def _insert_sample_events(db):
    """Insert a variety of events for date 2026-03-20 across several modules."""
    events = [
        _make_event("device.battery", "pulse", value_numeric=91.0, hour=8),
        _make_event("device.battery", "pulse", value_numeric=87.0, hour=10),
        _make_event("device.battery", "pulse", value_numeric=83.0, hour=12),
        _make_event("device.screen", "screen_on", value_numeric=90.0, hour=8),
        _make_event("device.screen", "screen_off", value_numeric=89.0, hour=9),
        _make_event("device.charging", "charge_start", value_numeric=45.0, hour=11),
        _make_event("environment.hourly", "snapshot", value_numeric=72.0, hour=9),
        _make_event("environment.hourly", "snapshot", value_numeric=78.0, hour=12),
        _make_event("environment.location", "fix", value_numeric=None, hour=10),
        _make_event("social.notification", "received", value_text="New message", hour=10),
        _make_event("social.notification", "received", value_text="Reminder", hour=14),
        _make_event("mind.mood", "check_in", value_numeric=7.0, hour=9),
        _make_event("mind.mood", "check_in", value_numeric=8.0, hour=18),
    ]
    db.insert_events_for_module("test_reports", events)
    return events


# ──────────────────────────────────────────────────────────────
# TestSparkline
# ──────────────────────────────────────────────────────────────


class TestSparkline:
    def test_ascending_values(self):
        """Ascending values produce a non-empty string with Unicode block chars."""
        result = _sparkline([1.0, 2.0, 3.0, 4.0, 5.0])
        assert len(result) == 5
        assert result != ""
        # Should contain Unicode block characters (U+2581 through U+2588)
        for ch in result:
            assert ch in " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"

    def test_single_value_returns_empty(self):
        """A single value produces an empty string (need >= 2)."""
        assert _sparkline([42.0]) == ""

    def test_empty_list_returns_empty(self):
        """An empty list produces an empty string."""
        assert _sparkline([]) == ""

    def test_constant_values_same_char(self):
        """All identical values produce a string of the same character."""
        result = _sparkline([5.0, 5.0, 5.0, 5.0])
        assert len(result) == 4
        assert len(set(result)) == 1  # all same character

    def test_two_values(self):
        """Two values produce a valid 2-character sparkline."""
        result = _sparkline([0.0, 100.0])
        assert len(result) == 2
        assert result != ""
        # First char should be lowest block, last should be highest
        for ch in result:
            assert ch in " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


# ──────────────────────────────────────────────────────────────
# TestGenerateDailyReport
# ──────────────────────────────────────────────────────────────


class TestGenerateDailyReport:
    def test_generates_file_at_expected_path(self, db, tmp_path):
        """Report file is created at the configured reports_dir."""
        config = _make_config(tmp_path)
        _insert_sample_events(db)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        assert os.path.isfile(path)
        expected_dir = str(tmp_path / "reports" / "daily")
        assert path.startswith(expected_dir)

    def test_file_is_nonempty_markdown(self, db, tmp_path):
        """Generated file is non-empty and contains markdown content."""
        config = _make_config(tmp_path)
        _insert_sample_events(db)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 0
        # Should contain markdown heading markers
        assert "#" in content

    def test_contains_header_with_date(self, db, tmp_path):
        """Report contains a header with the specified date."""
        config = _make_config(tmp_path)
        _insert_sample_events(db)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert _DATE_STR in content
        assert "# LifeData Daily Report" in content

    def test_contains_daily_report_text(self, db, tmp_path):
        """Report content includes 'Daily Report'."""
        config = _make_config(tmp_path)
        _insert_sample_events(db)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Daily Report" in content

    def test_empty_database_produces_minimal_report(self, db, tmp_path):
        """An empty database does not crash and still produces a report file."""
        config = _make_config(tmp_path)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "Daily Report" in content
        assert "Total events: 0" in content

    def test_specific_date_str_in_filename(self, db, tmp_path):
        """The date_str appears in the generated filename."""
        config = _make_config(tmp_path)
        custom_date = "2026-01-15"
        path = generate_daily_report(db, config=config, date_str=custom_date)
        assert custom_date in os.path.basename(path)

    def test_report_file_has_md_extension(self, db, tmp_path):
        """Generated report has a .md file extension."""
        config = _make_config(tmp_path)
        _insert_sample_events(db)
        path = generate_daily_report(db, config=config, date_str=_DATE_STR)
        assert path.endswith(".md")
