"""
Tests for analysis/anomaly.py — z-score anomaly detection and pattern detection.
"""

from analysis.anomaly import AnomalyDetector
from core.event import Event


# Config with all 9 compound patterns (matches config.yaml).
# Pattern tests pass this to AnomalyDetector so the config-driven evaluator runs.
_PATTERN_CONFIG = {
    "lifedata": {
        "analysis": {
            "patterns": [
                {
                    "name": "heavy_phone_usage",
                    "enabled": True,
                    "description_template": "Low battery ({device_battery:.0f}%) with high screen unlocks ({device_screen}) — heavy phone usage day",
                    "conditions": [
                        {"metric": "device.battery", "aggregate": "AVG", "operator": "<", "threshold": 20},
                        {"metric": "device.screen", "aggregate": "COUNT", "operator": ">", "threshold": 50},
                    ],
                },
                {
                    "name": "sleep_deprivation_high_stress",
                    "enabled": True,
                    "description_template": "Short sleep with high stress — burnout risk",
                    "conditions": [
                        {"metric": "body.derived", "event_type": "sleep_duration", "operator": "<", "threshold": 6.0},
                        {"metric": "mind.stress", "operator": ">", "threshold": 6},
                    ],
                },
                {
                    "name": "caffeine_late_poor_sleep",
                    "enabled": True,
                    "description_template": "Late caffeine with poor sleep quality",
                    "conditions": [
                        {"metric": "body.caffeine", "event_type": "intake", "aggregate": "SUM", "operator": ">", "threshold": 0, "hour_filter": ">= 14"},
                        {"metric": "mind.sleep", "operator": "<", "threshold": 5},
                    ],
                },
                {
                    "name": "low_mood_social_isolation",
                    "enabled": True,
                    "description_template": "Low mood with minimal social interaction",
                    "conditions": [
                        {"metric": "mind.mood", "operator": "<", "threshold": 4},
                        {"metric": "social.derived", "event_type": "density_score", "operator": "<", "threshold": 10},
                    ],
                },
                {
                    "name": "high_screen_low_movement",
                    "enabled": True,
                    "description_template": "High screen time with low step count — sedentary day",
                    "conditions": [
                        {"metric": "device.derived", "event_type": "screen_time_minutes", "operator": ">", "threshold": 180},
                        {"metric": "body.steps", "aggregate": "SUM", "operator": "<", "threshold": 3000},
                    ],
                },
                {
                    "name": "cognitive_impairment_sleep_deprivation",
                    "enabled": True,
                    "description_template": "High cognitive impairment after short sleep",
                    "conditions": [
                        {"metric": "cognition.derived", "event_type": "cognitive_load_index", "operator": ">", "threshold": 2.0},
                        {"metric": "body.derived", "event_type": "sleep_duration", "operator": "<", "threshold": 6.0},
                    ],
                },
                {
                    "name": "digital_restlessness_low_mood",
                    "enabled": True,
                    "description_template": "Digital restlessness with low mood",
                    "conditions": [
                        {"metric": "behavior.derived", "event_type": "digital_restlessness", "operator": ">", "threshold": 2.0},
                        {"metric": "mind.mood", "operator": "<", "threshold": 4},
                    ],
                },
                {
                    "name": "schumann_excursion_mood_swing",
                    "enabled": True,
                    "description_template": "Schumann resonance deviation with mood swing",
                    "conditions": [
                        {"metric": "oracle.schumann", "operator": ">", "threshold": 8.13},
                        {"metric": "mind.mood", "aggregate": "COUNT", "operator": ">", "threshold": 1},
                    ],
                },
                {
                    "name": "fragmentation_caffeine_spike",
                    "enabled": True,
                    "description_template": "High app fragmentation with heavy caffeine",
                    "conditions": [
                        {"metric": "behavior.app_switch.derived", "event_type": "fragmentation_index", "operator": ">", "threshold": 50},
                        {"metric": "body.caffeine", "aggregate": "SUM", "operator": ">", "threshold": 300},
                    ],
                },
            ],
        }
    }
}


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _insert_metric_day(db, source_module, date_str, value, event_type="measurement"):
    """Insert a single numeric event for a metric on a given date."""
    e = Event(
        timestamp_utc=f"{date_str}T12:00:00+00:00",
        timestamp_local=f"{date_str}T07:00:00-05:00",
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value,
    )
    db.insert_events_for_module(source_module.split(".")[0], [e])


def _fill_baseline(db, source_module, base_value=50.0, days=14, start_day=1):
    """Insert 14 days of baseline data at a consistent value."""
    for i in range(days):
        day = start_day + i
        date_str = f"2026-03-{day:02d}"
        # Add small variation to avoid zero stdev
        value = base_value + (i % 3) - 1
        _insert_metric_day(db, source_module, date_str, value)


# ──────────────────────────────────────────────────────────────
# Z-score anomaly detection
# ──────────────────────────────────────────────────────────────


