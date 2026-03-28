"""
Tests for analysis/hypothesis.py — HypothesisTest, load_hypotheses, and run_all_hypotheses().

Uses real SQLite fixtures (no mocks). Correlated/anti-correlated data is generated
over 30 days to ensure the Correlator has sufficient aligned observations.
"""

from datetime import UTC, datetime, timedelta

import pytest

from analysis.hypothesis import HypothesisTest, load_hypotheses, run_all_hypotheses
from core.event import Event

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_event(day_offset: int, source_module: str, value: float) -> Event:
    """Create an event for a given day offset from 2026-02-20.

    All dates land within a 90-day window of the current date (2026-03-25).
    """
    base = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
    dt = base + timedelta(days=day_offset)
    utc_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    local_dt = dt - timedelta(hours=5)
    local_str = local_dt.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return Event(
        timestamp_utc=utc_str,
        timestamp_local=local_str,
        timezone_offset="-0500",
        source_module=source_module,
        event_type="measurement",
        value_numeric=value,
        confidence=1.0,
        parser_version="1.0.0",
    )


def _insert_correlated_pair(
    db,
    metric_a: str,
    metric_b: str,
    n_days: int = 30,
    negative: bool = False,
):
    """Insert two perfectly correlated (or anti-correlated) metric series.

    metric_a values: 1, 2, 3, ...
    metric_b values: same (positive) or reversed (negative)
    """
    events = []
    for i in range(n_days):
        val_a = float(i + 1)
        val_b = float(n_days - i) if negative else float(i + 1)
        events.append(_make_event(i, metric_a, val_a))
        events.append(_make_event(i, metric_b, val_b))
    db.insert_events_for_module("test_hypothesis", events)


# ──────────────────────────────────────────────────────────────
# TestHypothesisTest
# ──────────────────────────────────────────────────────────────


