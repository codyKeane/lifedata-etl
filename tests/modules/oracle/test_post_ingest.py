"""
Tests for OracleModule.post_ingest() derived metric computation.

Covers:
  - oracle.rng.derived/daily_deviation (z-score of daily RNG mean vs 127.5)
  - oracle.schumann.derived/daily_summary (mean/min/max Hz + excursion count)
  - oracle.iching.derived/hexagram_frequency (distribution over rolling window)
  - oracle.iching.derived/entropy_test (chi-squared uniformity test)
  - oracle.planetary_hours.derived/activity_by_planet (mood/energy by planet)
"""

import json
from datetime import UTC

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
    from datetime import datetime, timedelta

    dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=UTC) + timedelta(minutes=minute_offset)
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

    def test_all_identical_values_uses_theoretical_std(self, db):
        """When all RNG samples are identical, std falls back to 7.39."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # All identical values: computed std = 0, so fallback to 7.39
        rng_events = [
            _make_event("oracle.rng", "hardware_sample", 127.5, minute_offset=i * 10)
            for i in range(5)
        ]
        db.insert_events_for_module("oracle_rng", rng_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        # std should be fallback 7.39 since all values identical
        assert data["std"] == 7.39
        # mean == expected, so z-score should be ~0
        assert abs(data["z_score"]) < 0.01

    def test_value_json_contains_required_fields(self, db):
        """Verify value_json contains z_score, p_value, and sample_count fields."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        rng_events = [
            _make_event("oracle.rng", "hardware_sample", 120.0 + i * 5, minute_offset=i * 10)
            for i in range(4)
        ]
        db.insert_events_for_module("oracle_rng", rng_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "z_score" in data
        assert "p_value" in data
        assert "n_samples" in data
        assert "daily_mean" in data
        assert "std" in data
        # p_value should be between 0 and 1
        assert 0.0 <= data["p_value"] <= 1.0
        assert data["n_samples"] == 4


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
        # 8.50 is >0.5 Hz from baseline 7.83 -> 1 excursion
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

    def test_excursion_detection_both_directions(self, db):
        """Excursions detected for values both above and below 7.83 baseline."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # 7.20 is 0.63 Hz below baseline -> excursion
        # 7.83 is on baseline -> no excursion
        # 8.50 is 0.67 Hz above baseline -> excursion
        # 8.30 is 0.47 Hz above baseline -> NOT excursion (<=0.5)
        readings = [7.20, 7.83, 8.50, 8.30]
        events = [
            _make_event("oracle.schumann", "measurement", val, minute_offset=i * 60)
            for i, val in enumerate(readings)
        ]
        db.insert_events_for_module("oracle_schumann", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.schumann.derived",
                               event_type="daily_summary")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["excursion_count"] == 2
        assert data["n_measurements"] == 4

    def test_value_json_stats_correct(self, db):
        """Verify mean, min, max, std are computed correctly."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        readings = [7.80, 7.90]
        events = [
            _make_event("oracle.schumann", "measurement", val, minute_offset=i * 60)
            for i, val in enumerate(readings)
        ]
        db.insert_events_for_module("oracle_schumann", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.schumann.derived",
                               event_type="daily_summary")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])

        expected_mean = (7.80 + 7.90) / 2
        assert data["mean_hz"] == pytest.approx(expected_mean, abs=0.001)
        assert data["min_hz"] == pytest.approx(7.80, abs=0.001)
        assert data["max_hz"] == pytest.approx(7.90, abs=0.001)
        # std = sqrt(((7.80-7.85)^2 + (7.90-7.85)^2)/2) = 0.05
        assert data["std_hz"] == pytest.approx(0.05, abs=0.001)
        # value_numeric is the mean
        assert rows[0]["value_numeric"] == pytest.approx(expected_mean, abs=0.001)


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

    def test_single_casting_no_event(self, db):
        """With only 1 casting, no frequency event (needs >=3)."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [_make_event("oracle.iching", "casting", 42.0)]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="hexagram_frequency")
        assert len(rows) == 0

    def test_distribution_values_correct(self, db):
        """Distribution dict maps hexagram number to count correctly."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # 3 castings of hex 1, 2 castings of hex 2
        hexagrams = [1, 1, 1, 2, 2]
        events = [
            _make_event("oracle.iching", "casting", float(h), minute_offset=i * 10)
            for i, h in enumerate(hexagrams)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="hexagram_frequency")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        dist = data["distribution"]
        # Keys are stringified ints in JSON
        assert dist["1"] == 3
        assert dist["2"] == 2
        assert data["most_common"] == 1
        assert data["window_days"] == 90
        # value_numeric is total castings
        assert rows[0]["value_numeric"] == 5.0

    def test_no_castings_no_event(self, db):
        """With no castings at all, no frequency event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

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

    def test_uniform_flag_when_p_above_threshold(self, db):
        """With many uniformly distributed castings, uniform flag should be True."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # 64 castings, one per hexagram -> perfectly uniform distribution
        # Should yield high p-value (uniform = True)
        events = [
            _make_event("oracle.iching", "casting", float(h), minute_offset=h)
            for h in range(1, 65)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="entropy_test")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        # Perfectly uniform -> chi_squared = 0 -> p_value very high
        assert data["chi_squared"] == pytest.approx(0.0, abs=0.01)
        assert data["uniform"] is True

    def test_concentrated_castings_low_p_value(self, db):
        """Many castings concentrated on one hexagram should yield low p-value."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # 50 castings all on hexagram 1 -> very non-uniform
        events = [
            _make_event("oracle.iching", "casting", 1.0, minute_offset=i)
            for i in range(50)
        ]
        db.insert_events_for_module("oracle_iching", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.iching.derived",
                               event_type="entropy_test")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        # Highly non-uniform -> p_value should be very low
        assert data["p_value"] < 0.05
        assert data["uniform"] is False


# ────────────────────────────────────────────────────────────
# Activity by Planet
# ────────────────────────────────────────────────────────────


class TestActivityByPlanet:
    """oracle.planetary_hours.derived/activity_by_planet — mood/energy by planet."""

    def test_planetary_hours_with_events(self, db):
        """Planetary hours data + other events produce activity distribution."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Insert planetary hour events
        planet_events = [
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=0,
                value_text="Mars",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T13:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T14:00:00+00:00",
                }),
            ),
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=60,
                value_text="Venus",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T14:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T15:00:00+00:00",
                }),
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)

        # Insert some non-oracle events that fall within planetary hour ranges
        # Use timestamp_local matching the planetary hour time ranges
        mood_event = Event(
            timestamp_utc=f"{TARGET_DATE}T13:30:00+00:00",
            timestamp_local=f"{TARGET_DATE}T13:30:00+00:00",
            timezone_offset=TZ_OFFSET,
            source_module="mind.mood",
            event_type="check_in",
            value_numeric=7.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        db.insert_events_for_module("mind", [mood_event])

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "Mars" in data
        assert "Venus" in data
        assert data["Mars"]["hours_count"] == 1
        assert data["Venus"]["hours_count"] == 1
        # Mars hour should have captured the mood event
        assert data["Mars"]["events_count"] >= 1
        assert data["Mars"]["mood_avg"] == 7.0

    def test_no_planetary_hours_no_event(self, db):
        """Without planetary hours data, no activity_by_planet event is produced."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 0

    def test_planetary_hours_no_matching_events(self, db):
        """Planetary hours exist but no non-oracle events -> event with zero counts."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        planet_events = [
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=0,
                value_text="Jupiter",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T13:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T14:00:00+00:00",
                }),
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "Jupiter" in data
        assert data["Jupiter"]["events_count"] == 0
        assert data["Jupiter"]["mood_avg"] is None
        assert data["Jupiter"]["energy_avg"] is None

    def test_planetary_hours_with_missing_times(self, db):
        """Planetary hours with empty start/end are skipped gracefully."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        planet_events = [
            # Missing start/end times
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=0,
                value_text="Saturn",
                value_json=json.dumps({}),  # no start_time/end_time
            ),
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=60,
                value_text="Mercury",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T14:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T15:00:00+00:00",
                }),
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        # Saturn has no valid time range -> not in activity
        assert "Saturn" not in data
        assert "Mercury" in data

    def test_planetary_hours_all_missing_ranges(self, db):
        """All planetary hours have empty time ranges => no activity event."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        planet_events = [
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=0,
                value_text="Mars",
                value_json=json.dumps({}),  # no start_time/end_time
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 0

    def test_planetary_hours_corrupt_json_in_db(self, db):
        """Directly inserted corrupt JSON in planetary hours is handled gracefully."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        # Bypass validation by inserting directly via SQL
        import hashlib
        import uuid
        raw_id = hashlib.sha256(b"corrupt_test").hexdigest()[:32]
        eid = str(uuid.UUID(hex=hashlib.sha256(raw_id.encode()).hexdigest()[:32]))
        db.conn.execute(
            """INSERT INTO events (event_id, timestamp_utc, timestamp_local, timezone_offset,
               source_module, event_type, value_text, value_json, confidence, raw_source_id,
               created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, f"{TARGET_DATE}T13:00:00+00:00", f"{TARGET_DATE}T08:00:00-05:00",
             "-0500", "oracle.planetary_hours", "current_hour", "Moon",
             "{{broken json", 1.0, raw_id, "2026-03-20T00:00:00+00:00"),
        )
        # Also insert a valid one so we get an event
        planet_events = [
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=120,
                value_text="Sun",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T15:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T16:00:00+00:00",
                }),
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)
        db.conn.commit()

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        # Moon with corrupt JSON should be skipped, Sun should be present
        assert "Moon" not in data
        assert "Sun" in data

    def test_energy_events_captured_by_planet(self, db):
        """Energy events are correctly attributed to planetary hours."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        planet_events = [
            _make_event(
                "oracle.planetary_hours", "current_hour", None,
                minute_offset=0,
                value_text="Sun",
                value_json=json.dumps({
                    "start_time": f"{TARGET_DATE}T13:00:00+00:00",
                    "end_time": f"{TARGET_DATE}T14:00:00+00:00",
                }),
            ),
        ]
        db.insert_events_for_module("oracle_planetary", planet_events)

        energy_event = Event(
            timestamp_utc=f"{TARGET_DATE}T13:30:00+00:00",
            timestamp_local=f"{TARGET_DATE}T13:30:00+00:00",
            timezone_offset=TZ_OFFSET,
            source_module="mind.energy",
            event_type="energy_check",
            value_numeric=8.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        db.insert_events_for_module("mind", [energy_event])

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.planetary_hours.derived",
                               event_type="activity_by_planet")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["Sun"]["events_count"] >= 1


# ────────────────────────────────────────────────────────────
# GetDailySummary
# ────────────────────────────────────────────────────────────


class TestGetDailySummary:
    """Tests for OracleModule.get_daily_summary() report rendering."""

    def test_summary_with_castings_and_rng(self, db):
        """Mixed oracle events produce a structured summary."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.iching", "casting", 42.0, minute_offset=0),
            _make_event("oracle.iching", "casting", 23.0, minute_offset=30),
            _make_event("oracle.rng", "hardware_sample", 130.0, minute_offset=60),
            _make_event("oracle.rng", "hardware_sample", 125.0, minute_offset=70),
            _make_event("oracle.rng", "hardware_sample", 128.0, minute_offset=80),
        ]
        db.insert_events_for_module("oracle", events)
        # Run post_ingest to create derived metrics
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is not None
        assert summary["section_title"] == "Oracle"
        assert summary["total_oracle_events"] > 0
        assert "event_counts" in summary
        assert isinstance(summary["bullets"], list)

    def test_summary_with_schumann(self, db):
        """Schumann readings produce derived summary that get_daily_summary can reference."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.schumann", "measurement", 7.83, minute_offset=0),
            _make_event("oracle.schumann", "measurement", 7.90, minute_offset=60),
        ]
        db.insert_events_for_module("oracle_schumann", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is not None
        assert summary["total_oracle_events"] > 0

    def test_summary_empty_day(self, db):
        """No oracle events => None summary."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is None

    def test_iching_bullet_present(self, db):
        """I Ching castings produce a bullet in summary."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.iching", "casting", 1.0, minute_offset=0),
            _make_event("oracle.iching", "casting", 2.0, minute_offset=30),
        ]
        db.insert_events_for_module("oracle_iching", events)

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is not None
        iching_bullets = [b for b in summary["bullets"] if "I Ching" in b]
        assert len(iching_bullets) >= 1


# ────────────────────────────────────────────────────────────
# TestDisabledMetrics
# ────────────────────────────────────────────────────────────


class TestOracleDisabledMetrics:
    """Tests that disabled_metrics prevents metric computation."""

    def test_disable_rng_deviation(self, db):
        """Disabling rng daily_deviation prevents computation."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"].copy()
        config["disabled_metrics"] = ["oracle.rng.derived:daily_deviation"]
        mod = create_module(config)

        events = [
            _make_event("oracle.rng", "hardware_sample", 130.0, minute_offset=i * 10)
            for i in range(5)
        ]
        db.insert_events_for_module("oracle_rng", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="oracle.rng.derived",
                               event_type="daily_deviation")
        assert len(rows) == 0

    def test_disable_all_iching_derived(self, db):
        """Disabling oracle.iching.derived prefix blocks frequency + entropy."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"].copy()
        config["disabled_metrics"] = ["oracle.iching.derived"]
        mod = create_module(config)

        events = [
            _make_event("oracle.iching", "casting", float(h), minute_offset=h)
            for h in range(1, 65)
        ]
        db.insert_events_for_module("oracle_iching", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        freq_rows = db.query_events(source_module="oracle.iching.derived",
                                    event_type="hexagram_frequency")
        entropy_rows = db.query_events(source_module="oracle.iching.derived",
                                       event_type="entropy_test")
        assert len(freq_rows) == 0
        assert len(entropy_rows) == 0


# ────────────────────────────────────────────────────────────
# TestIdempotency
# ────────────────────────────────────────────────────────────


class TestOracleIdempotency:
    """Verify post_ingest is idempotent (INSERT OR REPLACE)."""

    def test_rerun_same_results(self, db):
        """Running post_ingest twice produces identical event counts."""
        config = _oracle_config()["lifedata"]["modules"]["oracle"]
        mod = create_module(config)

        events = [
            _make_event("oracle.rng", "hardware_sample", 130.0, minute_offset=i * 10)
            for i in range(5)
        ]
        events.extend([
            _make_event("oracle.schumann", "measurement", 7.83 + i * 0.02, minute_offset=i * 60)
            for i in range(3)
        ])
        db.insert_events_for_module("oracle", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        count_1 = db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'oracle.%derived%'"
        ).fetchone()[0]

        mod.post_ingest(db, affected_dates={TARGET_DATE})
        count_2 = db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE source_module LIKE 'oracle.%derived%'"
        ).fetchone()[0]

        assert count_1 == count_2
        assert count_1 > 0
