"""
Tests for modules/meta/completeness.py — data completeness checking.
"""

from modules.meta.completeness import (
    check_daily_completeness,
    EXPECTED_DAILY_SOURCES,
    OPTIONAL_DAILY_SOURCES,
)
from core.event import Event


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _make_event(source_module, event_type, ts_local, value=1.0):
    return Event(
        timestamp_utc=ts_local.replace("-05:00", "+00:00"),
        timestamp_local=ts_local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value,
    )


def _fill_required_sources(db, date_str="2026-03-24"):
    """Insert enough events to satisfy all required sources.

    Uses unique timestamps and values to avoid dedup collisions.
    """
    for source, (min_count, _desc) in EXPECTED_DAILY_SOURCES.items():
        events = []
        for i in range(min_count):
            # Generate unique hour:minute:second combos to avoid dedup
            h = (i // 3600) % 24
            m = (i // 60) % 60
            s = i % 60
            ts_local = f"{date_str}T{h:02d}:{m:02d}:{s:02d}-05:00"
            ts_utc = f"{date_str}T{(h + 5) % 24:02d}:{m:02d}:{s:02d}+00:00"
            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset="-0500",
                    source_module=source,
                    event_type="test",
                    value_numeric=float(i),
                )
            )
        db.insert_events_for_module(source.split(".")[0], events)


# ──────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────


class TestCompletenessChecker:
    def test_empty_database_zero_pct(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        assert report["overall_pct"] == 0.0
        assert len(report["missing"]) == len(EXPECTED_DAILY_SOURCES)

    def test_full_data_100_pct(self, db):
        _fill_required_sources(db)
        report = check_daily_completeness(db, "2026-03-24")
        assert report["overall_pct"] == 100.0
        assert len(report["missing"]) == 0

    def test_partial_data(self, db):
        """Satisfy only 1 of the required sources."""
        source = "device.screen"
        min_count = EXPECTED_DAILY_SOURCES[source][0]
        events = []
        for i in range(min_count):
            h = (i // 60) % 24
            m = i % 60
            ts_local = f"2026-03-24T{h:02d}:{m:02d}:00-05:00"
            ts_utc = f"2026-03-24T{(h + 5) % 24:02d}:{m:02d}:00+00:00"
            events.append(
                Event(
                    timestamp_utc=ts_utc,
                    timestamp_local=ts_local,
                    timezone_offset="-0500",
                    source_module=source,
                    event_type="screen_on",
                    value_text="on",
                    value_numeric=float(i),
                )
            )
        db.insert_events_for_module("device", events)

        report = check_daily_completeness(db, "2026-03-24")
        assert 0 < report["overall_pct"] < 100
        # Only device.screen should be met
        assert report["required"]["device.screen"]["met"] is True

    def test_missing_sources_contain_details(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        for missing in report["missing"]:
            assert "source" in missing
            assert "expected_min" in missing
            assert "actual" in missing
            assert "description" in missing

    def test_optional_sources_generate_warnings(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        # All optional sources should show warnings when empty
        assert len(report["warnings"]) == len(OPTIONAL_DAILY_SOURCES)

    def test_wrong_date_gets_zero(self, db):
        _fill_required_sources(db, "2026-03-24")
        report = check_daily_completeness(db, "2026-03-25")
        assert report["overall_pct"] == 0.0

    def test_report_contains_date(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        assert report["date"] == "2026-03-24"

    def test_required_dict_all_sources(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        for source in EXPECTED_DAILY_SOURCES:
            assert source in report["required"]

    def test_optional_dict_all_sources(self, db):
        report = check_daily_completeness(db, "2026-03-24")
        for source in OPTIONAL_DAILY_SOURCES:
            assert source in report["optional"]