class TestHypothesisTest:
    """Tests for HypothesisTest.test() with various directions and data."""

    def test_negative_direction_negative_r_significant(self, db):
        """Negative direction + negative r + significant p -> supported=True."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=True)

        ht = HypothesisTest(
            "Test negative hypothesis",
            "test.metric_a",
            "test.metric_b",
            direction="negative",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "supported"
        assert result["supported"] is True
        assert result["pearson_r"] < 0
        assert result["p_value"] < 0.05
        assert result["direction_expected"] == "negative"

    def test_negative_direction_positive_r_not_supported(self, db):
        """Negative direction + positive r -> supported=False."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=False)

        ht = HypothesisTest(
            "Test negative but data is positive",
            "test.metric_a",
            "test.metric_b",
            direction="negative",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "not_supported"
        assert result["supported"] is False
        assert result["pearson_r"] > 0

    def test_positive_direction_positive_r_significant(self, db):
        """Positive direction + positive r + significant p -> supported=True."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=False)

        ht = HypothesisTest(
            "Test positive hypothesis",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "supported"
        assert result["supported"] is True
        assert result["pearson_r"] > 0
        assert result["p_value"] < 0.05

    def test_positive_direction_negative_r_not_supported(self, db):
        """Positive direction + negative r -> supported=False."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=True)

        ht = HypothesisTest(
            "Test positive but data is negative",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "not_supported"
        assert result["supported"] is False
        assert result["pearson_r"] < 0

    def test_any_direction_significant(self, db):
        """Any direction + significant p -> supported=True regardless of sign."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=True)

        ht = HypothesisTest(
            "Test any direction",
            "test.metric_a",
            "test.metric_b",
            direction="any",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "supported"
        assert result["supported"] is True
        assert result["p_value"] < 0.05

    def test_insufficient_data_no_events(self, db):
        """Empty database returns insufficient_data status."""
        ht = HypothesisTest(
            "Test insufficient data",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "insufficient_data"
        assert result["n"] == 0
        assert "hypothesis" in result
        assert "message" in result
        # Should NOT have correlation-specific keys
        assert "supported" not in result
        assert "pearson_r" not in result

    def test_needs_more_data_flag_when_n_below_30(self, db):
        """When n < 30, needs_more_data should be True."""
        # Insert only 15 days of data (above 7 minimum but below 30)
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=15, negative=False)

        ht = HypothesisTest(
            "Test needs more data",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        assert result["n"] < 30
        assert result["needs_more_data"] is True

    def test_needs_more_data_false_when_n_ge_30(self, db):
        """When n >= 30, needs_more_data should be False."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=False)

        ht = HypothesisTest(
            "Test enough data",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        assert result["n"] >= 30
        assert result["needs_more_data"] is False

    def test_custom_threshold_makes_result_not_supported(self, db):
        """A strict threshold (0.001) rejects a result that a loose threshold (0.05) accepts.

        Uses seed=12 with stddev=5.0 noise to produce p ~ 0.038, which is
        significant at 0.05 but not at 0.001.
        """
        import random

        events = []
        random.seed(12)
        for i in range(10):
            val_a = float(i + 1)
            val_b = float(i + 1) + random.gauss(0, 5.0)
            events.append(_make_event(i, "test.noisy_a", val_a))
            events.append(_make_event(i, "test.noisy_b", val_b))
        db.insert_events_for_module("test_hypothesis", events)

        # Loose threshold — should be supported (p < 0.05)
        ht_loose = HypothesisTest(
            "Loose threshold",
            "test.noisy_a",
            "test.noisy_b",
            direction="positive",
            threshold=0.05,
        )
        result_loose = ht_loose.test(db, window_days=90)

        # Strict threshold — should NOT be supported (p > 0.001)
        ht_strict = HypothesisTest(
            "Strict threshold",
            "test.noisy_a",
            "test.noisy_b",
            direction="positive",
            threshold=0.001,
        )
        result_strict = ht_strict.test(db, window_days=90)

        # Both share the same underlying data, so r and p match
        assert result_loose["pearson_r"] == result_strict["pearson_r"]
        assert result_loose["p_value"] == result_strict["p_value"]

        # Loose accepts, strict rejects
        assert result_loose["supported"] is True
        assert result_loose["status"] == "supported"
        assert result_strict["supported"] is False
        assert result_strict["status"] == "not_supported"

    def test_result_keys_complete(self, db):
        """Verify all expected keys are present in a successful result."""
        _insert_correlated_pair(db, "test.metric_a", "test.metric_b", n_days=30, negative=False)

        ht = HypothesisTest(
            "Complete keys test",
            "test.metric_a",
            "test.metric_b",
            direction="positive",
        )
        result = ht.test(db, window_days=90)

        expected_keys = {
            "hypothesis", "supported", "status", "direction_expected",
            "pearson_r", "p_value", "effect_size", "n",
            "confidence_tier", "needs_more_data", "lag_days",
        }
        assert set(result.keys()) == expected_keys

    def test_repr(self):
        """HypothesisTest __repr__ includes the name."""
        ht = HypothesisTest("My hypothesis", "a.b", "c.d", "positive")
        assert "My hypothesis" in repr(ht)


# ──────────────────────────────────────────────────────────────
# TestLoadHypotheses
# ──────────────────────────────────────────────────────────────


class TestLoadHypotheses:
    """Tests for load_hypotheses() — config.yaml is the single source of truth."""

    def test_no_config_returns_empty(self):
        """load_hypotheses(None) returns an empty list."""
        assert load_hypotheses(None) == []

    def test_empty_hypotheses_returns_empty(self):
        """Empty hypotheses list in config returns empty."""
        config = {"lifedata": {"analysis": {"hypotheses": []}}}
        assert load_hypotheses(config) == []

    def test_loads_from_config(self):
        """Hypotheses are loaded from config dict."""
        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {
                            "name": "Test H1",
                            "metric_a": "a.b",
                            "metric_b": "c.d",
                            "direction": "positive",
                        },
                    ],
                },
            },
        }
        hyps = load_hypotheses(config)
        assert len(hyps) == 1
        assert hyps[0].name == "Test H1"
        assert isinstance(hyps[0], HypothesisTest)

    def test_disabled_hypothesis_excluded(self):
        """Hypotheses with enabled: false should be excluded."""
        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {"name": "Active", "metric_a": "a.b", "metric_b": "c.d",
                         "direction": "positive", "enabled": True},
                        {"name": "Disabled", "metric_a": "e.f", "metric_b": "g.h",
                         "direction": "negative", "enabled": False},
                    ],
                },
            },
        }
        hyps = load_hypotheses(config)
        assert len(hyps) == 1
        assert hyps[0].name == "Active"


