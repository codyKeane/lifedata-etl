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
from typing import TYPE_CHECKING, Any, Callable, Optional

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files, safe_json

if TYPE_CHECKING:
    from core.database import Database

log = get_logger("lifedata.media")


class MediaModule(ModuleInterface):
    """Media module — indexes multimedia metadata from Tasker."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}
        self._parser_registry: dict[str, Any] | None = None

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

    def post_ingest(self, db: Database) -> None:
        """Post-ingestion: run optional transcription and compute derived metrics.

        If auto_transcribe is enabled and Whisper is available, transcribe
        any pending voice files.
        """
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Run transcription if configured
        if self._config.get("auto_transcribe", False):
            try:
                from modules.media.transcribe import transcribe_pending, is_whisper_available
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
        now_utc = datetime.now(timezone.utc).isoformat()
        derived_events = []

        rows = db.execute(
            """
            SELECT source_module, COUNT(*) as cnt
            FROM events
            WHERE source_module LIKE 'media.%'
              AND source_module != 'media.derived'
              AND date(timestamp_utc) = ?
            GROUP BY source_module
            """,
            (today,),
        )
        result_set = rows.fetchall() if hasattr(rows, 'fetchall') else rows
        media_counts = {}
        for row in result_set:
            media_counts[row[0]] = row[1]

        total = sum(media_counts.values())
        if total > 0:
            derived_events.append(Event(
                timestamp_utc=now_utc,
                timestamp_local=now_utc,
                timezone_offset="-0500",
                source_module="media.derived",
                event_type="daily_media_count",
                value_numeric=float(total),
                value_json=safe_json(media_counts),
                confidence=1.0,
                parser_version=self.version,
            ))
            log.info(f"Media today: {total} items ({media_counts})")

        if derived_events:
            inserted, skipped = db.insert_events_for_module("media", derived_events)
            log.info(f"Derived metrics: {inserted} inserted, {skipped} skipped")

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
        }


def create_module(config: dict[str, Any] | None = None) -> MediaModule:
    """Factory function called by the orchestrator."""
    return MediaModule(config)
