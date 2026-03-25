"""
LifeData V4 — Meta Module
modules/meta/module.py

Monitors the health of the LifeData system itself: data completeness,
quality, storage, sync lag, and backup freshness. This is the immune
system of the observatory — it tells you when something is broken
before you notice gaps in your data.

Implements the ModuleInterface contract. Unlike other modules, Meta
doesn't parse files — it inspects the database and filesystem during
post_ingest.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import safe_json, today_local

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.meta")

PARSER_VERSION = "1.0.0"
DEFAULT_TZ_OFFSET = "-0500"


class MetaModule(ModuleInterface):
    """Meta module — monitors LifeData system health."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "meta"

    @property
    def display_name(self) -> str:
        return "Meta Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "meta.etl",
            "meta.completeness",
            "meta.storage",
            "meta.quality",
            "meta.sync",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        # Meta module doesn't parse files — it inspects the database
        return []

    def parse(self, file_path: str) -> list[Event]:
        # Meta module doesn't parse files
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Run all health checks after other modules finish.

        Each check is gated by its config flag. Errors in individual
        checks are caught and logged, never crashing the ETL.
        """
        events: list[Event] = []
        date_str = today_local()

        # Use a FIXED timestamp per day (midnight UTC of the date)
        # so that raw_source_id hashes are deterministic within a day.
        # This ensures INSERT OR REPLACE deduplicates meta events
        # when the ETL runs multiple times in the same day.
        fixed_ts = f"{date_str}T00:00:00+00:00"

        from core.utils import parse_timestamp

        ts_utc, ts_local = parse_timestamp(fixed_ts, DEFAULT_TZ_OFFSET)

        # --- Completeness Check ---
        if self._config.get("completeness_check", True):
            try:
                from modules.meta.completeness import check_daily_completeness

                report = check_daily_completeness(db, date_str)
                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="meta.completeness",
                        event_type="daily_check",
                        value_numeric=report["overall_pct"],
                        value_json=safe_json(
                            {
                                "date": date_str,
                                "missing_count": len(report["missing"]),
                                "missing_sources": [
                                    m["source"] for m in report["missing"]
                                ],
                                "warning_count": len(report["warnings"]),
                            }
                        ),
                        tags="health,completeness",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )
                log.info(
                    f"Completeness: {report['overall_pct']}% "
                    f"({len(report['missing'])} missing)"
                )
            except Exception as e:
                log.error(f"Completeness check failed: {e}", exc_info=True)

        # --- Quality Check ---
        if self._config.get("quality_check", True):
            try:
                from modules.meta.quality import validate_events

                issues = validate_events(db, date_str)
                issue_count = len(issues)
                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="meta.quality",
                        event_type="daily_check",
                        value_numeric=float(issue_count),
                        value_json=safe_json(
                            {
                                "date": date_str,
                                "issue_count": issue_count,
                                "issues": [
                                    {
                                        "type": i["type"],
                                        "severity": i.get("severity", "info"),
                                        "message": i["message"],
                                    }
                                    for i in issues[:20]  # Cap at 20 for JSON size
                                ],
                            }
                        ),
                        tags="health,quality",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )
                log.info(f"Quality: {issue_count} issue(s)")
            except Exception as e:
                log.error(f"Quality check failed: {e}", exc_info=True)

        # --- Storage Check ---
        if self._config.get("storage_check", True):
            try:
                from modules.meta.storage import storage_report

                # Build a minimal config dict for storage_report
                storage_config = self._build_full_config()
                report = storage_report(storage_config)

                # Extract disk info for value_numeric
                disk = report.get("disk", {})
                db_size = report.get("database", {}).get("size_mb", 0)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="meta.storage",
                        event_type="usage_report",
                        value_numeric=db_size,
                        value_json=safe_json(
                            {
                                "date": date_str,
                                "db_size_mb": db_size,
                                "raw_size_mb": report.get("raw_data", {}).get(
                                    "size_mb", 0
                                ),
                                "disk_free_gb": disk.get("free_gb", 0),
                                "disk_used_pct": disk.get("used_pct", 0),
                            }
                        ),
                        tags="health,storage",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )
                log.info(
                    f"Storage: DB {db_size} MB, disk {disk.get('free_gb', '?')} GB free"
                )
            except Exception as e:
                log.error(f"Storage check failed: {e}", exc_info=True)

        # --- Sync Lag Check ---
        if self._config.get("sync_lag_check", True):
            try:
                from modules.meta.sync import check_sync_lag

                raw_base = self._get_raw_base()
                lag = check_sync_lag(raw_base)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="meta.sync",
                        event_type="sync_status",
                        value_numeric=float(lag["newest_file_age_minutes"]),
                        value_json=safe_json(
                            {
                                "date": date_str,
                                "lag_minutes": lag["newest_file_age_minutes"],
                                "healthy": lag["healthy"],
                            }
                        ),
                        tags="health,sync",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )
                log.info(f"Sync: {lag['message']}")
            except Exception as e:
                log.error(f"Sync lag check failed: {e}", exc_info=True)

        # --- DB Backup Check ---
        if self._config.get("db_backup_check", True):
            try:
                from modules.meta.sync import check_db_backup_age

                db_path = self._get_db_path()
                backup = check_db_backup_age(db_path)

                events.append(
                    Event(
                        timestamp_utc=ts_utc,
                        timestamp_local=ts_local,
                        timezone_offset=DEFAULT_TZ_OFFSET,
                        source_module="meta.sync",
                        event_type="backup_status",
                        value_numeric=(
                            backup["newest_backup_age_days"]
                            if backup["newest_backup_age_days"] is not None
                            else -1.0
                        ),
                        value_json=safe_json(
                            {
                                "date": date_str,
                                "healthy": backup["healthy"],
                            }
                        ),
                        tags="health,backup",
                        confidence=1.0,
                        parser_version=PARSER_VERSION,
                    )
                )
                log.info(f"Backup: {backup['message']}")
            except Exception as e:
                log.error(f"Backup check failed: {e}", exc_info=True)

        # --- Syncthing Relay Check ---
        if self._config.get("syncthing_relay_check", True):
            try:
                from modules.meta.sync import verify_syncthing_relay

                # Get API key from environment-resolved config
                api_key = self._config.get("syncthing_api_key", "")
                if api_key:
                    relay = verify_syncthing_relay(api_key)
                    severity = "critical" if relay.get("relay_enabled") else "info"
                    events.append(
                        Event(
                            timestamp_utc=ts_utc,
                            timestamp_local=ts_local,
                            timezone_offset=DEFAULT_TZ_OFFSET,
                            source_module="meta.sync",
                            event_type="relay_check",
                            value_text=relay["message"],
                            value_json=safe_json(
                                {
                                    "date": date_str,
                                    "healthy": relay["healthy"],
                                    "relay_enabled": relay["relay_enabled"],
                                }
                            ),
                            tags=f"health,security,{severity}",
                            confidence=1.0,
                            parser_version=PARSER_VERSION,
                        )
                    )
                    log.info(f"Relay: {relay['message']}")
                else:
                    log.info("Relay check skipped — no Syncthing API key configured")
            except Exception as e:
                log.error(f"Syncthing relay check failed: {e}", exc_info=True)

        # --- Insert all meta events ---
        if events:
            try:
                inserted, skipped = db.insert_events_for_module("meta", events)
                log.info(
                    f"Meta module: {inserted} health events recorded "
                    f"({skipped} skipped)"
                )
            except Exception as e:
                log.error(f"Failed to insert meta events: {e}", exc_info=True)

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return meta health metrics for report generation."""
        try:
            cursor = db.execute(
                """
                SELECT source_module, event_type, value_numeric, value_json
                FROM events
                WHERE date(timestamp_local) = ?
                  AND source_module LIKE 'meta.%'
                ORDER BY timestamp_utc DESC
                """,
                [date_str],
            )
            rows = cursor.fetchall()
        except Exception as e:
            log.warning(f"Failed to query meta summary for {date_str}: {e}")
            return None

        if not rows:
            return None

        summary: dict[str, Any] = {}
        for source, etype, val_num, val_json in rows:
            key = f"{source}.{etype}"
            if key not in summary:
                summary[key] = {
                    "value": val_num,
                }
                if val_json:
                    try:
                        summary[key]["detail"] = json.loads(val_json)
                    except (json.JSONDecodeError, TypeError):
                        pass

        return summary if summary else None

    def _build_full_config(self) -> dict[str, Any]:
        """Build a config dict suitable for storage_report.

        The module config only contains meta-specific keys.
        We need the top-level lifedata keys for paths.
        """
        # Try to read from the orchestrator's full config
        # Fall back to sensible defaults
        return {
            "lifedata": {
                "db_path": self._get_db_path(),
                "raw_base": self._get_raw_base(),
                "media_base": "~/LifeData/media",
                "reports_dir": "~/LifeData/reports",
            }
        }

    def _get_raw_base(self) -> str:
        """Get raw_base path from config or default."""
        return str(self._config.get("_raw_base", "~/LifeData/raw/LifeData"))

    def _get_db_path(self) -> str:
        """Get db_path from config or default."""
        return str(self._config.get("_db_path", "~/LifeData/db/lifedata.db"))


def create_module(config: dict[str, Any] | None = None) -> MetaModule:
    """Factory function called by the orchestrator."""
    return MetaModule(config)