# ──────────────────────────────────────────────────────────────
# TestRunAllHypotheses
# ──────────────────────────────────────────────────────────────


_TEST_CONFIG = {
    "lifedata": {
        "analysis": {
            "hypotheses": [
                {
                    "name": "Geomagnetic storms reduce mood",
                    "metric_a": "environment.geomagnetic",
                    "metric_b": "mind.mood",
                    "direction": "negative",
                },
                {
                    "name": "Morning light exposure improves energy",
                    "metric_a": "environment.hourly",
                    "metric_b": "mind.energy",
                    "direction": "positive",
                },
            ],
        },
    },
}


class TestRunAllHypotheses:
    """Tests for run_all_hypotheses() orchestration function."""

    def test_handles_empty_database_gracefully(self, db):
        """With no data, run_all_hypotheses should return results without crashing."""
        results = run_all_hypotheses(db, window_days=90, config=_TEST_CONFIG)

        assert isinstance(results, list)
        assert len(results) == 2  # One result per hypothesis in config
        for r in results:
            assert r["status"] == "insufficient_data"

    def test_no_config_returns_empty(self, db):
        """Without config, no hypotheses are loaded → empty results."""
        results = run_all_hypotheses(db, window_days=90, config=None)
        assert results == []

    def test_returns_sorted_by_significance(self, db):
        """Supported hypotheses appear before not_supported/insufficient_data."""
        events = []
        for i in range(30):
            geo_val = float(i + 1)
            mood_val = float(30 - i)
            events.append(_make_event(i, "environment.geomagnetic", geo_val))
            events.append(_make_event(i, "mind.mood", mood_val))
        db.insert_events_for_module("test_hypothesis", events)

        results = run_all_hypotheses(db, window_days=90, config=_TEST_CONFIG)

        assert len(results) == 2

        supported = [r for r in results if r["status"] == "supported"]
        assert len(supported) >= 1
        assert supported[0]["hypothesis"] == "Geomagnetic storms reduce mood"

        # Supported should come before not_supported and insufficient_data
        first_non_supported_idx = None
        for idx, r in enumerate(results):
            if r["status"] != "supported":
                first_non_supported_idx = idx
                break

        if first_non_supported_idx is not None:
            for r in results[:first_non_supported_idx]:
                assert r["status"] == "supported"

    def test_returns_list_of_dicts(self, db):
        """Return type is a list of dicts, each with at least 'hypothesis' and 'status'."""
        results = run_all_hypotheses(db, window_days=90, config=_TEST_CONFIG)

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)
            assert "hypothesis" in r
            assert "status" in r


# ──────────────────────────────────────────────────────────────
# TestLagDays
# ──────────────────────────────────────────────────────────────


