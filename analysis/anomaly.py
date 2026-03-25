"""
LifeData V4 — Anomaly Detector
analysis/anomaly.py

Flags unusual events using z-score analysis against rolling baselines.
Also detects multi-variable pattern anomalies (burnout signals, caffeine-sleep).
"""

import statistics
from datetime import UTC, datetime, timedelta

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
        allowed_aggs = {"AVG", "SUM", "MIN", "MAX", "COUNT"}
        if aggregate.upper() not in allowed_aggs:
            aggregate = "AVG"

        query = f"""
            SELECT {aggregate.upper()}(value_numeric)
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

        # Pattern: Sleep deprivation + high stress
        sleep_dur = self._get_daily_metric(
            "body.derived", date_str, event_type="sleep_duration"
        )
        stress = self._get_daily_metric("mind.stress", date_str)
        if sleep_dur is not None and stress is not None:
            if sleep_dur < 6.0 and stress > 6:
                patterns.append(
                    {
                        "pattern": "sleep_deprivation_high_stress",
                        "description": (
                            f"Short sleep ({sleep_dur:.1f}h) combined with "
                            f"high stress ({stress:.0f}/10) — burnout risk"
                        ),
                        "metrics": {
                            "sleep_hours": sleep_dur,
                            "stress_level": stress,
                        },
                    }
                )

        # Pattern: Late caffeine + fragmented sleep
        late_caffeine = self._get_late_caffeine(date_str)
        sleep_quality = self._get_daily_metric("mind.sleep", date_str)
        if late_caffeine is not None and sleep_quality is not None:
            if late_caffeine > 0 and sleep_quality < 5:
                patterns.append(
                    {
                        "pattern": "caffeine_late_poor_sleep",
                        "description": (
                            f"Caffeine intake after 14:00 ({late_caffeine:.0f}mg) "
                            f"with poor sleep quality ({sleep_quality:.0f}/10)"
                        ),
                        "metrics": {
                            "late_caffeine_mg": late_caffeine,
                            "sleep_quality": sleep_quality,
                        },
                    }
                )

        # Pattern: Low mood + social isolation
        mood = self._get_daily_metric("mind.mood", date_str)
        density = self._get_daily_metric(
            "social.derived", date_str, event_type="density_score"
        )
        if mood is not None and density is not None:
            if mood < 4 and density < 10:
                patterns.append(
                    {
                        "pattern": "low_mood_social_isolation",
                        "description": (
                            f"Low mood ({mood:.0f}/10) with minimal social "
                            f"interaction (density={density:.1f})"
                        ),
                        "metrics": {
                            "mood": mood,
                            "social_density": density,
                        },
                    }
                )

        # Pattern: High screen time + low steps
        screen_time = self._get_daily_metric(
            "device.derived", date_str, event_type="screen_time_minutes"
        )
        steps = self._get_daily_metric("body.steps", date_str, aggregate="SUM")
        if screen_time is not None and steps is not None:
            if screen_time > 180 and steps < 3000:
                patterns.append(
                    {
                        "pattern": "high_screen_low_movement",
                        "description": (
                            f"High screen time ({screen_time:.0f} min) with "
                            f"low step count ({steps:.0f}) — sedentary day"
                        ),
                        "metrics": {
                            "screen_time_min": screen_time,
                            "steps": steps,
                        },
                    }
                )

        # Pattern: High cognitive load after sleep deprivation (cognition × body)
        cli = self._get_daily_metric(
            "cognition.derived", date_str, event_type="cognitive_load_index"
        )
        sleep_cog = self._get_daily_metric(
            "body.derived", date_str, event_type="sleep_duration"
        )
        if cli is not None and sleep_cog is not None:
            if cli > 2.0 and sleep_cog < 6.0:
                patterns.append(
                    {
                        "pattern": "cognitive_impairment_sleep_deprivation",
                        "description": (
                            f"High cognitive impairment (CLI={cli:.1f}) "
                            f"after short sleep ({sleep_cog:.1f}h)"
                        ),
                        "metrics": {
                            "cognitive_load_index": cli,
                            "sleep_hours": sleep_cog,
                        },
                    }
                )

        # Pattern: Digital restlessness with low mood (behavior × mind)
        restlessness = self._get_daily_metric(
            "behavior.derived", date_str, event_type="digital_restlessness"
        )
        mood_rest = self._get_daily_metric("mind.mood", date_str)
        if restlessness is not None and mood_rest is not None:
            if restlessness > 2.0 and mood_rest < 4:
                patterns.append(
                    {
                        "pattern": "digital_restlessness_low_mood",
                        "description": (
                            f"Digital restlessness (z={restlessness:.1f}) "
                            f"with low mood ({mood_rest:.0f}/10)"
                        ),
                        "metrics": {
                            "digital_restlessness": restlessness,
                            "mood": mood_rest,
                        },
                    }
                )

        # Pattern: Schumann resonance deviation with mood swing (oracle × mind)
        schumann_mean = self._get_schumann_mean(date_str)
        mood_range = self._get_mood_range(date_str)
        if schumann_mean is not None and mood_range is not None:
            if abs(schumann_mean - 7.83) > 0.3 and mood_range > 4:
                patterns.append(
                    {
                        "pattern": "schumann_excursion_mood_swing",
                        "description": (
                            f"Schumann resonance deviation ({schumann_mean:.2f} Hz) "
                            f"with wide mood swing (range={mood_range:.0f})"
                        ),
                        "metrics": {
                            "schumann_mean_hz": schumann_mean,
                            "mood_range": mood_range,
                        },
                    }
                )

        # Pattern: High app fragmentation with heavy caffeine (behavior × body)
        frag = self._get_daily_metric(
            "behavior.app_switch.derived", date_str, event_type="fragmentation_index"
        )
        caffeine_total = self._get_daily_metric(
            "body.caffeine", date_str, aggregate="SUM"
        )
        if frag is not None and caffeine_total is not None:
            if frag > 50 and caffeine_total > 300:
                patterns.append(
                    {
                        "pattern": "fragmentation_caffeine_spike",
                        "description": (
                            f"High app fragmentation ({frag:.0f}) "
                            f"with heavy caffeine ({caffeine_total:.0f}mg)"
                        ),
                        "metrics": {
                            "fragmentation_index": frag,
                            "caffeine_mg": caffeine_total,
                        },
                    }
                )

        return patterns

    def _get_schumann_mean(self, date_str: str) -> float | None:
        """Get mean Schumann resonance frequency for a given date."""
        row = self.db.conn.execute(
            """
            SELECT AVG(value_numeric) FROM events
            WHERE source_module = 'oracle.schumann'
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) = ?
            """,
            [date_str],
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def _get_mood_range(self, date_str: str) -> float | None:
        """Get mood range (max - min) for a given date."""
        row = self.db.conn.execute(
            """
            SELECT MIN(value_numeric), MAX(value_numeric) FROM events
            WHERE source_module = 'mind.mood'
              AND value_numeric IS NOT NULL
              AND date(timestamp_local) = ?
            """,
            [date_str],
        ).fetchone()
        if row and row[0] is not None and row[1] is not None:
            return row[1] - row[0]
        return None

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

    @staticmethod
    def _describe(metric: str, zscore: float, value: float, mean: float) -> str:
        """Generate a human-readable anomaly description."""
        direction = "above" if zscore > 0 else "below"
        return (
            f"{metric}: {value:.1f} is {abs(zscore):.1f}σ {direction} "
            f"your 14-day average of {mean:.1f}"
        )
