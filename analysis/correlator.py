"""
LifeData V4 — Correlator
analysis/correlator.py

Computes pairwise correlations between metric streams from the events table.
Uses daily aggregation as the default resolution.

Events with confidence below min_confidence are excluded (e.g., the invalid
environment.sound events at confidence=0.1 are filtered out).
"""

from datetime import UTC, datetime, timedelta

from core.logger import get_logger

log = get_logger("lifedata.analysis.correlator")


class Correlator:
    """Computes pairwise correlations between metric time series."""

    def __init__(self, db):
        self.db = db

    def _get_daily_series(
        self,
        source_module: str,
        window_days: int = 30,
        min_confidence: float = 0.5,
    ) -> dict[str, float]:
        """Get daily-aggregated values for a source_module.

        Returns dict mapping date string -> average value_numeric for that day.
        Only events with confidence >= min_confidence are included.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()

        rows = self.db.conn.execute(
            """
            SELECT date(timestamp_local) as day, AVG(value_numeric) as avg_val
            FROM events
            WHERE source_module = ?
              AND value_numeric IS NOT NULL
              AND confidence >= ?
              AND timestamp_utc >= ?
            GROUP BY day
            ORDER BY day
            """,
            [source_module, min_confidence, cutoff],
        ).fetchall()

        return {row[0]: row[1] for row in rows if row[1] is not None}

    def _align_series(
        self,
        series_a: dict[str, float],
        series_b: dict[str, float],
        lag_days: int = 0,
    ) -> list[tuple[str, float, float]]:
        """Align two daily series by date, optionally applying a lag.

        If lag_days > 0, series_b is shifted forward (testing if A predicts B
        with a delay).
        """
        aligned = []
        for date_str, val_a in series_a.items():
            if lag_days != 0:
                # Shift the date for series_b lookup
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    shifted = (dt + timedelta(days=lag_days)).strftime("%Y-%m-%d")
                except ValueError:
                    continue
            else:
                shifted = date_str

            if shifted in series_b:
                aligned.append((date_str, val_a, series_b[shifted]))

        return aligned

    def _compute_from_aligned(
        self,
        metric_a: str,
        metric_b: str,
        aligned: list[tuple[str, float, float]],
        window_days: int = 30,
        lag_days: int = 0,
    ) -> dict:
        """Compute correlation statistics from pre-aligned data points.

        Shared implementation used by both correlate() and _correlate_from_series().

        Returns insufficient_data result if fewer than 7 aligned points,
        otherwise computes Pearson/Spearman and returns full result dict.
        """
        if len(aligned) < 7:
            return {
                "metric_a": metric_a,
                "metric_b": metric_b,
                "error": "insufficient_data",
                "n": len(aligned),
                "confidence_tier": "none",
                "message": (
                    f"Need 7+ co-occurring observations, have {len(aligned)}. "
                    f"Collect more data before interpreting this relationship."
                ),
            }

        a_vals = [p[1] for p in aligned]
        b_vals = [p[2] for p in aligned]

        # Import scipy here (lazy) to avoid import-time overhead
        from scipy import stats

        pearson_r, pearson_p = stats.pearsonr(a_vals, b_vals)
        spearman_rho, spearman_p = stats.spearmanr(a_vals, b_vals)

        return {
            "metric_a": metric_a,
            "metric_b": metric_b,
            "window_days": window_days,
            "lag_days": lag_days,
            "pearson_r": round(float(pearson_r), 4),
            "spearman_rho": round(float(spearman_rho), 4),
            "p_value": round(float(min(pearson_p, spearman_p)), 6),
            "n": len(aligned),
            "significant": float(min(pearson_p, spearman_p)) < 0.05,
            "effect_size": self._interpret_r(float(pearson_r)),
            "confidence_tier": self.confidence_tier(len(aligned)),
        }

    def correlate(
        self,
        metric_a: str,
        metric_b: str,
        window_days: int = 30,
        lag_days: int = 0,
        min_confidence: float = 0.5,
    ) -> dict:
        """Compute correlation between two metrics.

        Args:
            metric_a: source_module identifier (e.g., 'mind.mood')
            metric_b: source_module identifier (e.g., 'body.sleep_duration')
            window_days: Number of days to look back.
            lag_days: Shift metric_b by N days (test delayed effects).
            min_confidence: Minimum confidence threshold for events.

        Returns:
            Dict with pearson_r, spearman_rho, p_value, n, confidence_tier, etc.
        """
        series_a = self._get_daily_series(metric_a, window_days, min_confidence)
        series_b = self._get_daily_series(metric_b, window_days, min_confidence)
        aligned = self._align_series(series_a, series_b, lag_days)
        return self._compute_from_aligned(
            metric_a, metric_b, aligned, window_days, lag_days
        )

    def _correlate_from_series(
        self,
        metric_a: str,
        metric_b: str,
        series_a: dict[str, float],
        series_b: dict[str, float],
        window_days: int = 30,
        lag_days: int = 0,
    ) -> dict:
        """Compute correlation from pre-fetched series (avoids redundant DB calls)."""
        aligned = self._align_series(series_a, series_b, lag_days)
        return self._compute_from_aligned(
            metric_a, metric_b, aligned, window_days, lag_days
        )

    def run_correlation_matrix(self, metrics: list[str], window_days: int = 30) -> dict:
        """Run all pairwise correlations between a list of metrics.

        Pre-fetches each metric's daily series once, then computes all pairs
        from the cached data. For N metrics this reduces DB calls from
        2*C(N,2) to N.

        Returns matrix + ranked list of strongest correlations.
        """
        # Pre-fetch all series (N queries instead of 2*C(N,2))
        series_cache: dict[str, dict[str, float]] = {}
        for metric in metrics:
            series_cache[metric] = self._get_daily_series(metric, window_days)

        results = []
        for i, a in enumerate(metrics):
            for b in metrics[i + 1 :]:
                result = self._correlate_from_series(
                    a, b, series_cache[a], series_cache[b], window_days
                )
                if "error" not in result:
                    results.append(result)

        results.sort(key=lambda x: abs(x["pearson_r"]), reverse=True)
        return {
            "matrix": results,
            "strongest": results[:10],
            "significant_only": [r for r in results if r["significant"]],
        }

    def lagged_analysis(
        self, metric_a: str, metric_b: str, max_lag_days: int = 3
    ) -> list[dict]:
        """Test correlations at multiple lags.

        Answers: "Does X predict Y with a delay?"
        """
        results = []
        for lag in range(-max_lag_days, max_lag_days + 1):
            result = self.correlate(metric_a, metric_b, lag_days=lag)
            result["lag_days"] = lag
            results.append(result)
        return results

    def persist_matrix(self, matrix_result: dict) -> int:
        """Persist correlation matrix results to the correlations table.

        Args:
            matrix_result: Output from run_correlation_matrix().

        Returns:
            Number of correlations persisted.
        """
        count = 0
        for result in matrix_result.get("matrix", []):
            if "error" in result:
                continue
            try:
                self.db.upsert_correlation(
                    metric_a=result["metric_a"],
                    metric_b=result["metric_b"],
                    window_days=result.get("window_days", 30),
                    pearson_r=result.get("pearson_r"),
                    spearman_rho=result.get("spearman_rho"),
                    p_value=result.get("p_value"),
                    n_observations=result.get("n", 0),
                )
                count += 1
            except Exception as e:
                log.warning(
                    f"Failed to persist correlation "
                    f"{result['metric_a']} ~ {result['metric_b']}: {e}"
                )
        if count:
            log.info(f"Persisted {count} correlations to database")
        return count

    @staticmethod
    def confidence_tier(n: int) -> str:
        """Classify a correlation result by sample size.

        < 14: exploratory (do not act on these)
        14-29: preliminary (directionally useful)
        >= 30: reliable (suitable for hypothesis formation)
        """
        if n < 14:
            return "exploratory"
        elif n < 30:
            return "preliminary"
        else:
            return "reliable"

    @staticmethod
    def _interpret_r(r: float) -> str:
        """Interpret the magnitude of a correlation coefficient."""
        ar = abs(r)
        if ar < 0.1:
            return "negligible"
        if ar < 0.3:
            return "weak"
        if ar < 0.5:
            return "moderate"
        if ar < 0.7:
            return "strong"
        return "very_strong"
