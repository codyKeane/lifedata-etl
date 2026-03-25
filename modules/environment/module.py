"""
LifeData V4 — Environment Module
modules/environment/module.py

Handles environmental data: hourly snapshots, geofence location, astronomy.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json
from modules.environment.parsers import PARSER_REGISTRY

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.environment")


class EnvironmentModule(ModuleInterface):
    """Environment module — parses environmental sensor and location data."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "environment"

    @property
    def display_name(self) -> str:
        return "Environment Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "environment.hourly",
            "environment.location",
            "environment.astro",
            "environment.pressure",
            "environment.light",
            "environment.emf",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find environment, location, and astro CSVs in the raw data tree."""
        files = []
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "environment"),
            os.path.join(raw_base, "logs", "environment"),
            os.path.join(raw_base, "location"),
            os.path.join(raw_base, "logs", "location"),
            os.path.join(raw_base, "astro"),
            os.path.join(raw_base, "logs", "astro"),
            os.path.join(raw_base, "logs", "sensors"),  # Sensor Logger summaries
        ]

        for search_dir in search_dirs:
            expanded = os.path.expanduser(search_dir)
            if not os.path.isdir(expanded):
                continue
            for csv_file in glob_files(expanded, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                if any(basename.startswith(prefix) for prefix in PARSER_REGISTRY):
                    files.append(csv_file)

        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single environment CSV file."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for environment file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Compute derived environment metrics after ingestion.

        Only recomputes for dates that had events ingested this run.

        Derived metrics per day:
          - environment.derived/daily_weather_composite: temp range, avg humidity, avg temp, avg pressure
          - environment.derived/location_diversity: unique locations at ~111m resolution
          - environment.derived/astro_summary: moon phase and illumination
        """
        if affected_dates is not None:
            days = sorted(affected_dates)
        else:
            date_rows = db.execute(
                """
                SELECT DISTINCT date(timestamp_local) as d FROM events
                WHERE source_module LIKE 'environment.%'
                  AND source_module != 'environment.derived'
                ORDER BY d
                """
            ).fetchall()
            days = [row[0] for row in date_rows]

        all_derived: list[Event] = []

        for day in days:
            day_derived = self._compute_day_metrics(db, day)
            all_derived.extend(day_derived)

        if all_derived:
            inserted, skipped = db.insert_events_for_module("environment", all_derived)
            log.info(f"Environment derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db: Database, day: str) -> list[Event]:
        """Compute all derived metrics for a single day."""
        derived: list[Event] = []
        day_ts = f"{day}T12:00:00-05:00"

        # --- Daily weather composite ---
        hourly_rows = db.execute(
            """
            SELECT value_json FROM events
            WHERE source_module = 'environment.hourly'
              AND date(timestamp_local) = ?
              AND value_json IS NOT NULL
            """,
            [day],
        ).fetchall()

        if hourly_rows:
            temps = []
            humidities = []
            for (vj,) in hourly_rows:
                try:
                    data = json.loads(vj)
                    if "temp_f" in data:
                        temps.append(float(data["temp_f"]))
                    if "humidity_pct" in data:
                        humidities.append(float(data["humidity_pct"]))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue

            # Query pressure data for the day
            pressure_rows = db.execute(
                """
                SELECT value_numeric FROM events
                WHERE source_module = 'environment.pressure'
                  AND date(timestamp_local) = ?
                  AND value_numeric IS NOT NULL
                """,
                [day],
            ).fetchall()
            pressures = [r[0] for r in pressure_rows]

            if temps:
                temp_range = round(max(temps) - min(temps), 2)
                avg_temp = round(sum(temps) / len(temps), 2)
                avg_humidity = (
                    round(sum(humidities) / len(humidities), 2) if humidities else None
                )
                avg_pressure = (
                    round(sum(pressures) / len(pressures), 2) if pressures else None
                )

                composite = {
                    "temp_range_f": temp_range,
                    "temp_avg_f": avg_temp,
                }
                if avg_humidity is not None:
                    composite["humidity_avg_pct"] = avg_humidity
                if avg_pressure is not None:
                    composite["pressure_avg_hpa"] = avg_pressure

                derived.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="environment.derived",
                        event_type="daily_weather_composite",
                        value_numeric=avg_temp,
                        value_json=safe_json(composite),
                        confidence=0.9,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"[{day}] Weather composite: avg_temp={avg_temp}F, "
                    f"range={temp_range}F, humidity={avg_humidity}%"
                )

        # --- Location diversity ---
        location_rows = db.execute(
            """
            SELECT location_lat, location_lon FROM events
            WHERE source_module = 'environment.location'
              AND date(timestamp_local) = ?
              AND location_lat IS NOT NULL
              AND location_lon IS NOT NULL
            """,
            [day],
        ).fetchall()

        if location_rows:
            unique_locs = set()
            for lat, lon in location_rows:
                try:
                    rounded = (round(float(lat), 3), round(float(lon), 3))
                    unique_locs.add(rounded)
                except (ValueError, TypeError):
                    continue

            total_fixes = len(location_rows)
            unique_count = len(unique_locs)

            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="environment.derived",
                    event_type="location_diversity",
                    value_numeric=float(unique_count),
                    value_json=safe_json(
                        {
                            "total_fixes": total_fixes,
                            "unique_locations": unique_count,
                            "resolution_m": 111,
                        }
                    ),
                    confidence=0.85,
                    parser_version=self.version,
                )
            )
            log.info(
                f"[{day}] Location diversity: {unique_count} unique "
                f"locations from {total_fixes} fixes"
            )

        # --- Astro summary ---
        astro_rows = db.execute(
            """
            SELECT value_text, value_numeric FROM events
            WHERE source_module = 'environment.astro'
              AND date(timestamp_local) = ?
            """,
            [day],
        ).fetchall()

        if astro_rows:
            moon_phase = None
            moon_illumination = None
            for vtext, vnum in astro_rows:
                if vtext:
                    moon_phase = vtext
                if vnum is not None:
                    moon_illumination = vnum

            if moon_phase is not None or moon_illumination is not None:
                derived.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="environment.derived",
                        event_type="astro_summary",
                        value_numeric=moon_illumination,
                        value_text=moon_phase,
                        value_json=safe_json(
                            {
                                "moon_phase": moon_phase,
                                "moon_illumination_pct": moon_illumination,
                            }
                        ),
                        confidence=1.0,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"[{day}] Astro summary: phase={moon_phase}, "
                    f"illumination={moon_illumination}%"
                )

        return derived


def create_module(config: dict[str, Any] | None = None) -> EnvironmentModule:
    """Factory function called by the orchestrator."""
    return EnvironmentModule(config)
