"""
LifeData V4 — Device Module
modules/device/module.py

Handles device-level events from Tasker:
  battery, screen on/off, charging, bluetooth

Implements the ModuleInterface contract.
"""

import os
from datetime import datetime, timezone

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_float, safe_json
from modules.device.parsers import PARSER_REGISTRY, SAFE_PARSER_REGISTRY

log = get_logger("lifedata.device")


class DeviceModule(ModuleInterface):
    """Device module — parses phone hardware and OS events."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self._quarantined_files: list[str] = []

    @property
    def module_id(self) -> str:
        return "device"

    @property
    def display_name(self) -> str:
        return "Device Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "device.battery",
            "device.screen",
            "device.charging",
            "device.bluetooth",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all device CSV files in the raw data tree.

        Searches recursively for files matching any known parser prefix
        within the device/ and logs/device/ subdirectories.
        """
        files = []

        # Search in all common locations:
        # - raw_base/device/
        # - raw_base/logs/device/
        # - raw_base directly (if files are at root)
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "device"),
            os.path.join(raw_base, "logs", "device"),
        ]

        for search_dir in search_dirs:
            expanded = os.path.expanduser(search_dir)
            if not os.path.isdir(expanded):
                continue
            for csv_file in glob_files(expanded, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                # Only include files matching a known parser prefix
                if any(basename.startswith(prefix) for prefix in PARSER_REGISTRY):
                    files.append(csv_file)

        # Deduplicate (same file found via different search paths)
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    @property
    def quarantined_files(self) -> list[str]:
        """Files quarantined during parsing (>50% rows skipped)."""
        return list(self._quarantined_files)

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single device CSV file using the appropriate safe parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in SAFE_PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                result = parser_fn(file_path)
                if result.quarantined:
                    self._quarantined_files.append(file_path)
                if result.events:
                    log.info(f"Parsed {len(result.events)} events from {basename}")
                return result.events

        log.warning(f"No parser found for device file: {basename}")
        return []

    def post_ingest(self, db) -> None:
        """Compute derived device metrics after ingestion.

        Processes all dates that have device events (not just today),
        ensuring derived metrics are computed for backfilled data.

        Derived metrics per day:
          - device.derived/unlock_count: number of screen_on events
          - device.derived/screen_time_minutes: estimated active screen time
          - device.derived/charging_duration: total minutes on charger
          - device.derived/battery_drain_rate: avg %/hour drain (non-charging)
        """
        now_utc = datetime.now(timezone.utc).isoformat()

        # Find all dates that have device events
        date_rows = db.execute(
            """
            SELECT DISTINCT date(timestamp_local) as d FROM events
            WHERE source_module LIKE 'device.%'
              AND source_module != 'device.derived'
            ORDER BY d
            """
        ).fetchall()

        all_derived: list[Event] = []

        for (day,) in date_rows:
            day_derived = self._compute_day_metrics(db, day, now_utc)
            all_derived.extend(day_derived)

        if all_derived:
            inserted, skipped = db.insert_events_for_module("device", all_derived)
            log.info(f"Device derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db, day: str, now_utc: str) -> list[Event]:
        """Compute all derived metrics for a single day."""
        derived: list[Event] = []
        # Use noon of the target day as the event timestamp for determinism
        day_ts = f"{day}T12:00:00-05:00"

        # --- Unlock count ---
        row = db.execute(
            """
            SELECT COUNT(*) FROM events
            WHERE source_module = 'device.screen'
              AND event_type = 'screen_on'
              AND date(timestamp_local) = ?
            """,
            [day],
        ).fetchone()
        unlock_count = row[0] if row else 0
        if unlock_count > 0:
            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="device.derived",
                    event_type="unlock_count",
                    value_numeric=float(unlock_count),
                    confidence=1.0,
                    parser_version=self.version,
                )
            )
            log.info(f"[{day}] Unlock count: {unlock_count}")

        # --- Screen time estimate ---
        # Estimate from gaps between consecutive screen_on events,
        # capped at 10 min per session (no screen_off data available).
        screen_rows = db.execute(
            """
            SELECT timestamp_utc FROM events
            WHERE source_module = 'device.screen'
              AND event_type = 'screen_on'
              AND date(timestamp_local) = ?
            ORDER BY timestamp_utc
            """,
            [day],
        ).fetchall()

        if len(screen_rows) >= 2:
            total_screen_min = 0.0
            max_session_min = 10.0
            for i in range(len(screen_rows) - 1):
                try:
                    t1 = datetime.fromisoformat(screen_rows[i][0])
                    t2 = datetime.fromisoformat(screen_rows[i + 1][0])
                    if t1.tzinfo is None:
                        t1 = t1.replace(tzinfo=timezone.utc)
                    if t2.tzinfo is None:
                        t2 = t2.replace(tzinfo=timezone.utc)
                    gap_min = (t2 - t1).total_seconds() / 60
                    total_screen_min += min(gap_min, max_session_min)
                except (ValueError, TypeError):
                    continue
            avg_session = total_screen_min / (len(screen_rows) - 1)
            total_screen_min += min(avg_session, max_session_min)
            total_screen_min = round(total_screen_min, 1)

            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="device.derived",
                    event_type="screen_time_minutes",
                    value_numeric=total_screen_min,
                    value_json=safe_json(
                        {
                            "sessions": len(screen_rows),
                            "max_session_cap_min": max_session_min,
                            "method": "inter_unlock_gap_capped",
                        }
                    ),
                    confidence=0.7,
                    parser_version=self.version,
                )
            )
            log.info(
                f"[{day}] Screen time: {total_screen_min} min ({len(screen_rows)} sessions)"
            )

        # --- Charging duration ---
        charge_rows = db.execute(
            """
            SELECT event_type, timestamp_utc, value_numeric
            FROM events
            WHERE source_module = 'device.charging'
              AND event_type IN ('charge_start', 'charge_stop')
              AND date(timestamp_local) = ?
            ORDER BY timestamp_utc
            """,
            [day],
        ).fetchall()

        if charge_rows:
            total_charge_min = 0.0
            total_pct_gained = 0.0
            charge_sessions = 0
            last_start_ts: str | None = None
            last_start_pct: float | None = None

            for etype, ts, pct in charge_rows:
                if etype == "charge_start":
                    last_start_ts = ts
                    last_start_pct = safe_float(pct)
                elif etype == "charge_stop" and last_start_ts:
                    try:
                        dt_start = datetime.fromisoformat(last_start_ts)
                        dt_stop = datetime.fromisoformat(ts)
                        if dt_start.tzinfo is None:
                            dt_start = dt_start.replace(tzinfo=timezone.utc)
                        if dt_stop.tzinfo is None:
                            dt_stop = dt_stop.replace(tzinfo=timezone.utc)
                        dur_min = (dt_stop - dt_start).total_seconds() / 60
                        if 0 < dur_min < 1440:
                            total_charge_min += dur_min
                            charge_sessions += 1
                            stop_pct = safe_float(pct)
                            if last_start_pct is not None and stop_pct is not None:
                                total_pct_gained += stop_pct - last_start_pct
                    except (ValueError, TypeError):
                        pass
                    last_start_ts = None
                    last_start_pct = None

            if total_charge_min > 0:
                total_charge_min = round(total_charge_min, 1)
                derived.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="device.derived",
                        event_type="charging_duration",
                        value_numeric=total_charge_min,
                        value_json=safe_json(
                            {
                                "sessions": charge_sessions,
                                "total_pct_gained": round(total_pct_gained, 1),
                            }
                        ),
                        confidence=0.95,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"[{day}] Charging: {total_charge_min} min, "
                    f"{charge_sessions} session(s), +{total_pct_gained:.0f}%"
                )

        # --- Battery drain rate ---
        batt_rows = db.execute(
            """
            SELECT timestamp_utc, value_numeric FROM events
            WHERE source_module = 'device.battery'
              AND event_type = 'pulse'
              AND date(timestamp_local) = ?
              AND value_numeric IS NOT NULL
            ORDER BY timestamp_utc
            """,
            [day],
        ).fetchall()

        if len(batt_rows) >= 2:
            # Build charging intervals to exclude
            charge_intervals: list[tuple[str, str]] = []
            last_cs: str | None = None
            for etype, ts, _pct in charge_rows if charge_rows else []:
                if etype == "charge_start":
                    last_cs = ts
                elif etype == "charge_stop" and last_cs:
                    charge_intervals.append((last_cs, ts))
                    last_cs = None

            def _is_during_charging(ts_str: str) -> bool:
                for cs_start, cs_end in charge_intervals:
                    if cs_start <= ts_str <= cs_end:
                        return True
                return False

            drain_segments: list[float] = []
            for i in range(len(batt_rows) - 1):
                ts1, pct1 = batt_rows[i][0], batt_rows[i][1]
                ts2, pct2 = batt_rows[i + 1][0], batt_rows[i + 1][1]
                if _is_during_charging(ts1) or _is_during_charging(ts2):
                    continue
                try:
                    dt1 = datetime.fromisoformat(ts1)
                    dt2 = datetime.fromisoformat(ts2)
                    if dt1.tzinfo is None:
                        dt1 = dt1.replace(tzinfo=timezone.utc)
                    if dt2.tzinfo is None:
                        dt2 = dt2.replace(tzinfo=timezone.utc)
                    hours = (dt2 - dt1).total_seconds() / 3600
                    if hours > 0 and pct2 < pct1:
                        drain_segments.append((pct1 - pct2) / hours)
                except (ValueError, TypeError):
                    continue

            if drain_segments:
                avg_drain = round(sum(drain_segments) / len(drain_segments), 2)
                derived.append(
                    Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset="-0500",
                        source_module="device.derived",
                        event_type="battery_drain_rate",
                        value_numeric=avg_drain,
                        value_json=safe_json(
                            {
                                "unit": "pct_per_hour",
                                "segments_analyzed": len(drain_segments),
                                "total_pulses": len(batt_rows),
                            }
                        ),
                        confidence=0.85,
                        parser_version=self.version,
                    )
                )
                log.info(
                    f"[{day}] Battery drain: {avg_drain}%/hr "
                    f"({len(drain_segments)} segments)"
                )

        return derived


def create_module(config: dict | None = None) -> DeviceModule:
    """Factory function called by the orchestrator."""
    return DeviceModule(config)
