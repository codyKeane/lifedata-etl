"""
Tests for EnvironmentModule.post_ingest() derived metric computation.

Covers:
  - environment.derived/daily_weather_composite — temp range, avg temp, avg humidity, avg pressure
  - environment.derived/location_diversity — unique locations at ~111m resolution
  - environment.derived/astro_summary — moon phase and illumination
  - disabled_metrics configuration
"""

import json
from datetime import UTC

from core.event import Event
from modules.environment import create_module

TARGET_DATE = "2026-03-20"
TZ_OFFSET = "-0500"


def _env_config():
    return {"enabled": True}


def _make_event(source_module, event_type, value_numeric=None, value_text=None,
                value_json=None, location_lat=None, location_lon=None,
                minute_offset=0):
    """Build an environment event at a known timestamp on TARGET_DATE."""
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
        location_lat=location_lat,
        location_lon=location_lon,
        confidence=1.0,
        parser_version="1.0.0",
    )


# ────────────────────────────────────────────────────────────
# Daily Weather Composite
# ────────────────────────────────────────────────────────────


class TestDailyWeatherComposite:
    """environment.derived/daily_weather_composite — temp range, avg temp, avg humidity, avg pressure."""

    def test_normal_day_with_temp_humidity(self, db):
        """Multiple hourly readings produce a composite event with correct averages."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 70.0, "humidity_pct": 40.0}),
                        minute_offset=0),
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 80.0, "humidity_pct": 60.0}),
                        minute_offset=60),
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 75.0, "humidity_pct": 50.0}),
                        minute_offset=120),
        ]
        db.insert_events_for_module("environment_hourly", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 1
        row = rows[0]
        data = json.loads(row["value_json"])

        assert data["temp_range_f"] == 10.0  # 80 - 70
        assert data["temp_avg_f"] == 75.0    # (70+80+75)/3
        assert data["humidity_avg_pct"] == 50.0  # (40+60+50)/3
        assert row["value_numeric"] == 75.0  # avg temp stored as value_numeric

    def test_includes_pressure_data(self, db):
        """Pressure events from environment.pressure are included in the composite."""
        mod = create_module(_env_config())

        hourly_events = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 72.0, "humidity_pct": 45.0}),
                        minute_offset=0),
        ]
        pressure_events = [
            _make_event("environment.pressure", "reading", value_numeric=1013.25,
                        minute_offset=0),
            _make_event("environment.pressure", "reading", value_numeric=1015.75,
                        minute_offset=60),
        ]
        db.insert_events_for_module("environment_hourly", hourly_events)
        db.insert_events_for_module("environment_pressure", pressure_events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["pressure_avg_hpa"] == 1014.5  # (1013.25+1015.75)/2

    def test_no_hourly_data_no_event(self, db):
        """Without any hourly data, no composite event is produced."""
        mod = create_module(_env_config())

        # Only pressure data, no hourly
        events = [
            _make_event("environment.pressure", "reading", value_numeric=1013.0,
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_pressure", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 0

    def test_single_reading_produces_composite(self, db):
        """A single hourly reading still produces a composite (range = 0)."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 65.0, "humidity_pct": 55.0}),
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_hourly", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["temp_range_f"] == 0.0
        assert data["temp_avg_f"] == 65.0
        assert data["humidity_avg_pct"] == 55.0

    def test_value_json_contains_expected_keys(self, db):
        """Verify value_json contains temp_range_f, temp_avg_f, humidity_avg_pct."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 70.0, "humidity_pct": 50.0}),
                        minute_offset=0),
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 80.0, "humidity_pct": 60.0}),
                        minute_offset=60),
        ]
        db.insert_events_for_module("environment_hourly", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "temp_range_f" in data
        assert "temp_avg_f" in data
        assert "humidity_avg_pct" in data

    def test_no_humidity_omits_humidity_key(self, db):
        """Hourly data with temp but no humidity omits humidity_avg_pct from composite."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 72.0}),
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_hourly", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="daily_weather_composite")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "temp_range_f" in data
        assert "temp_avg_f" in data
        assert "humidity_avg_pct" not in data


# ────────────────────────────────────────────────────────────
# Location Diversity
# ────────────────────────────────────────────────────────────


class TestLocationDiversity:
    """environment.derived/location_diversity — unique locations at ~111m resolution."""

    def test_multiple_distinct_locations(self, db):
        """Multiple distinct GPS locations produce correct unique count."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.776, location_lon=-96.797, minute_offset=0),
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.800, location_lon=-96.750, minute_offset=60),
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=33.000, location_lon=-96.500, minute_offset=120),
        ]
        db.insert_events_for_module("environment_location", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="location_diversity")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 3.0

        data = json.loads(rows[0]["value_json"])
        assert data["unique_locations"] == 3
        assert data["total_fixes"] == 3
        assert data["resolution_m"] == 111

    def test_same_location_repeated(self, db):
        """Same location repeated at different times produces diversity = 1."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.7767, location_lon=-96.7970, minute_offset=0),
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.7767, location_lon=-96.7970, minute_offset=60),
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.7767, location_lon=-96.7970, minute_offset=120),
        ]
        db.insert_events_for_module("environment_location", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="location_diversity")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 1.0

        data = json.loads(rows[0]["value_json"])
        assert data["unique_locations"] == 1
        assert data["total_fixes"] == 3

    def test_no_location_data_no_event(self, db):
        """Without location data, no diversity event is produced."""
        mod = create_module(_env_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="location_diversity")
        assert len(rows) == 0

    def test_nearby_locations_within_111m_grid(self, db):
        """Locations within the same 0.001-degree grid cell count as one."""
        mod = create_module(_env_config())

        # These two differ by less than 0.0005 degrees (~55m),
        # so rounding to 3 decimal places makes them identical
        # 32.7762 rounds to 32.776, 32.7764 rounds to 32.776
        # -96.7971 rounds to -96.797, -96.7974 rounds to -96.797
        events = [
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.7762, location_lon=-96.7971, minute_offset=0),
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.7764, location_lon=-96.7974, minute_offset=60),
        ]
        db.insert_events_for_module("environment_location", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="location_diversity")
        assert len(rows) == 1
        # Both round to (32.776, -96.797) so unique_locations = 1
        assert rows[0]["value_numeric"] == 1.0


