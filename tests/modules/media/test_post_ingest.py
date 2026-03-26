"""
Tests for MediaModule.post_ingest() derived metric computation.

Covers:
  - media.derived/daily_media_count — COUNT of media.voice, media.photo, media.video
  - Transcription skip when auto_transcribe=False
"""

import json
import unittest.mock

import pytest

from core.event import Event
from modules.media import create_module

TARGET_DATE = "2026-03-20"
TZ_OFFSET = "-0500"


def _media_config(auto_transcribe=False):
    return {
        "enabled": True,
        "auto_transcribe": auto_transcribe,
    }


def _make_event(source_module, event_type, value_numeric=None, value_text=None,
                minute_offset=0):
    """Build a media event at a known timestamp on TARGET_DATE."""
    from datetime import datetime, timedelta, timezone as tz

    dt = datetime(2026, 3, 20, 13, 0, 0, tzinfo=tz.utc) + timedelta(minutes=minute_offset)
    ts_utc = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    ts_local = (dt - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset=TZ_OFFSET,
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric,
        value_text=value_text,
        confidence=1.0,
        parser_version="1.0.0",
    )


# ────────────────────────────────────────────────────────────
# Daily Media Count
# ────────────────────────────────────────────────────────────


class TestDailyMediaCount:
    """media.derived/daily_media_count — total media events per day."""

    def test_photos_and_voice_counted(self, db):
        """3 photos + 2 voice recordings = total 5."""
        mod = create_module(_media_config())

        photos = [
            _make_event("media.photo", "capture", value_text="photo.jpg",
                        minute_offset=i * 10)
            for i in range(3)
        ]
        voice = [
            _make_event("media.voice", "recording", value_text="memo.wav",
                        minute_offset=30 + i * 15)
            for i in range(2)
        ]
        db.insert_events_for_module("media_photo", photos)
        db.insert_events_for_module("media_voice", voice)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        row = rows[0]
        assert row["value_numeric"] == 5.0

        data = json.loads(row["value_json"])
        assert data["media.photo"] == 3
        assert data["media.voice"] == 2

    def test_no_media_no_event(self, db):
        """With no media events, no daily_media_count is produced."""
        mod = create_module(_media_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 0

    def test_video_counted(self, db):
        """Video events are also included in the count."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.video", "capture", value_text="clip.mp4",
                        minute_offset=i * 20)
            for i in range(4)
        ]
        db.insert_events_for_module("media_video", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 4.0

    def test_derived_events_excluded_from_count(self, db):
        """media.derived events are NOT counted as media items."""
        mod = create_module(_media_config())

        # Insert a photo and a pre-existing derived event
        photo = _make_event("media.photo", "capture", value_text="photo.jpg",
                            minute_offset=0)
        derived = _make_event("media.derived", "daily_media_count",
                              value_numeric=99.0, minute_offset=5)
        db.insert_events_for_module("media_photo", [photo])
        db.insert_events_for_module("media_derived", [derived])

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        # Should count only the photo (1), not the derived event
        # There may be 2 rows (pre-existing + new) so find the one from post_ingest
        counts = [r["value_numeric"] for r in rows]
        assert 1.0 in counts


# ────────────────────────────────────────────────────────────
# Transcription Skipped
# ────────────────────────────────────────────────────────────


class TestTranscriptionSkipped:
    """auto_transcribe=False should not crash and should not attempt transcription."""

    def test_auto_transcribe_false_no_crash(self, db):
        """post_ingest with auto_transcribe=False completes without error."""
        mod = create_module(_media_config(auto_transcribe=False))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        # Should not raise
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        # Voice event exists but no transcription-related crash
        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 1.0

    def test_auto_transcribe_true_no_crash(self, db):
        """post_ingest with auto_transcribe=True doesn't crash even without Whisper."""
        mod = create_module(_media_config(auto_transcribe=True))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        # Should not raise — Whisper unavailability is handled gracefully
        mod.post_ingest(db, affected_dates={TARGET_DATE})

    def test_auto_transcribe_false_does_not_call_whisper(self, db):
        """With auto_transcribe=False, transcription imports are never touched."""
        mod = create_module(_media_config(auto_transcribe=False))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        with unittest.mock.patch(
            "modules.media.transcribe.is_whisper_available"
        ) as mock_avail:
            mod.post_ingest(db, affected_dates={TARGET_DATE})
            mock_avail.assert_not_called()

    def test_auto_transcribe_true_whisper_unavailable_graceful(self, db):
        """With auto_transcribe=True but whisper unavailable, skips gracefully."""
        mod = create_module(_media_config(auto_transcribe=True))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        with unittest.mock.patch(
            "modules.media.transcribe.is_whisper_available", return_value=False
        ):
            # Should not raise
            mod.post_ingest(db, affected_dates={TARGET_DATE})

        # Derived metrics should still be computed despite transcription skip
        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 1.0


# ────────────────────────────────────────────────────────────
# Additional Daily Media Count Tests
# ────────────────────────────────────────────────────────────


class TestDailyMediaCountExtended:
    """Additional coverage for daily_media_count edge cases."""

    def test_mixed_media_types_breakdown(self, db):
        """Voice + photo + video → correct total and per-type breakdown."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav",
                        minute_offset=0),
            _make_event("media.voice", "recording", value_text="memo2.wav",
                        minute_offset=5),
            _make_event("media.photo", "capture", value_text="img.jpg",
                        minute_offset=10),
            _make_event("media.video", "capture", value_text="clip.mp4",
                        minute_offset=15),
            _make_event("media.video", "capture", value_text="clip2.mp4",
                        minute_offset=20),
            _make_event("media.video", "capture", value_text="clip3.mp4",
                        minute_offset=25),
        ]
        db.insert_events_for_module("media_mixed", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        row = rows[0]
        assert row["value_numeric"] == 6.0

        data = json.loads(row["value_json"])
        assert data["media.voice"] == 2
        assert data["media.photo"] == 1
        assert data["media.video"] == 3

    def test_single_type_only(self, db):
        """A single photo event produces count=1 with only photo in breakdown."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.photo", "capture", value_text="solo.jpg",
                        minute_offset=0),
        ]
        db.insert_events_for_module("media_photo", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        assert rows[0]["value_numeric"] == 1.0

        data = json.loads(rows[0]["value_json"])
        assert data == {"media.photo": 1}

    def test_no_media_events_no_derived(self, db):
        """With zero media events on the day, no derived event is created."""
        mod = create_module(_media_config())

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 0

    def test_value_json_contains_all_types(self, db):
        """value_json keys correspond exactly to the source_module values present."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.voice", "recording", value_text="v1.wav",
                        minute_offset=0),
            _make_event("media.photo", "capture", value_text="p1.jpg",
                        minute_offset=10),
        ]
        db.insert_events_for_module("media_vp", events)

        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
        data = json.loads(rows[0]["value_json"])
        assert set(data.keys()) == {"media.voice", "media.photo"}


# ────────────────────────────────────────────────────────────
# Disabled Metrics
# ────────────────────────────────────────────────────────────


class TestMediaDisabledMetrics:
    """Verify disabled_metrics prevents media derived metric computation."""

    def test_disable_daily_media_count_skips(self, db):
        """Disabling media.derived:daily_media_count produces no event."""
        cfg = {
            "enabled": True,
            "auto_transcribe": False,
            "disabled_metrics": ["media.derived:daily_media_count"],
        }
        mod = create_module(cfg)

        events = [
            _make_event("media.photo", "capture", value_text="photo.jpg",
                        minute_offset=0),
            _make_event("media.voice", "recording", value_text="memo.wav",
                        minute_offset=10),
        ]
        db.insert_events_for_module("media_disabled", events)
        mod.post_ingest(db, affected_dates={TARGET_DATE})

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 0
