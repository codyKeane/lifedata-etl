"""
LifeData V4 — Oracle Module (XI)
modules/oracle/module.py

Captures data from frontier/esoteric sources: I Ching divination,
hardware RNG distributions, Schumann resonance, and planetary hours.

File discovery patterns:
  spool/oracle/iching_*.csv       → oracle.iching / casting
  spool/oracle/iching_auto_*.csv  → oracle.iching / casting (automated)
  spool/oracle/rng_*.csv          → oracle.rng / hardware_sample
  spool/oracle/rng_raw_*.csv      → oracle.rng / raw_batch
  raw/api/schumann/*.json         → oracle.schumann / measurement
  raw/api/planetary/*.json        → oracle.planetary_hours / current_hour

Derived metrics (computed in post_ingest):
  oracle.iching.derived / hexagram_frequency
  oracle.iching.derived / entropy_test
  oracle.rng.derived / daily_deviation
  oracle.schumann.derived / daily_summary
  oracle.planetary_hours.derived / activity_by_planet
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.oracle")


class OracleModule(ModuleInterface):
    """Oracle module — frontier data: divination, RNG, Schumann, planetary hours."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._parser_registry: dict[str, Any] | None = None

    def _get_parsers(self) -> dict[str, Any]:
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.oracle.parsers import PARSER_REGISTRY

            self._parser_registry = PARSER_REGISTRY
        return self._parser_registry

    @property
    def module_id(self) -> str:
        return "oracle"

    @property
    def display_name(self) -> str:
        return "Oracle Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "oracle.iching",
            "oracle.iching.derived",
            "oracle.rng",
            "oracle.rng.derived",
            "oracle.schumann",
            "oracle.schumann.derived",
            "oracle.planetary_hours",
            "oracle.planetary_hours.derived",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all oracle data files in spool/oracle and raw/api directories."""
        files = []
        expanded = os.path.expanduser(raw_base)

        search_dirs = [
            (os.path.join(expanded, "spool", "oracle"), "*.csv"),
            (os.path.join(expanded, "..", "raw", "api", "schumann"), "*.json"),
            (os.path.join(expanded, "..", "raw", "api", "planetary"), "*.json"),
        ]

        # Also check raw_base-relative paths for api data
        raw_root = os.path.dirname(expanded)  # one level up from LifeData
        api_dirs = [
            (os.path.join(raw_root, "api", "schumann"), "*.json"),
            (os.path.join(raw_root, "api", "planetary"), "*.json"),
        ]

        for search_dir, pattern in search_dirs + api_dirs:
            if not os.path.isdir(search_dir):
                continue
            for data_file in glob_files(search_dir, pattern, recursive=True):
                basename = os.path.basename(data_file)
                if any(basename.startswith(prefix) for prefix in self._get_parsers()):
                    files.append(data_file)

        # Deduplicate
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single oracle data file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in self._get_parsers().items():
            if basename.startswith(prefix):
                events: list[Event] = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for oracle file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Compute derived oracle metrics after all events are ingested.

        Only recomputes for dates that had events ingested this run.
        Derived metrics:
          - oracle.iching.derived/hexagram_frequency: distribution over window
          - oracle.iching.derived/entropy_test: chi-squared uniformity test
          - oracle.rng.derived/daily_deviation: z-score of daily mean vs expected
          - oracle.schumann.derived/daily_summary: mean/min/max/excursion count
          - oracle.planetary_hours.derived/activity_by_planet: mood/energy by planet
        """
        derived_events = []

        if affected_dates is not None:
            dates = sorted(affected_dates)
        else:
            # Fallback: recompute all dates
            rows = db.execute(
                """
                SELECT DISTINCT date(timestamp_utc) as d
                FROM events
                WHERE source_module LIKE 'oracle.%'
                  AND source_module NOT LIKE '%.derived'
                ORDER BY d
                """
            )
            result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
            dates = [r[0] for r in result_set if r[0]]

        for date_str in dates:
            # --- RNG daily deviation ---
            rng_event = self._compute_rng_daily_deviation(db, date_str)
            if rng_event:
                derived_events.append(rng_event)

            # --- Schumann daily summary ---
            schumann_event = self._compute_schumann_daily_summary(db, date_str)
            if schumann_event:
                derived_events.append(schumann_event)

            # --- Activity by planet ---
            planet_event = self._compute_activity_by_planet(db, date_str)
            if planet_event:
                derived_events.append(planet_event)

        # --- Hexagram frequency (rolling window, computed once) ---
        latest_date = dates[-1] if dates else None
        freq_event = self._compute_hexagram_frequency(db, latest_date)
        if freq_event:
            derived_events.append(freq_event)

        # --- Entropy test (rolling window, computed once) ---
        entropy_event = self._compute_entropy_test(db, latest_date)
        if entropy_event:
            derived_events.append(entropy_event)

        # Insert derived events
        if derived_events:
            inserted, skipped = db.insert_events_for_module("oracle", derived_events)
            log.info(f"Oracle derived metrics: {inserted} inserted, {skipped} skipped")

    def _compute_hexagram_frequency(
        self, db: Database, latest_date: str | None = None
    ) -> Event | None:
        """Distribution of hexagrams over the rolling analysis window."""
        window_days = self._config.get("analysis_window_days", 90)

        rows = db.execute(
            """
            SELECT value_numeric, COUNT(*) as cnt
            FROM events
            WHERE source_module = 'oracle.iching'
              AND event_type = 'casting'
              AND value_numeric IS NOT NULL
              AND date(timestamp_utc) >= date('now', ? || ' days')
            GROUP BY value_numeric
            ORDER BY cnt DESC
            """,
            (str(-window_days),),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        if not result_set:
            return None

        distribution = {int(r[0]): r[1] for r in result_set}
        total = sum(distribution.values())

        if total < 3:
            return None

        # Deterministic timestamp for idempotency
        ts_utc = (
            f"{latest_date}T23:59:01+00:00"
            if latest_date
            else datetime.now(UTC).isoformat()
        )
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="oracle.iching.derived",
            event_type="hexagram_frequency",
            value_numeric=float(total),
            value_json=safe_json(
                {
                    "distribution": distribution,
                    "total_castings": total,
                    "unique_hexagrams": len(distribution),
                    "most_common": max(distribution, key=lambda k: distribution[k]),
                    "window_days": window_days,
                }
            ),
            tags="iching,frequency,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_entropy_test(self, db: Database, latest_date: str | None = None) -> Event | None:
        """Chi-squared uniformity test on hexagram distribution."""
        window_days = self._config.get("analysis_window_days", 90)

        rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = 'oracle.iching'
              AND event_type = 'casting'
              AND value_numeric IS NOT NULL
              AND date(timestamp_utc) >= date('now', ? || ' days')
            """,
            (str(-window_days),),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        hexagrams = [int(r[0]) for r in result_set if r[0] is not None]

        if len(hexagrams) < 10:
            return None

        # Count observed frequencies across all 64 hexagrams
        observed = [0] * 64
        for h in hexagrams:
            if 1 <= h <= 64:
                observed[h - 1] += 1

        n = len(hexagrams)
        expected = n / 64.0

        # Chi-squared test
        chi2 = sum((obs - expected) ** 2 / expected for obs in observed)
        df = 63

        # Approximate p-value using Wilson-Hilferty normal approximation
        z = ((chi2 / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
        # Approximate upper-tail p from z-score
        p_value = 0.5 * math.erfc(z / math.sqrt(2))

        # Deterministic timestamp for idempotency
        ts_utc = (
            f"{latest_date}T23:59:02+00:00"
            if latest_date
            else datetime.now(UTC).isoformat()
        )
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="oracle.iching.derived",
            event_type="entropy_test",
            value_numeric=round(p_value, 6),
            value_json=safe_json(
                {
                    "chi_squared": round(chi2, 4),
                    "df": df,
                    "n_castings": n,
                    "p_value": round(p_value, 6),
                    "uniform": p_value > 0.05,
                    "window_days": window_days,
                }
            ),
            tags="iching,entropy,chi_squared,derived",
            confidence=0.9,
            parser_version=self.version,
        )

    def _compute_rng_daily_deviation(self, db: Database, date_str: str) -> Event | None:
        """Z-score of daily RNG mean vs expected 127.5."""
        rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = 'oracle.rng'
              AND event_type = 'hardware_sample'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        means = [r[0] for r in result_set if r[0] is not None]

        if len(means) < 3:
            return None

        daily_mean = sum(means) / len(means)
        expected = 127.5
        std_of_means = (
            math.sqrt(sum((x - daily_mean) ** 2 for x in means) / len(means))
            if len(means) > 1
            else 7.39
        )

        if std_of_means < 0.01:
            std_of_means = 7.39  # fallback to theoretical

        z = (daily_mean - expected) / (std_of_means / math.sqrt(len(means)))

        # Approximate p-value
        p_value = 2 * 0.5 * math.erfc(abs(z) / math.sqrt(2))

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="oracle.rng.derived",
            event_type="daily_deviation",
            value_numeric=round(z, 4),
            value_json=safe_json(
                {
                    "daily_mean": round(daily_mean, 4),
                    "z_score": round(z, 4),
                    "p_value": round(p_value, 6),
                    "n_samples": len(means),
                    "std": round(std_of_means, 4),
                }
            ),
            tags="rng,deviation,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_schumann_daily_summary(self, db: Database, date_str: str) -> Event | None:
        """Mean/min/max/excursion count for Schumann resonance."""
        rows = db.execute(
            """
            SELECT value_numeric
            FROM events
            WHERE source_module = 'oracle.schumann'
              AND event_type = 'measurement'
              AND date(timestamp_utc) = ?
              AND value_numeric IS NOT NULL
            """,
            (date_str,),
        )
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        values = [r[0] for r in result_set if r[0] is not None]

        if len(values) < 2:
            return None

        mean_hz = sum(values) / len(values)
        min_hz = min(values)
        max_hz = max(values)
        std_hz = math.sqrt(sum((x - mean_hz) ** 2 for x in values) / len(values))

        # Count excursions: readings > 0.5 Hz from baseline 7.83
        baseline = 7.83
        excursion_count = sum(1 for v in values if abs(v - baseline) > 0.5)

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="oracle.schumann.derived",
            event_type="daily_summary",
            value_numeric=round(mean_hz, 4),
            value_json=safe_json(
                {
                    "mean_hz": round(mean_hz, 4),
                    "min_hz": round(min_hz, 4),
                    "max_hz": round(max_hz, 4),
                    "std_hz": round(std_hz, 4),
                    "excursion_count": excursion_count,
                    "n_measurements": len(values),
                }
            ),
            tags="schumann,daily_summary,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def _compute_activity_by_planet(self, db: Database, date_str: str) -> Event | None:
        """Cross-query mood/energy by ruling planet for the day."""
        # Get planetary hours for this date
        hours_rows = db.execute(
            """
            SELECT value_text, value_json
            FROM events
            WHERE source_module = 'oracle.planetary_hours'
              AND event_type = 'current_hour'
              AND date(timestamp_utc) = ?
            """,
            (date_str,),
        )
        hours_set = (
            hours_rows.fetchall() if hasattr(hours_rows, "fetchall") else hours_rows
        )

        if not hours_set:
            return None

        # Collect planet → time ranges
        planet_ranges: dict[str, list[tuple[str, str]]] = {}
        for row in hours_set:
            planet = row[0]
            try:
                data = json.loads(row[1]) if row[1] else {}
            except (json.JSONDecodeError, TypeError):
                continue
            start = data.get("start_time", "")
            end = data.get("end_time", "")
            if planet and start and end:
                if planet not in planet_ranges:
                    planet_ranges[planet] = []
                planet_ranges[planet].append((start, end))

        if not planet_ranges:
            return None

        # Fetch ALL non-oracle events for the day in ONE query (replaces 72+ queries)
        all_events_rows = db.execute(
            """
            SELECT timestamp_local, source_module, event_type, value_numeric
            FROM events
            WHERE date(timestamp_local) = ?
              AND source_module NOT LIKE 'oracle.%'
            ORDER BY timestamp_local
            """,
            (date_str,),
        ).fetchall()

        # Build Python-side lists for fast filtering
        all_events = [
            (row[0], row[1], row[2], row[3]) for row in all_events_rows
        ]

        # For each planet, filter events by time ranges in Python
        activity = {}
        for planet, ranges in planet_ranges.items():
            mood_vals: list[float] = []
            energy_vals: list[float] = []
            event_count = 0
            for start, end in ranges:
                for ts_local, src_mod, evt_type, val_num in all_events:
                    if ts_local < start or ts_local >= end:
                        continue
                    event_count += 1
                    if val_num is not None:
                        if src_mod in ("mind.mood", "mind.assessment"):
                            mood_vals.append(val_num)
                        if src_mod in ("mind.energy", "mind.assessment") and "energy" in (evt_type or ""):
                            energy_vals.append(val_num)

            activity[planet] = {
                "events_count": event_count,
                "mood_avg": round(sum(mood_vals) / len(mood_vals), 2)
                if mood_vals
                else None,
                "energy_avg": round(sum(energy_vals) / len(energy_vals), 2)
                if energy_vals
                else None,
                "hours_count": len(ranges),
            }

        ts_utc = f"{date_str}T23:59:00+00:00"
        return Event(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc,
            timezone_offset="-0500",
            source_module="oracle.planetary_hours.derived",
            event_type="activity_by_planet",
            value_numeric=float(len(activity)),
            value_json=safe_json(activity),
            tags="planetary_hours,activity,derived",
            confidence=0.8,
            parser_version=self.version,
        )

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily oracle metrics for report generation."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt,
                   AVG(value_numeric) as avg_val,
                   MIN(value_numeric) as min_val,
                   MAX(value_numeric) as max_val
            FROM events
            WHERE source_module LIKE 'oracle.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        result_set = rows.fetchall() if hasattr(rows, "fetchall") else rows
        for row in result_set:
            src, evt, cnt, avg_val, min_val, max_val = row
            key = f"{src}.{evt}"
            summary[key] = {
                "count": cnt,
                "avg": round(avg_val, 2) if avg_val is not None else None,
                "min": round(min_val, 2) if min_val is not None else None,
                "max": round(max_val, 2) if max_val is not None else None,
            }

        if not summary:
            return None

        return {
            "event_counts": summary,
            "total_oracle_events": sum(v["count"] for v in summary.values()),
        }


def create_module(config: dict[str, Any] | None = None) -> OracleModule:
    """Factory function called by the orchestrator."""
    return OracleModule(config)
