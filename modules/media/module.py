"""
LifeData V4 — Media Module
modules/media/module.py

Captures, indexes, and processes multimedia metadata: voice recordings,
photographs, and video clips. Media files are archived as-is — the
metadata, transcripts, and extracted features are stored as events.

File discovery pattern:
  logs/media/voice/voice_meta_*.csv  → media.voice  (memos, dreams)
  logs/media/photos/photo_meta_*.csv → media.photo   (photos + EXIF)
  logs/media/video/video_meta_*.csv  → media.video   (clips + ffprobe)
"""

from __future__ import annotations

import os
from datetime import UTC
from typing import TYPE_CHECKING, Any

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import get_utc_offset, glob_files, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.media")


class MediaModule(ModuleInterface):
    """Media module — indexes multimedia metadata from Tasker."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._parser_registry: dict[str, Any] | None = None

    def _tz_offset(self, date_str: str) -> str:
        """Get DST-aware UTC offset for a date from config timezone."""
        tz_name = self._config.get("_timezone", "America/Chicago")
        try:
            return get_utc_offset(tz_name, date_str)
        except Exception:
            return str(self._config.get("_default_tz_offset", "-0500"))

    def _get_parsers(self) -> dict[str, Any]:
        """Lazy-load parser registry."""
        if self._parser_registry is None:
            from modules.media.parsers import PARSER_REGISTRY
            self._parser_registry = PARSER_REGISTRY
        assert self._parser_registry is not None
        return self._parser_registry

    @property
    def module_id(self) -> str:
        return "media"

    @property
    def display_name(self) -> str:
        return "Media Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "media.voice",
            "media.photo",
            "media.video",
            "media.derived",
        ]

    def get_metrics_manifest(self) -> dict[str, Any]:
        """Return machine-readable manifest of metrics this module produces."""
        return {
            "metrics": [
                {
                    "name": "media.photo",
                    "display_name": "Photos",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "media.voice",
                    "display_name": "Voice Memos",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "media.video",
                    "display_name": "Videos",
                    "unit": "count",
                    "aggregate": "COUNT",
                    "trend_eligible": False,
                    "anomaly_eligible": False,
                },
                {
                    "name": "media.derived:daily_media_count",
                    "display_name": "Daily Media Count",
                    "unit": "count",
                    "aggregate": "SUM",
                    "event_type": "daily_media_count",
                    "trend_eligible": True,
                    "anomaly_eligible": True,
                },
            ]
        }

    def discover_files(self, raw_base: str) -> list[str]:
        """Find media metadata CSV files in the raw data tree."""
        files = []
        expanded = os.path.expanduser(raw_base)

        search_dirs = [
            os.path.join(expanded, "media"),
            os.path.join(expanded, "media", "voice"),
            os.path.join(expanded, "media", "photos"),
            os.path.join(expanded, "media", "video"),
            os.path.join(expanded, "logs", "media"),
            os.path.join(expanded, "logs", "media", "voice"),
            os.path.join(expanded, "logs", "media", "photos"),
            os.path.join(expanded, "logs", "media", "video"),
        ]

        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue
            for csv_file in glob_files(search_dir, "*.csv", recursive=False):
                basename = os.path.basename(csv_file)
                if any(basename.startswith(prefix) for prefix in self._get_parsers()):
                    files.append(csv_file)

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
        """Parse a single media metadata CSV using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in self._get_parsers().items():
            if basename.startswith(prefix):
                events: list[Event] = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for media file: {basename}")
        return []

    def post_ingest(self, db: Database, affected_dates: set[str] | None = None) -> None:
        """Post-ingestion: run optional transcription and compute derived metrics.

        If auto_transcribe is enabled and Whisper is available, transcribe
        any pending voice files.
        """
        from datetime import datetime

        # Determine which dates to process
        if affected_dates:
            days_to_process = sorted(affected_dates)
        else:
            days_to_process = [datetime.now(UTC).strftime("%Y-%m-%d")]

        # Run transcription if configured
        if self._config.get("auto_transcribe", False):
            try:
                from modules.media.transcribe import is_whisper_available, transcribe_pending
                if is_whisper_available():
                    media_dir = os.path.expanduser(
                        "~/LifeData/raw/LifeData/logs/media"
                    )
                    model = self._config.get("whisper_model", "base")
                    results = transcribe_pending(media_dir, model)
                    if results:
                        log.info(f"Transcribed {len(results)} voice files")
                else:
                    log.debug("Whisper not available — skipping transcription")
            except Exception as e:
                log.warning(f"Transcription error: {e}")

        # Compute daily media frequency metrics
        all_derived: list[Event] = []
        if self.is_metric_enabled("media.derived:daily_media_count"):
            for process_day in days_to_process:
                # Deterministic timestamp for derived daily metrics (idempotent hashing)
                day_ts = f"{process_day}T23:59:00+00:00"

                rows = db.execute(
                    """
                    SELECT source_module, COUNT(*) as cnt
                    FROM events
                    WHERE source_module LIKE 'media.%'
                      AND source_module != 'media.derived'
                      AND date(timestamp_utc) = ?
                    GROUP BY source_module
                    """,
                    (process_day,),
                )
                result_set = rows.fetchall() if hasattr(rows, 'fetchall') else rows
                media_counts = {}
                for row in result_set:
                    media_counts[row[0]] = row[1]

                total = sum(media_counts.values())
                if total > 0:
                    all_derived.append(Event(
                        timestamp_utc=day_ts,
                        timestamp_local=day_ts,
                        timezone_offset=self._tz_offset(process_day),
                        source_module="media.derived",
                        event_type="daily_media_count",
                        value_numeric=float(total),
                        value_json=safe_json(media_counts),
                        confidence=1.0,
                        parser_version=self.version,
                    ))
                    log.info(f"Media {process_day}: {total} items ({media_counts})")

        if all_derived:
            inserted, skipped = db.insert_events_for_module("media", all_derived)
            log.info(f"Media derived: {inserted} inserted, {skipped} skipped")

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Return daily media metrics for report generation."""
        rows = db.execute(
            """
            SELECT source_module, event_type, COUNT(*) as cnt
            FROM events
            WHERE source_module LIKE 'media.%'
              AND date(timestamp_utc) = ?
            GROUP BY source_module, event_type
            """,
            (date_str,),
        )

        summary = {}
        result_set = rows.fetchall() if hasattr(rows, 'fetchall') else rows
        for row in result_set:
            src, evt, cnt = row
            key = f"{src}.{evt}"
            summary[key] = {"count": cnt}

        if not summary:
            return None

        return {
            "event_counts": summary,
            "total_media_events": sum(v["count"] for v in summary.values()),
            "section_title": "Media",
            "bullets": [],
        }


def create_module(config: dict[str, Any] | None = None) -> MediaModule:
    """Factory function called by the orchestrator."""
    return MediaModule(config)
