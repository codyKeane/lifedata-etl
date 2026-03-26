"""
Tests for OracleModule.post_ingest() derived metric computation.

Covers:
  - oracle.rng.derived/daily_deviation (z-score of daily RNG mean vs 127.5)
  - oracle.schumann.derived/daily_summary (mean/min/max Hz + excursion count)
  - oracle.iching.derived/hexagram_frequency (distribution over rolling window)
  - oracle.iching.derived/entropy_test (chi-squared uniformity test)
"""

import json

import pytest

from core.event import Event
from modules.oracle import create_module

TARGET_DATE = "2026-03-20"
TS_BASE = f"{TARGET_DATE}T13:00:00+00:00"
TZ_OFFSET = "-0500"


def _oracle_config():
    return {
        "lifedata": {
            "modules": {
                "oracle": {
                    "enabled": True,
                    "analysis_window_days": 90,
                    "home_lat": "41.88",
                    "home_lon": "-87.63",
                },
            },
        },
    }


def _make_event(source_module, event_type, value_numeric, minute_offset=0,
                value_text=None, value_json=None):
    """Build a raw oracle event at a known timestamp on TARGET_DATE."""
    from datetime import datetime, timedelta, timezone as tz

    dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=tz.utc) + timedelta(minutes=minute_offset)
    ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ts_local = (dt - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=TZ_OFFSET,
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        value_json=value_json,
        confidence=1.0,
        parser_version="1.0.0",
    )


# ────────────────────────────────────────────────────────────
# RNG Daily Deviation
# ────────────────────────────────────────────────────────────


class TestRNGDeviation:
    """oracle.rng.derived/daily_deviation — z-score of daily mean vs 127.5."""

    def test_known_samples(self, db):
        """With 5 RNG samples, post_ingest produces a daily_deviation event."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Insert 5 RNG hardware samples (above expected 127.5)
        rng_events = [
            _make_event("oracle.rng", "hardware_sample", 130.0, minute_offset=i * 10)
            for i in range(5)
        ]
        db.insert_events_for_module("oracle_rng", rng_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 1
        row = rows[0]
        # z-score should be positive (mean 130 > expected 127.5)
        assert row["value_numeric"] is not None
        assert row["value_numeric"] > 0

        data = json.loads(row["value_json"])
        assert data["n_samples"] == 5
        assert data["daily_mean"] == 130.0

    def test_no_samples_no_event(self, db):
        """With no RNG samples, no daily_deviation event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 0

    def test_fewer_than_three_samples_no_event(self, db):
        """With fewer than 3 RNG samples, no event is produced (threshold)."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        rng_events = [
            _make_event("oracle.rng", "hardware_sample", 130.0, minute_offset=i * 10)
            for i in range(2)
        ]
        db.insert_events_for_module("oracle_rng", rng_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Schumann Daily Summary
# ────────────────────────────────────────────────────────────


class TestSchumannSummary:
    """oracle.schumann.derived/daily_summary — mean/min/max Hz + excursions."""

    def test_multiple_readings(self, db):
        """With several Schumann readings, a daily_summary is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Insert readings: two normal, one excursion (>0.5 Hz from 7.83 baseline)
        readings = [7.83, 7.85, 8.50]
        events = [
            _make_event("oracle.schumann", "measurement", val, minute_offset=i * 60)
            for i, val in enumerate(readings)
        ]
        db.insert_events_for_module("oracle_schumann", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.schumann.derived",
                               event_type="daily_summary")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])
        assert data["n_measurements"] == 3
        assert data["min_hz"] == 7.83
        assert data["max_hz"] == 8.5
        # 8.50 is >0.5 Hz from baseline 7.83 → 1 excursion
        assert data["excursion_count"] == 1

    def test_no_readings_no_event(self, db):
        """With no Schumann measurements, no summary event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.schumann.derived",
                               event_type="daily_summary")
        assert len(rows) == 0

    def test_single_reading_no_event(self, db):
        """With only 1 measurement, no summary (needs >=2)."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [_make_event("oracle.schumann", "measurement", 7.83)]
        db.insert_events_for_module("oracle_schumann", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.schumann.derived",
                               event_type="daily_summary")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Hexagram Frequency
# ────────────────────────────────────────────────────────────


class TestHexagramFrequency:
    """oracle.iching.derived/hexagram_frequency — distribution over window."""

    def test_enough_castings(self, db):
        """With 3+ castings over the window, a frequency event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Insert 5 castings with varying hexagram numbers
        hexagrams = [1, 23, 23, 42, 64]
        events = [
            _make_event("oracle.iching", "casting", float(h), minute_offset=i * 30)
            for i, h in enumerate(hexagrams)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="hexagram_frequency")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])
        assert data["total_castings"] == 5
        assert data["unique_hexagrams"] == 4
        # Hexagram 23 appears twice — should be most common
        assert data["most_common"] == 23

    def test_too_few_castings(self, db):
        """With fewer than 3 castings, no frequency event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.iching", "casting", 10.0, minute_offset=0),
            _make_event("oracle.iching", "casting", 20.0, minute_offset=30),
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="hexagram_frequency")
        assert len(rows) == 0


# ────────────────────────────────────────────────────────────
# Entropy Test
# ────────────────────────────────────────────────────────────


class TestEntropyTest:
    """oracle.iching.derived/entropy_test — chi-squared uniformity test."""

    def test_enough_castings_produces_event(self, db):
        """With 10+ castings, an entropy_test event is produced with chi-squared."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Insert 12 castings spread across hexagrams
        hexagrams = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
        events = [
            _make_event("oracle.iching", "casting", float(h), minute_offset=i * 10)
            for i, h in enumerate(hexagrams)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="entropy_test")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])
        assert data["n_castings"] == 12
        assert data["df"] == 63
        assert "chi_squared" in data
        assert "p_value" in data
        # p_value is stored in value_numeric
        assert row["value_numeric"] is not None
        assert 0.0 <= row["value_numeric"] <= 1.0

    def test_too_few_castings_no_event(self, db):
        """With fewer than 10 castings, no entropy_test event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.iching", "casting", float(i + 1), minute_offset=i * 10)
            for i in range(9)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="entropy_test")
        assert len(rows) == 0
