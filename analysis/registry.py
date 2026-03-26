"""
LifeData V4 — Metrics Registry
analysis/registry.py

Aggregates metrics manifests from modules and analysis config.
The analysis layer reads this registry instead of hardcoding module names.
"""

from __future__ import annotations

import operator

from core.logger import get_logger

log = get_logger("lifedata.analysis.registry")

# Operator mapping for config-driven pattern conditions
_OPS = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


class MetricsRegistry:
    """Central registry of all module metrics and analysis configuration."""

    def __init__(
        self,
        modules: list | None = None,
        config: dict | None = None,
    ):
        self._metrics: dict[str, dict] = {}
        self._config = config or {}
        self._analysis = self._config.get("lifedata", {}).get("analysis", {})

        if modules:
            for m in modules:
                manifest = m.get_metrics_manifest()
                for metric in manifest.get("metrics", []):
                    self._metrics[metric["name"]] = metric

    def get_metric(self, name: str) -> dict | None:
        """Look up a metric declaration by source_module name."""
        return self._metrics.get(name)

    def get_all_metrics(self) -> list[dict]:
        """Return all registered metrics."""
        return list(self._metrics.values())

    def get_anomaly_eligible(self) -> list[dict]:
        """Return metrics flagged for z-score anomaly detection."""
        return [m for m in self._metrics.values() if m.get("anomaly_eligible")]

    def get_trend_metrics(self) -> list[dict]:
        """Return metrics configured for trend display.

        Reads from config analysis.report.trend_metrics if available,
        otherwise returns metrics flagged trend_eligible in manifests.
        """
        report_cfg = self._analysis.get("report", {})
        configured = report_cfg.get("trend_metrics", [])
        if configured:
            result = []
            for name in configured:
                metric = self._metrics.get(name)
                if metric:
                    result.append(metric)
                else:
                    log.warning(f"Trend metric '{name}' not found in any module manifest")
            return result
        return [m for m in self._metrics.values() if m.get("trend_eligible")]

    def get_patterns(self) -> list[dict]:
        """Return compound anomaly patterns from config."""
        return [p for p in self._analysis.get("patterns", []) if p.get("enabled", True)]

    def get_hypotheses(self) -> list[dict]:
        """Return hypothesis definitions from config."""
        return [h for h in self._analysis.get("hypotheses", []) if h.get("enabled", True)]

    def get_report_sections(self) -> list[dict]:
        """Return report section configuration."""
        report_cfg = self._analysis.get("report", {})
        return [s for s in report_cfg.get("sections", []) if s.get("enabled", True)]

    @staticmethod
    def evaluate_condition(op_str: str, value: float, threshold: float) -> bool:
        """Evaluate a condition like '< 20' against a value."""
        op_fn = _OPS.get(op_str)
        if op_fn is None:
            log.warning(f"Unknown operator '{op_str}', defaulting to '<'")
            op_fn = operator.lt
        return op_fn(value, threshold)