class TestAnomalyDetectorZScore:
    def test_no_anomalies_normal_value(self, db):
        """A value near the mean should not be flagged."""
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 80.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        battery_anomalies = [a for a in anomalies if a["metric"] == "device.battery"]
        assert len(battery_anomalies) == 0

    def test_extreme_high_flagged(self, db):
        """A value far above the mean should be flagged as high."""
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 200.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        battery = [a for a in anomalies if a["metric"] == "device.battery"]
        assert len(battery) == 1
        assert battery[0]["direction"] == "high"
        assert abs(battery[0]["zscore"]) > 2.0

    def test_extreme_low_flagged(self, db):
        """A value far below the mean should be flagged as low."""
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 0.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        battery = [a for a in anomalies if a["metric"] == "device.battery"]
        assert len(battery) == 1
        assert battery[0]["direction"] == "low"

    def test_insufficient_baseline_skipped(self, db):
        """Less than 3 days of history should be skipped."""
        _insert_metric_day(db, "device.battery", "2026-03-01", 80.0)
        _insert_metric_day(db, "device.battery", "2026-03-02", 80.0)
        _insert_metric_day(db, "device.battery", "2026-03-20", 200.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        # Not enough baseline (2 days excl. target) → no anomalies
        assert len(anomalies) == 0

    def test_empty_db_no_anomalies(self, db):
        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-24")
        assert anomalies == []

    def test_anomalies_sorted_by_severity(self, db):
        """Anomalies should be sorted by absolute z-score, highest first."""
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _fill_baseline(db, "mind.mood", base_value=7.0, days=14, start_day=1)
        # Both extreme, but battery more so
        _insert_metric_day(db, "device.battery", "2026-03-20", 300.0)
        _insert_metric_day(db, "mind.mood", "2026-03-20", 20.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        if len(anomalies) >= 2:
            assert abs(anomalies[0]["zscore"]) >= abs(anomalies[1]["zscore"])

    def test_severity_labels(self, db):
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 500.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        assert len(anomalies) > 0
        assert anomalies[0]["severity"] in ("notable", "extreme")

    def test_human_readable_description(self, db):
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 200.0)

        detector = AnomalyDetector(db, zscore_threshold=2.0)
        anomalies = detector.check_today("2026-03-20")
        assert len(anomalies) > 0
        desc = anomalies[0]["human_readable"]
        assert "device.battery" in desc
        assert "σ" in desc

    def test_custom_threshold(self, db):
        """Higher threshold → fewer anomalies."""
        _fill_baseline(db, "device.battery", base_value=80.0, days=14, start_day=1)
        _insert_metric_day(db, "device.battery", "2026-03-20", 90.0)

        low_threshold = AnomalyDetector(db, zscore_threshold=0.5)
        high_threshold = AnomalyDetector(db, zscore_threshold=10.0)

        low_anomalies = low_threshold.check_today("2026-03-20")
        high_anomalies = high_threshold.check_today("2026-03-20")
        assert len(low_anomalies) >= len(high_anomalies)


# ──────────────────────────────────────────────────────────────
# Pattern anomaly detection
# ──────────────────────────────────────────────────────────────


class TestPatternAnomalies:
    """All pattern tests use config-driven evaluation via _PATTERN_CONFIG."""

    def test_no_patterns_empty_db(self, db):
        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        assert patterns == []

    def test_heavy_phone_usage_pattern(self, db):
        """Low battery + high screen events → heavy_phone_usage pattern."""
        _insert_metric_day(db, "device.battery", "2026-03-24", 15.0)
        for i in range(55):
            e = Event(
                timestamp_utc=f"2026-03-24T{8 + (i // 6):02d}:{(i * 10) % 60:02d}:00+00:00",
                timestamp_local=f"2026-03-24T{3 + (i // 6):02d}:{(i * 10) % 60:02d}:00-05:00",
                timezone_offset="-0500",
                source_module="device.screen",
                event_type="screen_on",
                value_text="on",
            )
            db.insert_events_for_module("device", [e])

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        pattern_names = [p["pattern"] for p in patterns]
        assert "heavy_phone_usage" in pattern_names

    def test_pattern_has_description(self, db):
        """All patterns must have description and metrics."""
        _insert_metric_day(db, "device.battery", "2026-03-24", 10.0)
        for i in range(60):
            e = Event(
                timestamp_utc=f"2026-03-24T{8 + (i // 6):02d}:{(i * 10) % 60:02d}:00+00:00",
                timestamp_local=f"2026-03-24T{3 + (i // 6):02d}:{(i * 10) % 60:02d}:00-05:00",
                timezone_offset="-0500",
                source_module="device.screen",
                event_type="screen_on",
                value_text="on",
            )
            db.insert_events_for_module("device", [e])

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        for p in patterns:
            assert "pattern" in p
            assert "description" in p
            assert "metrics" in p

    def test_sleep_deprivation_high_stress(self, db):
        """Short sleep + high stress → sleep_deprivation_high_stress pattern."""
        _insert_metric_day(db, "body.derived", "2026-03-24", 4.5, event_type="sleep_duration")
        _insert_metric_day(db, "mind.stress", "2026-03-24", 8.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "sleep_deprivation_high_stress" in names

    def test_sleep_deprivation_not_triggered_when_rested(self, db):
        """Good sleep + high stress → no burnout pattern."""
        _insert_metric_day(db, "body.derived", "2026-03-24", 8.0, event_type="sleep_duration")
        _insert_metric_day(db, "mind.stress", "2026-03-24", 8.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "sleep_deprivation_high_stress" not in names

    def test_caffeine_late_poor_sleep(self, db):
        """Late caffeine + poor sleep → caffeine_late_poor_sleep pattern."""
        e = Event(
            timestamp_utc="2026-03-24T20:00:00+00:00",
            timestamp_local="2026-03-24T15:00:00-05:00",
            timezone_offset="-0500",
            source_module="body.caffeine",
            event_type="intake",
            value_numeric=200.0,
        )
        db.insert_events_for_module("body", [e])
        _insert_metric_day(db, "mind.sleep", "2026-03-24", 3.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "caffeine_late_poor_sleep" in names

    def test_low_mood_social_isolation(self, db):
        """Low mood + low social density → low_mood_social_isolation pattern."""
        _insert_metric_day(db, "mind.mood", "2026-03-24", 2.0)
        _insert_metric_day(db, "social.derived", "2026-03-24", 5.0, event_type="density_score")

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "low_mood_social_isolation" in names

    def test_high_screen_low_movement(self, db):
        """High screen time + low steps → high_screen_low_movement pattern."""
        _insert_metric_day(db, "device.derived", "2026-03-24", 240.0, event_type="screen_time_minutes")
        _insert_metric_day(db, "body.steps", "2026-03-24", 1500.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "high_screen_low_movement" in names

    def test_cognitive_impairment_sleep_deprivation(self, db):
        """High CLI + short sleep → cognitive_impairment_sleep_deprivation pattern."""
        _insert_metric_day(db, "cognition.derived", "2026-03-24", 3.5, event_type="cognitive_load_index")
        _insert_metric_day(db, "body.derived", "2026-03-24", 4.0, event_type="sleep_duration")

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "cognitive_impairment_sleep_deprivation" in names

    def test_digital_restlessness_low_mood(self, db):
        """High restlessness + low mood → digital_restlessness_low_mood pattern."""
        _insert_metric_day(db, "behavior.derived", "2026-03-24", 3.0, event_type="digital_restlessness")
        _insert_metric_day(db, "mind.mood", "2026-03-24", 2.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "digital_restlessness_low_mood" in names

    def test_schumann_excursion_mood_swing(self, db):
        """Schumann deviation + wide mood range → schumann_excursion_mood_swing."""
        e1 = Event(
            timestamp_utc="2026-03-24T10:00:00+00:00",
            timestamp_local="2026-03-24T05:00:00-05:00",
            timezone_offset="-0500",
            source_module="oracle.schumann",
            event_type="measurement",
            value_numeric=8.5,
        )
        db.insert_events_for_module("oracle", [e1])
        for val, hour in [(2.0, "08"), (9.0, "14"), (5.0, "20")]:
            e = Event(
                timestamp_utc=f"2026-03-24T{hour}:00:00+00:00",
                timestamp_local=f"2026-03-24T{hour}:00:00-05:00",
                timezone_offset="-0500",
                source_module="mind.mood",
                event_type="check_in",
                value_numeric=val,
            )
            db.insert_events_for_module("mind", [e])

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "schumann_excursion_mood_swing" in names

    def test_fragmentation_caffeine_spike(self, db):
        """High fragmentation + heavy caffeine → fragmentation_caffeine_spike."""
        _insert_metric_day(
            db, "behavior.app_switch.derived", "2026-03-24", 75.0,
            event_type="fragmentation_index",
        )
        _insert_metric_day(db, "body.caffeine", "2026-03-24", 400.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "fragmentation_caffeine_spike" in names

    def test_pattern_not_triggered_when_one_metric_missing(self, db):
        """If only one side of a compound pattern has data, no pattern fires."""
        _insert_metric_day(db, "mind.mood", "2026-03-24", 2.0)

        detector = AnomalyDetector(db, config=_PATTERN_CONFIG)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        names = [p["pattern"] for p in patterns]
        assert "low_mood_social_isolation" not in names

    def test_no_config_patterns_returns_empty(self, db):
        """When no config patterns are defined, returns empty list."""
        detector = AnomalyDetector(db)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        assert patterns == []

    def test_describe_static_method(self):
        """Test _describe() produces readable output."""
        desc = AnomalyDetector._describe("device.battery", 3.5, 95.0, 80.0)
        assert "device.battery" in desc
        assert "above" in desc
        assert "3.5" in desc