# ────────────────────────────────────────────────────────────
# Astro Summary
# ────────────────────────────────────────────────────────────


class TestAstroSummary:
    """environment.derived/astro_summary — moon phase and illumination."""

    def test_moon_phase_and_illumination(self, db):
        """Astro data with phase and illumination produces a summary event."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.astro", "moon",
                        value_text="Waxing Gibbous", value_numeric=85.3,
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_astro", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="astro_summary")
        assert len(rows) == 1
        row = rows[0]
        assert row["value_text"] == "Waxing Gibbous"
        assert row["value_numeric"] == 85.3

        data = json.loads(row["value_json"])
        assert data["moon_phase"] == "Waxing Gibbous"
        assert data["moon_illumination_pct"] == 85.3

    def test_no_astro_data_no_event(self, db):
        """Without astro data, no summary event is produced."""
        mod = create_module(_env_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="astro_summary")
        assert len(rows) == 0

    def test_value_json_contains_moon_keys(self, db):
        """Verify value_json contains moon_phase and moon_illumination_pct."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.astro", "moon",
                        value_text="Full Moon", value_numeric=100.0,
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_astro", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="astro_summary")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert "moon_phase" in data
        assert "moon_illumination_pct" in data

    def test_phase_only_no_illumination(self, db):
        """Astro event with only phase text (no numeric) still produces summary."""
        mod = create_module(_env_config())

        events = [
            _make_event("environment.astro", "moon",
                        value_text="New Moon", value_numeric=None,
                        minute_offset=0),
        ]
        db.insert_events_for_module("environment_astro", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="environment.derived",
                               event_type="astro_summary")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert data["moon_phase"] == "New Moon"
        assert data["moon_illumination_pct"] is None


# ────────────────────────────────────────────────────────────
# Disabled Metrics
# ────────────────────────────────────────────────────────────


class TestDisabledMetrics:
    """Verify disabled_metrics config prevents derived metric computation."""

    def test_disable_one_metric_skips_only_that(self, db):
        """Disabling daily_weather_composite skips it but still computes others."""
        cfg = {"enabled": True,
               "disabled_metrics": ["environment.derived:daily_weather_composite"]}
        mod = create_module(cfg)

        # Insert data for all three metric types
        hourly = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 72.0, "humidity_pct": 50.0}),
                        minute_offset=0),
        ]
        location = [
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.776, location_lon=-96.797, minute_offset=0),
        ]
        astro = [
            _make_event("environment.astro", "moon",
                        value_text="Full Moon", value_numeric=100.0, minute_offset=0),
        ]
        db.insert_events_for_module("env_hourly", hourly)
        db.insert_events_for_module("env_location", location)
        db.insert_events_for_module("env_astro", astro)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        # Weather composite should be skipped
        composite_rows = db.query_events(source_module="environment.derived",
                                         event_type="daily_weather_composite")
        assert len(composite_rows) == 0

        # Location diversity should still compute
        loc_rows = db.query_events(source_module="environment.derived",
                                   event_type="location_diversity")
        assert len(loc_rows) == 1

        # Astro summary should still compute
        astro_rows = db.query_events(source_module="environment.derived",
                                     event_type="astro_summary")
        assert len(astro_rows) == 1

    def test_disable_all_derived_via_prefix(self, db):
        """Disabling 'environment.derived' skips all derived metrics."""
        cfg = {"enabled": True, "disabled_metrics": ["environment.derived"]}
        mod = create_module(cfg)

        hourly = [
            _make_event("environment.hourly", "snapshot",
                        value_json=json.dumps({"temp_f": 72.0, "humidity_pct": 50.0}),
                        minute_offset=0),
        ]
        location = [
            _make_event("environment.location", "fix", value_text="fix",
                        location_lat=32.776, location_lon=-96.797, minute_offset=0),
        ]
        astro = [
            _make_event("environment.astro", "moon",
                        value_text="Full Moon", value_numeric=100.0, minute_offset=0),
        ]
        db.insert_events_for_module("env_hourly", hourly)
        db.insert_events_for_module("env_location", location)
        db.insert_events_for_module("env_astro", astro)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        all_derived = db.query_events(source_module="environment.derived")
        assert len(all_derived) == 0
