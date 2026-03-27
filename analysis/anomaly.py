"""
LifeData V4 — Anomaly Detector
analysis/anomaly.py

Flags unusual events using z-score analysis against rolling baselines.
Also detects multi-variable pattern anomalies (burnout signals, caffeine-sleep).
"""

import contextlib
import statistics
from datetime import UTC, datetime, timedelta

from core.logger import get_logger

log = get_logger("lifedata.analysis.anomaly")


class AnomalyDetector:
    """Detects statistical anomalies in daily metric values."""

    def __init__(self, db, zscore_threshold: float = 2.0, config: dict | None = None):
        self.db = db
        self.threshold = zscore_threshold
        self._config = config
        self._analysis = (config or {}).get("lifedata", {}).get("analysis", {})

    def _get_distinct_numeric_metrics(self) -> list[str]:
        """Get all source_modules that have numeric data."""
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT source_module
            FROM events
            WHERE value_numeric IS NOT NULL
            ORDER BY source_module
            """
        ).fetchall()
        return [row[0] for row in rows]

    def _get_daily_metric(
        self,
        source_module: str,
        date_str: str,
        event_type: str | None = None,
        aggregate: str = "AVG",
    ) -> float | None:
        """Get an aggregated value_numeric for a metric on a specific date.

        Args:
            source_module: The source module to query.
            date_str: Date string (YYYY-MM-DD).
            event_type: Optional event_type filter.
            aggregate: SQL aggregate function (AVG, SUM, MIN, MAX, COUNT).
        """
        _AGG_SQL = {"AVG": "AVG", "SUM": "SUM", "MIN": "MIN", "MAX": "MAX", "COUNT": "COUNT"}
        agg_fn = _AGG_SQL.get(aggregate.upper(), "AVG")

        query = f"""
            SELECT {agg_fn}(value_numeric)
            FROM events
            WHERE source_module = ?
              AND date(timestamp_local) = ?
              AND value_numeric IS NOT NULL
        """
        params: list = [source_module, date_str]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)

        row = self.db.conn.execute(query, params).fetchone()
        return row[0] if row and row[0] is not None else None

    def _get_metric_history(
        self,
        source_module: str,
        days: int = 14,
        exclude_date: str | None = None,
    ) -> list[float]:
        """Get daily averages for a metric over the past N days.

        Excludes a specific date (usually today) from the baseline.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )

        query = """
            SELECT date(timestamp_local) as day, AVG(value_numeric) as avg_val
            FROM events
            WHERE source_module = ?
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) >= ?
        """
        params: list = [source_module, cutoff]

        if exclude_date:
            query += " AND date(timestamp_local) != ?"
            params.append(exclude_date)

        query += " GROUP BY day ORDER BY day"

        rows = self.db.conn.execute(query, params).fetchall()
        return [row[1] for row in rows if row[1] is not None]

    def check_today(self, date_str: str) -> list[dict]:
        """Check all numeric metrics for today against rolling baselines.

        Returns list of anomalies sorted by z-score magnitude.
        """
        anomalies = []
        metrics = self._get_distinct_numeric_metrics()

        for metric in metrics:
            today_value = self._get_daily_metric(metric, date_str)
            if today_value is None:
                continue

            baseline = self._get_metric_history(metric, days=14, exclude_date=date_str)
            if len(baseline) < 3:
                # Not enough history for meaningful anomaly detection
                continue

            # Compute z-score
            mean = statistics.mean(baseline)
            stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0

            if stdev == 0:
                continue

            zscore = (today_value - mean) / stdev

            if abs(zscore) > self.threshold:
                anomalies.append(
                    {
                        "metric": metric,
                        "today_value": round(today_value, 2),
                        "baseline_mean": round(mean, 2),
                        "baseline_std": round(stdev, 2),
                        "zscore": round(zscore, 2),
                        "direction": "high" if zscore > 0 else "low",
                        "severity": "extreme" if abs(zscore) > 3 else "notable",
                        "human_readable": self._describe(
                            metric, zscore, today_value, mean
                        ),
                    }
                )

        anomalies.sort(key=lambda x: abs(x["zscore"]), reverse=True)
        return anomalies

    def check_pattern_anomalies(self, date_str: str) -> list[dict]:
        """Detect multi-variable anomalies using config-driven pattern evaluation.

        Patterns are defined in config.yaml under analysis.patterns.
        Returns empty list if no patterns are configured.
        """
        return self.check_config_patterns(date_str)

    def _get_late_caffeine(self, date_str: str) -> float | None:
        """Get total caffeine intake after 14:00 local time on a given date."""
        row = self.db.conn.execute(
            """
            SELECT SUM(value_numeric) FROM events
            WHERE source_module = 'body.caffeine'
              AND event_type = 'intake'
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) = ?
              AND CAST(strftime('%H', timestamp_local) AS INTEGER) >= 14
            """,
            [date_str],
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def _count_events(self, source_module: str, date_str: str) -> int | None:
        """Count events for a metric on a specific date."""
        row = self.db.conn.execute(
            """
            SELECT COUNT(*)
            FROM events
            WHERE source_module = ?
              AND date(timestamp_local) = ?
            """,
            [source_module, date_str],
        ).fetchone()
        return row[0] if row else None

    def check_config_patterns(self, date_str: str) -> list[dict]:
        """Evaluate compound patterns from config.yaml instead of hardcoded logic.

        Each pattern has a list of conditions. All conditions must be met for the
        pattern to fire. Returns list of triggered pattern dicts.
        """
        import operator as op

        _OPS = {"<": op.lt, ">": op.gt, "<=": op.le, ">=": op.ge, "==": op.eq, "!=": op.ne}

        config_patterns = self._analysis.get("patterns", [])
        if not config_patterns:
            return []

        triggered = []
        for pattern in config_patterns:
            if not pattern.get("enabled", True):
                continue

            conditions = pattern.get("conditions", [])
            if not conditions:
                continue

            all_met = True
            metric_values: dict[str, float] = {}

            for cond in conditions:
                metric = cond.get("metric", "")
                agg = cond.get("aggregate", "AVG")
                event_type = cond.get("event_type")
                hour_filter = cond.get("hour_filter")
                threshold = cond.get("threshold", 0)
                op_str = cond.get("operator", "<")

                # Special case: hour-filtered caffeine query
                if hour_filter:
                    value = self._get_late_caffeine(date_str)
                elif agg.upper() == "COUNT":
                    value = self._count_events(metric, date_str)
                else:
                    value = self._get_daily_metric(
                        metric, date_str, event_type=event_type, aggregate=agg,
                    )

                if value is None:
                    all_met = False
                    break

                op_fn = _OPS.get(op_str, op.lt)
                if not op_fn(value, threshold):
                    all_met = False
                    break

                # Store value for description template
                metric_key = metric.replace(".", "_")
                if event_type:
                    metric_key = event_type
                metric_values[metric_key] = value

            if all_met:
                desc = pattern.get("description_template", pattern["name"])
                with contextlib.suppress(KeyError, ValueError):
                    desc = desc.format(**metric_values)

                triggered.append({
                    "pattern": pattern["name"],
                    "description": desc,
                    "metrics": metric_values,
                })

        return triggered

    @staticmethod
    def _describe(metric: str, zscore: float, value: float, mean: float) -> str:
        """Generate a human-readable anomaly description."""
        direction = "above" if zscore > 0 else "below"
        return (
            f"{metric}: {value:.1f} is {abs(zscore):.1f}σ {direction} "
            f"your 14-day average of {mean:.1f}"
        )
