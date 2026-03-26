"""
LifeData V4 — Social Module
modules/social/module.py

Handles communication and social interaction data: notifications, calls,
SMS, app usage, and WiFi connectivity.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json
from modules.social.parsers import PARSER_REGISTRY

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.social")


class SocialModule(ModuleInterface):
    """Social module — parses communication and app usage data."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "social"

    @property
    def display_name(self) -> str:
        return "Social Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "social.notification",
            "social.call",
            "social.sms",
            "social.app_usage",
            "social.wifi",
            "social.derived",
        ]

    def get_metrics_manifest(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "name": "social.notification",
                    "display_name": "Notifications",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": True,
                },
                {
                    "name": "social.call",
                    "display_name": "Calls",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "social.sms",
                    "display_name": "SMS Messages",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "event_type": None,
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "social.derived:density_score",
                    "display_name": "Social Density",
                    "unit": "score",
                    "aggregate": "AVG",
                    "event_type": "density_score",
                    "trend_eligible": True,
                    "anomaly_eligible": True,
                },
            ],
        }

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all social/communication CSV files in the raw data tree."""
        files = []
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "communication"),
            os.path.join(raw_base, "logs", "communication"),
            os.path.join(raw_base, "apps"),
            os.path.join(raw_base, "logs", "apps"),
            os.path.join(raw_base, "network"),
            os.path.join(raw_base, "logs", "network"),
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
        """Parse a single social CSV file."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for social file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Compute derived social metrics after ingestion.

        Only recomputes for dates that had events ingested this run.
        Derived metrics per day:
          - social.derived/density_score: weighted human interaction score
          - social.derived/digital_hygiene: productive vs distraction app ratio
          - social.derived/notification_load: notifications per active hour
        """
        if affected_dates is not None:
            days = sorted(affected_dates)
        else:
            date_rows = db.execute(
                """
                SELECT DISTINCT date(timestamp_local) as d FROM events
                WHERE source_module LIKE 'social.%'
                  AND source_module != 'social.derived'
                ORDER BY d
                """
            ).fetchall()
            days = [row[0] for row in date_rows]

        all_derived: list[Event] = []
        for day in days:
            all_derived.extend(self._compute_day_metrics(db, day))

        if all_derived:
            inserted, skipped = db.insert_events_for_module("social", all_derived)
            log.info(f"Social derived: {inserted} inserted, {skipped} skipped")

    def _compute_day_metrics(self, db: Database, day: str) -> list[Event]:
        """Compute derived social metrics for a single day."""
        derived: list[Event] = []
        # Deterministic timestamp for derived daily metrics (idempotent hashing)
        day_ts = f"{day}T23:59:00+00:00"

        # --- Density score ---
        # Weighted measure of human interaction volume.
        # Calls (heaviest signal) > SMS > notifications (lightest).
        counts: dict[str, int] = {}
        count_rows = db.execute(
            """
            SELECT source_module, COUNT(*) as cnt FROM events
            WHERE source_module IN (
                'social.call', 'social.sms', 'social.notification'
            )
              AND date(timestamp_local) = ?
            GROUP BY source_module
            """,
            [day],
        ).fetchall()
        for src, cnt in count_rows:
            counts[src] = cnt

        call_count = counts.get("social.call", 0)
        sms_count = counts.get("social.sms", 0)
        notif_count = counts.get("social.notification", 0)

        if call_count + sms_count + notif_count > 0:
            density = round(call_count * 3.0 + sms_count * 2.0 + notif_count * 0.1, 1)
            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="social.derived",
                    event_type="density_score",
                    value_numeric=density,
                    value_json=safe_json(
                        {
                            "calls": call_count,
                            "sms": sms_count,
                            "notifications": notif_count,
                            "weights": {"call": 3.0, "sms": 2.0, "notification": 0.1},
                        }
                    ),
                    confidence=0.9,
                    parser_version=self.version,
                )
            )
            log.info(
                f"[{day}] Density score: {density} "
                f"(calls={call_count}, sms={sms_count}, notif={notif_count})"
            )

        # --- Digital hygiene ---
        # Ratio of productive app usage to total app usage.
        # Productive apps: known work/utility apps. Distraction: social media, games.
        app_rows = db.execute(
            """
            SELECT value_text FROM events
            WHERE source_module = 'social.app_usage'
              AND event_type = 'foreground'
              AND date(timestamp_local) = ?
              AND value_text IS NOT NULL
            """,
            [day],
        ).fetchall()

        if app_rows:
            # Classify apps into productive vs distraction
            productive_keywords = {
                "terminal",
                "code",
                "editor",
                "file",
                "calendar",
                "email",
                "mail",
                "clock",
                "calculator",
                "notes",
                "settings",
                "dialer",
                "contacts",
                "maps",
                "camera",
                "syncthing",
                "tasker",
                "launcher",
                "keyboard",
            }
            distraction_keywords = {
                "reddit",
                "twitter",
                "instagram",
                "tiktok",
                "facebook",
                "youtube",
                "netflix",
                "game",
                "twitch",
                "snapchat",
                "discord",
            }

            productive = 0
            distraction = 0
            neutral = 0

            for (app_name,) in app_rows:
                name_lower = app_name.lower() if app_name else ""
                if any(kw in name_lower for kw in productive_keywords):
                    productive += 1
                elif any(kw in name_lower for kw in distraction_keywords):
                    distraction += 1
                else:
                    neutral += 1

            total_apps = productive + distraction + neutral
            hygiene_ratio = (
                round(productive / total_apps * 100, 1) if total_apps > 0 else 0.0
            )

            derived.append(
                Event(
                    timestamp_utc=day_ts,
                    timestamp_local=day_ts,
                    timezone_offset="-0500",
                    source_module="social.derived",
                    event_type="digital_hygiene",
                    value_numeric=hygiene_ratio,
                    value_json=safe_json(
                        {
                            "productive": productive,
                            "distraction": distraction,
                            "neutral": neutral,
                            "total_app_switches": total_apps,
                            "unit": "productive_pct",
                        }
                    ),
                    confidence=0.75,
                    parser_version=self.version,
                )
            )
            log.info(
                f"[{day}] Digital hygiene: {hygiene_ratio}% productive "
                f"({productive}/{total_apps})"
            )

        # --- Notification load (per active hour) ---
        if notif_count > 0:
            # Estimate active hours from first to last notification
            notif_times = db.execute(
                """
                SELECT MIN(timestamp_utc), MAX(timestamp_utc) FROM events
                WHERE source_module = 'social.notification'
                  AND date(timestamp_local) = ?
                """,
                [day],
            ).fetchone()

            if notif_times and notif_times[0] and notif_times[1]:
                try:
                    dt_first = datetime.fromisoformat(notif_times[0])
                    dt_last = datetime.fromisoformat(notif_times[1])
                    if dt_first.tzinfo is None:
                        dt_first = dt_first.replace(tzinfo=UTC)
                    if dt_last.tzinfo is None:
                        dt_last = dt_last.replace(tzinfo=UTC)
                    active_hours = (dt_last - dt_first).total_seconds() / 3600
                    if active_hours < 1:
                        active_hours = 1.0  # minimum 1 hour
                    load = round(notif_count / active_hours, 1)

                    derived.append(
                        Event(
                            timestamp_utc=day_ts,
                            timestamp_local=day_ts,
                            timezone_offset="-0500",
                            source_module="social.derived",
                            event_type="notification_load",
                            value_numeric=load,
                            value_json=safe_json(
                                {
                                    "notifications": notif_count,
                                    "active_hours": round(active_hours, 1),
                                    "unit": "notifications_per_hour",
                                }
                            ),
                            confidence=0.85,
                            parser_version=self.version,
                        )
                    )
                    log.info(
                        f"[{day}] Notification load: {load}/hr "
                        f"({notif_count} over {active_hours:.1f}h)"
                    )
                except (ValueError, TypeError):
                    pass

        return derived

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily social metrics for report generation."""
        bullets: list[str] = []

        rows = db.conn.execute(
            """
            SELECT source_module, COUNT(*) as n
            FROM events
            WHERE source_module LIKE 'social.%'
              AND date(timestamp_local) = ?
            GROUP BY source_module
            ORDER BY n DESC
            """,
            [date_str],
        ).fetchall()

        for row in rows:
            label = row[0].replace("social.", "").replace("_", " ").title()
            bullets.append(f"- {label}: {row[1]:,}")

        if not bullets:
            return None
        return {"section_title": "Social & Apps", "bullets": bullets}


def create_module(config: dict[str, Any] | None = None) -> SocialModule:
    """Factory function called by the orchestrator."""
    return SocialModule(config)
