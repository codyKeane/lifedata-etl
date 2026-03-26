"""
Tests for analysis/hypothesis.py — HypothesisTest, HYPOTHESES list, and run_all_hypotheses().

Uses real SQLite fixtures (no mocks). Correlated/anti-correlated data is generated
over 30 days to ensure the Correlator has sufficient aligned observations.
"""

import math
from datetime import UTC, datetime, timedelta

import pytest

from analysis.hypothesis import HYPOTHESES, HypothesisTest, run_all_hypotheses
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
            "confidence_tier", "needs_more_data",
        }
        assert set(result.keys()) == expected_keys

    def test_repr(self):
        """HypothesisTest __repr__ includes the name."""
        ht = HypothesisTest("My hypothesis", "a.b", "c.d", "positive")
        assert "My hypothesis" in repr(ht)


# ──────────────────────────────────────────────────────────────
# TestHypothesesList
# ──────────────────────────────────────────────────────────────


class TestHypothesesList:
    """Tests for the HYPOTHESES module-level list of 10 pre-defined hypotheses."""

    def test_count(self):
        """There should be exactly 10 pre-defined hypotheses."""
        assert len(HYPOTHESES) == 10

    def test_all_valid_directions(self):
        """Every hypothesis must have direction in {'positive', 'negative', 'any'}."""
        valid_directions = {"positive", "negative", "any"}
        for h in HYPOTHESES:
            assert h.direction in valid_directions, (
                f"Hypothesis '{h.name}' has invalid direction '{h.direction}'"
            )

    def test_all_distinct_names(self):
        """All hypothesis names must be unique."""
        names = [h.name for h in HYPOTHESES]
        assert len(names) == len(set(names)), (
            f"Duplicate hypothesis names found: "
            f"{[n for n in names if names.count(n) > 1]}"
        )

    def test_all_have_two_metric_strings(self):
        """Every hypothesis must have non-empty metric_a and metric_b strings."""
        for h in HYPOTHESES:
            assert isinstance(h.metric_a, str) and len(h.metric_a) > 0, (
                f"Hypothesis '{h.name}' has invalid metric_a"
            )
            assert isinstance(h.metric_b, str) and len(h.metric_b) > 0, (
                f"Hypothesis '{h.name}' has invalid metric_b"
            )

    def test_all_are_hypothesis_test_instances(self):
        """Every item in HYPOTHESES is a HypothesisTest instance."""
        for h in HYPOTHESES:
            assert isinstance(h, HypothesisTest)

    def test_metrics_use_dot_notation(self):
        """All metrics should use dot-notation (module.submodule)."""
        for h in HYPOTHESES:
            assert "." in h.metric_a, (
                f"Hypothesis '{h.name}' metric_a '{h.metric_a}' missing dot notation"
            )
            assert "." in h.metric_b, (
                f"Hypothesis '{h.name}' metric_b '{h.metric_b}' missing dot notation"
            )


# ──────────────────────────────────────────────────────────────
# TestRunAllHypotheses
# ──────────────────────────────────────────────────────────────


class TestRunAllHypotheses:
    """Tests for run_all_hypotheses() orchestration function."""

    def test_handles_empty_database_gracefully(self, db):
        """With no data, run_all_hypotheses should return results without crashing."""
        results = run_all_hypotheses(db, window_days=90)

        assert isinstance(results, list)
        assert len(results) == 10  # One result per hypothesis
        # All should be insufficient_data since database is empty
        for r in results:
            assert r["status"] == "insufficient_data"

    def test_returns_sorted_by_significance(self, db):
        """Supported hypotheses appear before not_supported/insufficient_data,
        and within each group results are sorted by p_value ascending."""
        # Insert data that will make ONE specific hypothesis supported.
        # Use environment.geomagnetic and mind.mood (hypothesis: "Geomagnetic storms reduce mood")
        # which expects direction="negative"
        events = []
        for i in range(30):
            # Higher geomagnetic -> lower mood (negative correlation)
            geo_val = float(i + 1)
            mood_val = float(30 - i)
            events.append(_make_event(i, "environment.geomagnetic", geo_val))
            events.append(_make_event(i, "mind.mood", mood_val))
        db.insert_events_for_module("test_hypothesis", events)

        results = run_all_hypotheses(db, window_days=90)

        assert len(results) == 10

        # Find status groups
        supported = [r for r in results if r["status"] == "supported"]
        not_supported = [r for r in results if r["status"] == "not_supported"]
        insufficient = [r for r in results if r["status"] == "insufficient_data"]

        # At least one should be supported (geomagnetic vs mood)
        assert len(supported) >= 1
        assert supported[0]["hypothesis"] == "Geomagnetic storms reduce mood"

        # Supported should come before not_supported and insufficient_data
        first_non_supported_idx = None
        for idx, r in enumerate(results):
            if r["status"] != "supported":
                first_non_supported_idx = idx
                break

        if first_non_supported_idx is not None:
            # All items before first_non_supported should be "supported"
            for r in results[:first_non_supported_idx]:
                assert r["status"] == "supported"

        # Within supported group, p_values should be ascending
        if len(supported) > 1:
            p_values = [r["p_value"] for r in supported]
            assert p_values == sorted(p_values)

    def test_returns_list_of_dicts(self, db):
        """Return type is a list of dicts, each with at least 'hypothesis' and 'status'."""
        results = run_all_hypotheses(db, window_days=90)

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, dict)
            assert "hypothesis" in r
            assert "status" in r
