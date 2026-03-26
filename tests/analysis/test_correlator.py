"""
Tests for analysis/correlator.py — Correlator class.

Uses real in-memory SQLite via the `db` fixture from conftest.py.
All correlation data is inserted as Event objects through the database API.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.event import Event
from analysis.correlator import Correlator


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

# Use a date relative to "now" so tests don't break as calendar advances.
# 35 days back ensures 30-day data fits within window_days=60 used by most tests,
# AND within the default window_days=30 used by lagged_analysis.
BASE_DATE = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=35)


def _make_event(
    day_offset: int,
    source_module: str,
    value: float,
    confidence: float = 1.0,
    hour: int = 12,
) -> Event:
    """Create an Event for a given day offset from BASE_DATE."""
    dt = BASE_DATE + timedelta(days=day_offset, hours=hour - 12)
    utc_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    local_str = (dt - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return Event(
        timestamp_utc=utc_str,
        timestamp_local=local_str,
        timezone_offset="-0500",
        source_module=source_module,
        event_type="measurement",
        value_numeric=value,
        confidence=confidence,
        parser_version="1.0.0",
    )


def _insert_daily_series(db, source_module, values, confidence=1.0):
    """Insert one event per day for the given values list starting at BASE_DATE."""
    events = [
        _make_event(i, source_module, v, confidence=confidence)
        for i, v in enumerate(values)
    ]
    db.insert_events_for_module(source_module.split(".")[0], events)


# ──────────────────────────────────────────────────────────────
# 1. _get_daily_series
# ──────────────────────────────────────────────────────────────


class TestGetDailySeries:
    """Tests for Correlator._get_daily_series."""

    def test_single_day(self, db):
        """Single event on one day returns one entry."""
        _insert_daily_series(db, "test.metric", [42.0])
        c = Correlator(db)
        series = c._get_daily_series("test.metric", window_days=60)
        assert len(series) == 1
        date_key = list(series.keys())[0]
        assert series[date_key] == pytest.approx(42.0)

    def test_multiple_events_averaged(self, db):
        """Multiple events on the same day are averaged."""
        events = [
            _make_event(0, "test.avg", 10.0, hour=8),
            _make_event(0, "test.avg", 20.0, hour=14),
            _make_event(0, "test.avg", 30.0, hour=20),
        ]
        db.insert_events_for_module("test", events)
        c = Correlator(db)
        series = c._get_daily_series("test.avg", window_days=60)
        assert len(series) == 1
        assert list(series.values())[0] == pytest.approx(20.0)

    def test_confidence_filter(self, db):
        """Events below min_confidence are excluded."""
        events = [
            _make_event(0, "test.conf", 100.0, confidence=0.9),
            _make_event(1, "test.conf", 50.0, confidence=0.1),  # below threshold
        ]
        db.insert_events_for_module("test", events)
        c = Correlator(db)
        series = c._get_daily_series("test.conf", window_days=60, min_confidence=0.5)
        assert len(series) == 1
        assert list(series.values())[0] == pytest.approx(100.0)

    def test_window_cutoff(self, db):
        """Events outside the window are excluded."""
        # Insert an event 90 days ago — should be outside a 60-day window
        old_dt = datetime.now(UTC) - timedelta(days=90)
        old_event = Event(
            timestamp_utc=old_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            timestamp_local=old_dt.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
            timezone_offset="-0500",
            source_module="test.window",
            event_type="measurement",
            value_numeric=99.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        # Insert a recent event
        recent_dt = datetime.now(UTC) - timedelta(days=1)
        recent_event = Event(
            timestamp_utc=recent_dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            timestamp_local=recent_dt.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
            timezone_offset="-0500",
            source_module="test.window",
            event_type="measurement",
            value_numeric=10.0,
            confidence=1.0,
            parser_version="1.0.0",
        )
        db.insert_events_for_module("test", [old_event, recent_event])
        c = Correlator(db)
        series = c._get_daily_series("test.window", window_days=60)
        assert len(series) == 1
        assert list(series.values())[0] == pytest.approx(10.0)

    def test_empty(self, db):
        """No events for the module returns an empty dict."""
        c = Correlator(db)
        series = c._get_daily_series("nonexistent.module", window_days=60)
        assert series == {}


# ──────────────────────────────────────────────────────────────
# 2. _align_series
# ──────────────────────────────────────────────────────────────


class TestAlignSeries:
    """Tests for Correlator._align_series."""

    def test_perfect_overlap(self, db):
        """Two series with identical date keys align fully."""
        c = Correlator(db)
        sa = {"2026-02-01": 1.0, "2026-02-02": 2.0, "2026-02-03": 3.0}
        sb = {"2026-02-01": 10.0, "2026-02-02": 20.0, "2026-02-03": 30.0}
        aligned = c._align_series(sa, sb)
        assert len(aligned) == 3
        assert aligned[0] == ("2026-02-01", 1.0, 10.0)
        assert aligned[2] == ("2026-02-03", 3.0, 30.0)

    def test_partial_overlap(self, db):
        """Only overlapping dates are returned."""
        c = Correlator(db)
        sa = {"2026-02-01": 1.0, "2026-02-02": 2.0, "2026-02-03": 3.0}
        sb = {"2026-02-02": 20.0, "2026-02-03": 30.0, "2026-02-04": 40.0}
        aligned = c._align_series(sa, sb)
        assert len(aligned) == 2
        dates = [a[0] for a in aligned]
        assert "2026-02-01" not in dates
        assert "2026-02-04" not in dates

    def test_no_overlap(self, db):
        """Disjoint series return empty alignment."""
        c = Correlator(db)
        sa = {"2026-02-01": 1.0, "2026-02-02": 2.0}
        sb = {"2026-02-10": 10.0, "2026-02-11": 20.0}
        aligned = c._align_series(sa, sb)
        assert aligned == []

    def test_with_lag(self, db):
        """Lag shifts the lookup date for series_b."""
        c = Correlator(db)
        # A has Feb 1, B has Feb 2. With lag_days=1, A[Feb 1] pairs with B[Feb 1+1=Feb 2]
        sa = {"2026-02-01": 5.0}
        sb = {"2026-02-02": 50.0}
        aligned = c._align_series(sa, sb, lag_days=1)
        assert len(aligned) == 1
        assert aligned[0] == ("2026-02-01", 5.0, 50.0)

    def test_empty_series(self, db):
        """Empty input series returns empty alignment."""
        c = Correlator(db)
        assert c._align_series({}, {"2026-02-01": 1.0}) == []
        assert c._align_series({"2026-02-01": 1.0}, {}) == []
        assert c._align_series({}, {}) == []


# ──────────────────────────────────────────────────────────────
# 3. correlate
# ──────────────────────────────────────────────────────────────


class TestCorrelate:
    """Tests for Correlator.correlate using real DB events."""

    def test_perfect_positive(self, db):
        """Two perfectly correlated metrics yield r ~ 1.0."""
        values_a = [float(i) for i in range(30)]
        values_b = [float(i * 2) for i in range(30)]  # perfect linear
        _insert_daily_series(db, "corr.pos_a", values_a)
        _insert_daily_series(db, "corr.pos_b", values_b)
        c = Correlator(db)
        result = c.correlate("corr.pos_a", "corr.pos_b", window_days=60)
        assert "error" not in result
        assert result["pearson_r"] == pytest.approx(1.0, abs=0.001)
        assert result["spearman_rho"] == pytest.approx(1.0, abs=0.001)
        assert result["n"] == 30
        assert result["effect_size"] == "very_strong"
        assert result["significant"] is True

    def test_perfect_negative(self, db):
        """Two perfectly anti-correlated metrics yield r ~ -1.0."""
        values_a = [float(i) for i in range(30)]
        values_b = [float(30 - i) for i in range(30)]  # perfect negative linear
        _insert_daily_series(db, "corr.neg_a", values_a)
        _insert_daily_series(db, "corr.neg_b", values_b)
        c = Correlator(db)
        result = c.correlate("corr.neg_a", "corr.neg_b", window_days=60)
        assert "error" not in result
        assert result["pearson_r"] == pytest.approx(-1.0, abs=0.001)
        assert result["spearman_rho"] == pytest.approx(-1.0, abs=0.001)
        assert result["n"] == 30

    def test_insufficient_data(self, db):
        """Fewer than 7 co-occurring days returns error dict."""
        values = [1.0, 2.0, 3.0]  # only 3 days
        _insert_daily_series(db, "corr.few_a", values)
        _insert_daily_series(db, "corr.few_b", values)
        c = Correlator(db)
        result = c.correlate("corr.few_a", "corr.few_b", window_days=60)
        assert result["error"] == "insufficient_data"
        assert result["n"] < 7
        assert result["confidence_tier"] == "none"

    def test_confidence_tier_exploratory(self, db):
        """Between 7 and 13 data points -> exploratory tier."""
        values = [float(i) for i in range(10)]
        _insert_daily_series(db, "corr.exp_a", values)
        _insert_daily_series(db, "corr.exp_b", values)
        c = Correlator(db)
        result = c.correlate("corr.exp_a", "corr.exp_b", window_days=60)
        assert "error" not in result
        assert result["confidence_tier"] == "exploratory"
        assert result["n"] == 10

    def test_confidence_tier_preliminary(self, db):
        """Between 14 and 29 data points -> preliminary tier."""
        values = [float(i) for i in range(20)]
        _insert_daily_series(db, "corr.pre_a", values)
        _insert_daily_series(db, "corr.pre_b", values)
        c = Correlator(db)
        result = c.correlate("corr.pre_a", "corr.pre_b", window_days=60)
        assert "error" not in result
        assert result["confidence_tier"] == "preliminary"

    def test_confidence_tier_reliable(self, db):
        """30+ data points -> reliable tier."""
        values = [float(i) for i in range(30)]
        _insert_daily_series(db, "corr.rel_a", values)
        _insert_daily_series(db, "corr.rel_b", values)
        c = Correlator(db)
        result = c.correlate("corr.rel_a", "corr.rel_b", window_days=60)
        assert "error" not in result
        assert result["confidence_tier"] == "reliable"
        assert result["n"] == 30


# ──────────────────────────────────────────────────────────────
# 4. _correlate_from_series
# ──────────────────────────────────────────────────────────────


class TestCorrelateFromSeries:
    """Tests for Correlator._correlate_from_series with pre-built dicts."""

    def test_perfect_positive_from_series(self, db):
        """Pre-built perfectly correlated series yield r ~ 1.0."""
        c = Correlator(db)
        dates = [(BASE_DATE + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
        sa = {d: float(i) for i, d in enumerate(dates)}
        sb = {d: float(i * 3) for i, d in enumerate(dates)}
        result = c._correlate_from_series("a", "b", sa, sb, window_days=60)
        assert "error" not in result
        assert result["pearson_r"] == pytest.approx(1.0, abs=0.001)
        assert result["n"] == 30

    def test_perfect_negative_from_series(self, db):
        """Pre-built perfectly anti-correlated series yield r ~ -1.0."""
        c = Correlator(db)
        dates = [(BASE_DATE + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)]
        sa = {d: float(i) for i, d in enumerate(dates)}
        sb = {d: float(30 - i) for i, d in enumerate(dates)}
        result = c._correlate_from_series("a", "b", sa, sb, window_days=60)
        assert "error" not in result
        assert result["pearson_r"] == pytest.approx(-1.0, abs=0.001)

    def test_insufficient_from_series(self, db):
        """Fewer than 7 overlapping days returns error dict."""
        c = Correlator(db)
        sa = {"2026-02-01": 1.0, "2026-02-02": 2.0}
        sb = {"2026-02-01": 10.0, "2026-02-02": 20.0}
        result = c._correlate_from_series("a", "b", sa, sb)
        assert result["error"] == "insufficient_data"
        assert result["confidence_tier"] == "none"

    def test_result_fields(self, db):
        """Result dict contains all expected keys."""
        c = Correlator(db)
        dates = [(BASE_DATE + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(15)]
        sa = {d: float(i) for i, d in enumerate(dates)}
        sb = {d: float(i ** 2) for i, d in enumerate(dates)}
        result = c._correlate_from_series("metric.a", "metric.b", sa, sb, window_days=60, lag_days=0)
        expected_keys = {
            "metric_a", "metric_b", "window_days", "lag_days",
            "pearson_r", "spearman_rho", "p_value", "n",
            "significant", "effect_size", "confidence_tier",
        }
        assert expected_keys == set(result.keys())
        assert result["metric_a"] == "metric.a"
        assert result["metric_b"] == "metric.b"


# ──────────────────────────────────────────────────────────────
# 5. run_correlation_matrix
# ──────────────────────────────────────────────────────────────


class TestRunCorrelationMatrix:
    """Tests for Correlator.run_correlation_matrix."""

    def test_three_metrics_all_pairs(self, db):
        """Three metrics produce up to 3 pairwise results."""
        # Insert 30 days of correlated data for 3 metrics
        vals_a = [float(i) for i in range(30)]
        vals_b = [float(i * 2) for i in range(30)]
        vals_c = [float(i * 3) for i in range(30)]
        _insert_daily_series(db, "mat.a", vals_a)
        _insert_daily_series(db, "mat.b", vals_b)
        _insert_daily_series(db, "mat.c", vals_c)

        c = Correlator(db)
        result = c.run_correlation_matrix(["mat.a", "mat.b", "mat.c"], window_days=60)

        assert "matrix" in result
        assert "strongest" in result
        assert "significant_only" in result
        # 3 metrics -> C(3,2) = 3 pairs
        assert len(result["matrix"]) == 3
        # All pairs should be significant with perfect correlation
        assert len(result["significant_only"]) == 3

    def test_empty_metrics(self, db):
        """Empty metrics list returns empty matrix."""
        c = Correlator(db)
        result = c.run_correlation_matrix([], window_days=60)
        assert result["matrix"] == []
        assert result["strongest"] == []
        assert result["significant_only"] == []

    def test_single_metric(self, db):
        """Single metric produces no pairs."""
        _insert_daily_series(db, "mat.solo", [float(i) for i in range(30)])
        c = Correlator(db)
        result = c.run_correlation_matrix(["mat.solo"], window_days=60)
        assert result["matrix"] == []

    def test_insufficient_data_pairs_excluded(self, db):
        """Pairs with insufficient data are excluded from matrix results."""
        # Only 3 days of data — not enough for correlation
        vals = [1.0, 2.0, 3.0]
        _insert_daily_series(db, "mat.short_a", vals)
        _insert_daily_series(db, "mat.short_b", vals)
        c = Correlator(db)
        result = c.run_correlation_matrix(
            ["mat.short_a", "mat.short_b"], window_days=60
        )
        # Pairs with errors are excluded from matrix
        assert result["matrix"] == []


# ──────────────────────────────────────────────────────────────
# 6. lagged_analysis
# ──────────────────────────────────────────────────────────────


class TestLaggedAnalysis:
    """Tests for Correlator.lagged_analysis."""

    def test_returns_results_for_each_lag(self, db):
        """lagged_analysis returns one result per lag value."""
        values = [float(i) for i in range(30)]
        _insert_daily_series(db, "lag.a", values)
        _insert_daily_series(db, "lag.b", values)
        c = Correlator(db)
        results = c.lagged_analysis("lag.a", "lag.b", max_lag_days=3)
        # Range is -3 to +3 inclusive = 7 results
        assert len(results) == 7
        lags = [r["lag_days"] for r in results]
        assert lags == [-3, -2, -1, 0, 1, 2, 3]

    def test_lag_zero_has_highest_correlation(self, db):
        """For identical series, lag=0 should have the strongest correlation."""
        values = [float(i) for i in range(30)]
        _insert_daily_series(db, "lag.same_a", values)
        _insert_daily_series(db, "lag.same_b", values)
        c = Correlator(db)
        results = c.lagged_analysis("lag.same_a", "lag.same_b", max_lag_days=2)
        # Find the lag=0 result
        lag0 = [r for r in results if r["lag_days"] == 0][0]
        assert "error" not in lag0
        assert lag0["pearson_r"] == pytest.approx(1.0, abs=0.001)

    def test_max_lag_one(self, db):
        """max_lag_days=1 returns lags -1, 0, +1."""
        values = [float(i) for i in range(10)]
        _insert_daily_series(db, "lag.one_a", values)
        _insert_daily_series(db, "lag.one_b", values)
        c = Correlator(db)
        results = c.lagged_analysis("lag.one_a", "lag.one_b", max_lag_days=1)
        assert len(results) == 3
        assert [r["lag_days"] for r in results] == [-1, 0, 1]


# ──────────────────────────────────────────────────────────────
# 7. confidence_tier (static method)
# ──────────────────────────────────────────────────────────────


class TestConfidenceTier:
    """Tests for Correlator.confidence_tier static method."""

    def test_exploratory(self):
        """n < 14 -> exploratory."""
        assert Correlator.confidence_tier(0) == "exploratory"
        assert Correlator.confidence_tier(7) == "exploratory"
        assert Correlator.confidence_tier(13) == "exploratory"

    def test_preliminary(self):
        """14 <= n < 30 -> preliminary."""
        assert Correlator.confidence_tier(14) == "preliminary"
        assert Correlator.confidence_tier(20) == "preliminary"
        assert Correlator.confidence_tier(29) == "preliminary"

    def test_reliable(self):
        """n >= 30 -> reliable."""
        assert Correlator.confidence_tier(30) == "reliable"
        assert Correlator.confidence_tier(100) == "reliable"
        assert Correlator.confidence_tier(365) == "reliable"


# ──────────────────────────────────────────────────────────────
# 8. _interpret_r (static method)
# ──────────────────────────────────────────────────────────────


class TestInterpretR:
    """Tests for Correlator._interpret_r static method."""

    def test_negligible(self):
        """abs(r) < 0.1 -> negligible."""
        assert Correlator._interpret_r(0.0) == "negligible"
        assert Correlator._interpret_r(0.05) == "negligible"
        assert Correlator._interpret_r(-0.09) == "negligible"

    def test_weak(self):
        """0.1 <= abs(r) < 0.3 -> weak."""
        assert Correlator._interpret_r(0.1) == "weak"
        assert Correlator._interpret_r(0.2) == "weak"
        assert Correlator._interpret_r(-0.29) == "weak"

    def test_moderate(self):
        """0.3 <= abs(r) < 0.5 -> moderate."""
        assert Correlator._interpret_r(0.3) == "moderate"
        assert Correlator._interpret_r(0.4) == "moderate"
        assert Correlator._interpret_r(-0.49) == "moderate"

    def test_strong(self):
        """0.5 <= abs(r) < 0.7 -> strong."""
        assert Correlator._interpret_r(0.5) == "strong"
        assert Correlator._interpret_r(0.6) == "strong"
        assert Correlator._interpret_r(-0.69) == "strong"

    def test_very_strong(self):
        """abs(r) >= 0.7 -> very_strong."""
        assert Correlator._interpret_r(0.7) == "very_strong"
        assert Correlator._interpret_r(0.95) == "very_strong"
        assert Correlator._interpret_r(-1.0) == "very_strong"
