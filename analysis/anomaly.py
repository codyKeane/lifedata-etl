"""
LifeData V4 — Anomaly Detector
analysis/anomaly.py

Flags unusual events using z-score analysis against rolling baselines.
Also detects multi-variable pattern anomalies (burnout signals, caffeine-sleep).
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from core.logger import get_logger

log = get_logger("lifedata.analysis.anomaly")


class AnomalyDetector:
    """Detects statistical anomalies in daily metric values."""

    def __init__(self, db, zscore_threshold: float = 2.0):
        self.db = db
        self.threshold = zscore_threshold

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
        self, source_module: str, date_str: str
    ) -> Optional[float]:
        """Get the average value_numeric for a metric on a specific date."""
        row = self.db.conn.execute(
            """
            SELECT AVG(value_numeric)
            FROM events
            WHERE source_module = ?
              AND date(timestamp_local) = ?
              AND value_numeric IS NOT NULL
            """,
            [source_module, date_str],
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def _get_metric_history(
        self,
        source_module: str,
        days: int = 14,
        exclude_date: Optional[str] = None,
    ) -> list[float]:
        """Get daily averages for a metric over the past N days.

        Excludes a specific date (usually today) from the baseline.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).strftime("%Y-%m-%d")

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

            baseline = self._get_metric_history(
                metric, days=14, exclude_date=date_str
            )
            if len(baseline) < 3:
                # Not enough history for meaningful anomaly detection
                continue

            # Compute z-score
            import statistics

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
        """Detect multi-variable anomalies that single-metric checks miss.

        These are compound patterns that are significant in combination
        but might not trigger individually.
        """
        patterns = []

        # Pattern: Low battery + high screen time (excessive phone use)
        battery = self._get_daily_metric("device.battery", date_str)
        screen_count = self._count_events("device.screen", date_str)

        if battery is not None and screen_count is not None:
            if battery < 20 and screen_count > 50:
                patterns.append(
                    {
                        "pattern": "heavy_phone_usage",
                        "description": (
                            f"Low battery ({battery:.0f}%) with high screen unlocks "
                            f"({screen_count}) — heavy phone usage day"
                        ),
                        "metrics": {
                            "battery_avg": battery,
                            "screen_events": screen_count,
                        },
                    }
                )

        return patterns

    def _count_events(
        self, source_module: str, date_str: str
    ) -> Optional[int]:
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

    @staticmethod
    def _describe(
        metric: str, zscore: float, value: float, mean: float
    ) -> str:
        """Generate a human-readable anomaly description."""
        direction = "above" if zscore > 0 else "below"
        return (
            f"{metric}: {value:.1f} is {abs(zscore):.1f}σ {direction} "
            f"your 14-day average of {mean:.1f}"
        )
