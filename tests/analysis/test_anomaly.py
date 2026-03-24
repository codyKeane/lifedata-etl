"""
Tests for analysis/anomaly.py — z-score anomaly detection and pattern detection.
"""

from analysis.anomaly import AnomalyDetector
from core.event import Event


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
    def test_no_patterns_empty_db(self, db):
        detector = AnomalyDetector(db)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        assert patterns == []

    def test_heavy_phone_usage_pattern(self, db):
        """Low battery + high screen events → heavy_phone_usage pattern."""
        # Insert low battery
        _insert_metric_day(db, "device.battery", "2026-03-24", 15.0)
        # Insert >50 screen events
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

        detector = AnomalyDetector(db)
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

        detector = AnomalyDetector(db)
        patterns = detector.check_pattern_anomalies("2026-03-24")
        for p in patterns:
            assert "pattern" in p
            assert "description" in p
            assert "metrics" in p

    def test_describe_static_method(self):
        """Test _describe() produces readable output."""
        desc = AnomalyDetector._describe("device.battery", 3.5, 95.0, 80.0)
        assert "device.battery" in desc
        assert "above" in desc
        assert "3.5" in desc