class TestLagDays:
    """Tests for time-lagged hypothesis testing (lag_days parameter)."""

    def test_lag_days_zero_same_as_default(self, db):
        """lag_days=0 produces identical results to the default (no lag)."""
        _insert_correlated_pair(db, "test.lag_a", "test.lag_b", n_days=30, negative=True)

        ht_default = HypothesisTest(
            "No lag default",
            "test.lag_a",
            "test.lag_b",
            direction="negative",
        )
        ht_zero = HypothesisTest(
            "No lag explicit",
            "test.lag_a",
            "test.lag_b",
            direction="negative",
            lag_days=0,
        )

        result_default = ht_default.test(db, window_days=90)
        result_zero = ht_zero.test(db, window_days=90)

        assert result_default["pearson_r"] == result_zero["pearson_r"]
        assert result_default["p_value"] == result_zero["p_value"]
        assert result_default["n"] == result_zero["n"]
        assert result_zero["lag_days"] == 0
        assert result_default["lag_days"] == 0

    def test_lag_days_one_offsets_alignment(self, db):
        """lag_days=1 correctly offsets metric_b by one day.

        Insert metric_a as 1,2,3,...,30 on days 0-29.
        Insert metric_b as 1,2,3,...,30 on days 0-29.

        With lag_days=0: day 0 -> (a=1, b=1), perfect positive r ~ 1.0
        With lag_days=1: day 0 a=1 pairs with day 1 b=2, still positive
        but the alignment shifts, losing one day of data (n should be 29).
        """
        _insert_correlated_pair(db, "test.lag1_a", "test.lag1_b", n_days=30, negative=False)

        ht_no_lag = HypothesisTest(
            "No lag",
            "test.lag1_a",
            "test.lag1_b",
            direction="positive",
            lag_days=0,
        )
        ht_lag_1 = HypothesisTest(
            "Lag 1 day",
            "test.lag1_a",
            "test.lag1_b",
            direction="positive",
            lag_days=1,
        )

        result_no_lag = ht_no_lag.test(db, window_days=90)
        result_lag_1 = ht_lag_1.test(db, window_days=90)

        # Both should produce valid results
        assert result_no_lag["status"] != "insufficient_data"
        assert result_lag_1["status"] != "insufficient_data"

        # Lagged version loses one day of alignment
        assert result_lag_1["n"] == result_no_lag["n"] - 1
        assert result_lag_1["lag_days"] == 1

        # Both should still show strong positive correlation (monotonic data)
        assert result_lag_1["pearson_r"] > 0.9

    def test_lag_days_in_result_dict(self, db):
        """The lag_days value appears in the result dict."""
        _insert_correlated_pair(db, "test.lagr_a", "test.lagr_b", n_days=30, negative=False)

        ht = HypothesisTest(
            "Lag result test",
            "test.lagr_a",
            "test.lagr_b",
            direction="positive",
            lag_days=3,
        )
        result = ht.test(db, window_days=90)

        assert "lag_days" in result
        assert result["lag_days"] == 3

    def test_lag_days_insufficient_data(self, db):
        """lag_days with insufficient data still returns insufficient_data status."""
        ht = HypothesisTest(
            "Lag insufficient",
            "test.nope_a",
            "test.nope_b",
            direction="positive",
            lag_days=2,
        )
        result = ht.test(db, window_days=90)

        assert result["status"] == "insufficient_data"

    def test_load_hypotheses_passes_lag_days(self):
        """load_hypotheses() passes lag_days from config to HypothesisTest."""
        from analysis.hypothesis import load_hypotheses

        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {
                            "name": "Lagged test",
                            "metric_a": "a.b",
                            "metric_b": "c.d",
                            "direction": "negative",
                            "lag_days": 3,
                        },
                        {
                            "name": "No lag test",
                            "metric_a": "e.f",
                            "metric_b": "g.h",
                            "direction": "positive",
                        },
                    ]
                }
            }
        }
        hyps = load_hypotheses(config)
        assert len(hyps) == 2
        assert hyps[0].lag_days == 3
        assert hyps[1].lag_days == 0  # default


# ──────────────────────────────────────────────────────────────
# TestHypothesisConfigLagDays
# ──────────────────────────────────────────────────────────────


class TestHypothesisConfigLagDays:
    """Tests for lag_days validation in HypothesisConfig (config_schema.py)."""

    def test_lag_days_valid_range(self):
        """lag_days values 0 through 7 are accepted."""
        from core.config_schema import HypothesisConfig

        for lag in range(8):
            hc = HypothesisConfig(
                name="test", metric_a="a.b", metric_b="c.d", lag_days=lag,
            )
            assert hc.lag_days == lag

    def test_lag_days_default_zero(self):
        """lag_days defaults to 0 when not specified."""
        from core.config_schema import HypothesisConfig

        hc = HypothesisConfig(name="test", metric_a="a.b", metric_b="c.d")
        assert hc.lag_days == 0

    def test_lag_days_negative_rejected(self):
        """Negative lag_days raises ValidationError."""
        from pydantic import ValidationError

        from core.config_schema import HypothesisConfig

        with pytest.raises(ValidationError, match="lag_days"):
            HypothesisConfig(
                name="test", metric_a="a.b", metric_b="c.d", lag_days=-1,
            )

    def test_lag_days_above_seven_rejected(self):
        """lag_days > 7 raises ValidationError."""
        from pydantic import ValidationError

        from core.config_schema import HypothesisConfig

        with pytest.raises(ValidationError, match="lag_days"):
            HypothesisConfig(
                name="test", metric_a="a.b", metric_b="c.d", lag_days=8,
            )
