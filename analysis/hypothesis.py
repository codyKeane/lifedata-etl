"""
LifeData V4 — Hypothesis Testing Framework
analysis/hypothesis.py

Formal hypothesis testing using collected data.
Pre-defines the key research questions of the LifeData project.
"""

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
        result = corr.correlate(self.metric_a, self.metric_b, window_days=window_days)

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

        if (
            (self.direction == "negative" and r < 0 and p < self.threshold)
            or (self.direction == "positive" and r > 0 and p < self.threshold)
            or (self.direction == "any" and p < self.threshold)
        ):
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
        "environment.geomagnetic",
        "mind.mood",
        direction="negative",
    ),
    HypothesisTest(
        "Morning light exposure improves energy",
        "environment.hourly",
        "mind.energy",
        direction="positive",
    ),
    HypothesisTest(
        "Afternoon caffeine disrupts sleep",
        "body.caffeine",
        "body.sleep_quality",
        direction="negative",
    ),
    HypothesisTest(
        "Social interaction improves next-day mood",
        "social.density_score",
        "mind.mood",
        direction="positive",
    ),
    HypothesisTest(
        "High notification volume reduces focus",
        "social.notification",
        "mind.focus",
        direction="negative",
    ),
    # direction="positive" because higher sentiment score (more positive news)
    # correlates with higher mood — the hypothesis NAME describes the inverse
    # relationship but the DIRECTION describes the correlation sign.
    HypothesisTest(
        "Negative news sentiment predicts lower mood",
        "world.news_sentiment",
        "mind.mood",
        direction="positive",
    ),
    # ── Cognition hypotheses ──
    HypothesisTest(
        "Caffeine improves reaction time within 2 hours",
        "body.caffeine",
        "cognition.reaction",
        direction="negative",  # lower RT = better, caffeine should reduce RT
    ),
    HypothesisTest(
        "Sleep deprivation impairs cognitive load index",
        "body.sleep",
        "cognition.derived",
        direction="negative",  # less sleep → higher CLI (more impaired)
    ),
    HypothesisTest(
        "High stress correlates with impaired working memory",
        "mind.stress",
        "cognition.memory",
        direction="negative",  # higher stress → lower digit span
    ),
    HypothesisTest(
        "Morning cognition scores predict self-reported productivity",
        "cognition.reaction",
        "mind.focus",
        direction="negative",  # lower RT (better cognition) → higher focus rating
    ),
]


def load_hypotheses(config: dict | None = None) -> list[HypothesisTest]:
    """Load hypothesis definitions from config, falling back to HYPOTHESES.

    If config contains analysis.hypotheses, builds HypothesisTest instances
    from those definitions. Otherwise returns the hardcoded HYPOTHESES list.
    This allows users to add/remove/modify hypotheses via config.yaml.
    """
    if config is None:
        return list(HYPOTHESES)

    analysis = config.get("lifedata", {}).get("analysis", {})
    hyp_configs = analysis.get("hypotheses", [])

    if not hyp_configs:
        return list(HYPOTHESES)

    loaded = []
    for h in hyp_configs:
        if not h.get("enabled", True):
            continue
        loaded.append(
            HypothesisTest(
                name=h["name"],
                metric_a=h["metric_a"],
                metric_b=h["metric_b"],
                direction=h.get("direction", "any"),
                threshold=h.get("threshold", 0.05),
            )
        )
    return loaded


def run_all_hypotheses(
    db, window_days: int = 90, config: dict | None = None,
) -> list[dict]:
    """Run all hypothesis tests (from config or hardcoded fallback).

    Returns list of results sorted by significance.
    """
    hypotheses = load_hypotheses(config)
    results = []
    for h in hypotheses:
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
