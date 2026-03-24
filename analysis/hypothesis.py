"""
LifeData V4 — Hypothesis Testing Framework
analysis/hypothesis.py

Formal hypothesis testing using collected data.
Pre-defines the key research questions of the LifeData project.
"""

from typing import Optional

from analysis.correlator import Correlator
from core.logger import get_logger

log = get_logger("lifedata.analysis.hypothesis")


class HypothesisTest:
    """A formal test of a specific hypothesis using collected data."""

    def __init__(
        self,
        name: str,
        metric_a: str,
        metric_b: str,
        direction: str,
        threshold: float = 0.05,
    ):
        """
        Args:
            name: Human-readable hypothesis statement.
            metric_a: First metric source_module.
            metric_b: Second metric source_module.
            direction: Expected direction: 'positive', 'negative', or 'any'.
            threshold: p-value significance threshold (default 0.05).
        """
        self.name = name
        self.metric_a = metric_a
        self.metric_b = metric_b
        self.direction = direction
        self.threshold = threshold

    def test(self, db, window_days: int = 90) -> dict:
        """Run the hypothesis test against the database.

        Returns a dict with test results including whether the
        hypothesis is supported by the data.
        """
        corr = Correlator(db)
        result = corr.correlate(
            self.metric_a, self.metric_b, window_days=window_days
        )

        if "error" in result:
            return {
                "hypothesis": self.name,
                "status": "insufficient_data",
                "n": result.get("n", 0),
                "message": result.get("message", ""),
            }

        supported = False
        r = result["pearson_r"]
        p = result["p_value"]

        if self.direction == "negative" and r < 0 and p < self.threshold:
            supported = True
        elif self.direction == "positive" and r > 0 and p < self.threshold:
            supported = True
        elif self.direction == "any" and p < self.threshold:
            supported = True

        return {
            "hypothesis": self.name,
            "supported": supported,
            "status": "supported" if supported else "not_supported",
            "direction_expected": self.direction,
            "pearson_r": result["pearson_r"],
            "p_value": result["p_value"],
            "effect_size": result["effect_size"],
            "n": result["n"],
            "confidence_tier": result["confidence_tier"],
            "needs_more_data": result["n"] < 30,
        }

    def __repr__(self) -> str:
        return f"HypothesisTest('{self.name}')"


# ──────────────────────────────────────────────────────────────
# Pre-defined hypotheses — the core research questions
# ──────────────────────────────────────────────────────────────

HYPOTHESES = [
    HypothesisTest(
        "Geomagnetic storms reduce mood",
        "environment.geomagnetic", "mind.mood",
        direction="negative",
    ),
    HypothesisTest(
        "Morning light exposure improves energy",
        "environment.hourly", "mind.energy",
        direction="positive",
    ),
    HypothesisTest(
        "Afternoon caffeine disrupts sleep",
        "body.caffeine", "body.sleep_quality",
        direction="negative",
    ),
    HypothesisTest(
        "Social interaction improves next-day mood",
        "social.density_score", "mind.mood",
        direction="positive",
    ),
    HypothesisTest(
        "High notification volume reduces focus",
        "social.notification", "mind.focus",
        direction="negative",
    ),
    HypothesisTest(
        "Negative news sentiment predicts lower mood",
        "world.news_sentiment", "mind.mood",
        direction="positive",
    ),
]


def run_all_hypotheses(db, window_days: int = 90) -> list[dict]:
    """Run all pre-defined hypothesis tests.

    Returns list of results sorted by significance.
    """
    results = []
    for h in HYPOTHESES:
        result = h.test(db, window_days)
        results.append(result)
        status = result["status"]
        log.info(f"Hypothesis '{h.name}': {status}")

    # Sort: supported first, then by p-value
    results.sort(
        key=lambda x: (
            0 if x["status"] == "supported" else 1,
            x.get("p_value", 1.0),
        )
    )
    return results
