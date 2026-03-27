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


# ────────────────────────────────────────────────────────────
# Properties and Factory
# ────────────────────────────────────────────────────────────


class TestMediaModuleProperties:
    """Cover module_id, display_name, source_types, version, get_metrics_manifest."""

    def test_module_id(self):
        mod = create_module(_media_config())
        assert mod.module_id == "media"

    def test_display_name(self):
        mod = create_module(_media_config())
        assert mod.display_name == "Media Module"

    def test_version(self):
        mod = create_module(_media_config())
        assert mod.version == "1.0.0"

    def test_source_types(self):
        mod = create_module(_media_config())
        types = mod.source_types
        assert "media.voice" in types
        assert "media.photo" in types
        assert "media.video" in types
        assert "media.derived" in types

    def test_get_metrics_manifest(self):
        mod = create_module(_media_config())
        manifest = mod.get_metrics_manifest()
        assert "metrics" in manifest
        names = [m["name"] for m in manifest["metrics"]]
        assert "media.photo" in names
        assert "media.voice" in names
        assert "media.video" in names

    def test_create_module_factory_no_config(self):
        """create_module with None config does not crash."""
        from modules.media.module import create_module as factory_fn
        mod = factory_fn(None)
        assert mod.module_id == "media"

    def test_create_module_factory_with_config(self):
        from modules.media.module import create_module as factory_fn
        mod = factory_fn({"enabled": True})
        assert mod.module_id == "media"


# ────────────────────────────────────────────────────────────
# get_daily_summary
# ────────────────────────────────────────────────────────────


class TestGetDailySummary:
    """Cover get_daily_summary method."""

    def test_summary_with_media_events(self, db):
        """Returns summary dict when media events exist for the day."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.photo", "capture", value_text="img1.jpg",
                        minute_offset=0),
            _make_event("media.photo", "capture", value_text="img2.jpg",
                        minute_offset=5),
            _make_event("media.voice", "recording", value_text="memo.wav",
                        minute_offset=10),
        ]
        db.insert_events_for_module("media_summary", events)

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is not None
        assert "event_counts" in summary
        assert summary["total_media_events"] == 3
        assert summary["section_title"] == "Media"
        assert isinstance(summary["bullets"], list)

    def test_summary_no_media_events(self, db):
        """Returns None when no media events exist for the day."""
        mod = create_module(_media_config())

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is None

    def test_summary_event_type_keys(self, db):
        """event_counts keys are source_module.event_type combos."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.video", "clip", value_text="vid.mp4",
                        minute_offset=0),
        ]
        db.insert_events_for_module("media_vid", events)

        summary = mod.get_daily_summary(db, TARGET_DATE)
        assert summary is not None
        assert "media.video.clip" in summary["event_counts"]
        assert summary["event_counts"]["media.video.clip"]["count"] == 1

    def test_summary_different_date_returns_none(self, db):
        """Events on a different date are not included."""
        mod = create_module(_media_config())

        events = [
            _make_event("media.photo", "capture", value_text="img.jpg",
                        minute_offset=0),
        ]
        db.insert_events_for_module("media_photo", events)

        # Query a different date
        summary = mod.get_daily_summary(db, "2026-03-21")
        assert summary is None


# ────────────────────────────────────────────────────────────
# discover_files and parse
# ────────────────────────────────────────────────────────────


class TestDiscoverFilesAndParse:
    """Cover discover_files and parse dispatch logic."""

    def test_discover_files_empty_dir(self, tmp_path):
        """Returns empty list when directory has no matching CSVs."""
        mod = create_module(_media_config())
        files = mod.discover_files(str(tmp_path))
        assert files == []

    def test_discover_files_finds_voice_meta(self, tmp_path):
        """Discovers voice_meta_*.csv in media/voice subdir."""
        mod = create_module(_media_config())
        voice_dir = tmp_path / "media" / "voice"
        voice_dir.mkdir(parents=True)
        csv_file = voice_dir / "voice_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,memo1,30,home\n")

        files = mod.discover_files(str(tmp_path))
        assert len(files) == 1
        assert "voice_meta_2026-03-20.csv" in files[0]

    def test_discover_files_finds_photo_meta(self, tmp_path):
        """Discovers photo_meta_*.csv in media/photos subdir."""
        mod = create_module(_media_config())
        photo_dir = tmp_path / "media" / "photos"
        photo_dir.mkdir(parents=True)
        csv_file = photo_dir / "photo_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,pic1,Landscape,park\n")

        files = mod.discover_files(str(tmp_path))
        assert len(files) == 1

    def test_discover_files_finds_video_meta(self, tmp_path):
        """Discovers video_meta_*.csv in media/video subdir."""
        mod = create_module(_media_config())
        video_dir = tmp_path / "media" / "video"
        video_dir.mkdir(parents=True)
        csv_file = video_dir / "video_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,clip1,walk\n")

        files = mod.discover_files(str(tmp_path))
        assert len(files) == 1

    def test_discover_files_ignores_non_matching_csv(self, tmp_path):
        """Non-matching CSV files in media dirs are ignored."""
        mod = create_module(_media_config())
        media_dir = tmp_path / "media"
        media_dir.mkdir(parents=True)
        (media_dir / "random_data.csv").write_text("foo,bar\n")

        files = mod.discover_files(str(tmp_path))
        assert files == []

    def test_discover_files_deduplicates(self, tmp_path):
        """Symlinks or duplicate paths produce deduplicated results."""
        mod = create_module(_media_config())
        voice_dir = tmp_path / "media" / "voice"
        voice_dir.mkdir(parents=True)
        csv_file = voice_dir / "voice_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,memo1,30,home\n")

        # Also place in logs/media/voice pointing to same file via symlink
        logs_voice_dir = tmp_path / "logs" / "media" / "voice"
        logs_voice_dir.mkdir(parents=True)
        link = logs_voice_dir / "voice_meta_2026-03-20.csv"
        link.symlink_to(csv_file)

        files = mod.discover_files(str(tmp_path))
        # Should deduplicate to just 1 file (same realpath)
        assert len(files) == 1

    def test_parse_voice_meta_csv(self, tmp_path):
        """parse() dispatches voice_meta CSV to correct parser."""
        mod = create_module(_media_config())
        csv_file = tmp_path / "voice_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,memo1,30,home\n")

        events = mod.parse(str(csv_file))
        assert len(events) == 1
        assert events[0].source_module == "media.voice"

    def test_parse_photo_meta_csv(self, tmp_path):
        """parse() dispatches photo_meta CSV to correct parser."""
        mod = create_module(_media_config())
        csv_file = tmp_path / "photo_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,pic1,Landscape,park\n")

        events = mod.parse(str(csv_file))
        assert len(events) == 1
        assert events[0].source_module == "media.photo"

    def test_parse_video_meta_csv(self, tmp_path):
        """parse() dispatches video_meta CSV to correct parser."""
        mod = create_module(_media_config())
        csv_file = tmp_path / "video_meta_2026-03-20.csv"
        csv_file.write_text("1742475600,08:00,clip1,walk\n")

        events = mod.parse(str(csv_file))
        assert len(events) == 1
        assert events[0].source_module == "media.video"

    def test_parse_unknown_file_returns_empty(self, tmp_path):
        """parse() returns empty list for unknown file prefix."""
        mod = create_module(_media_config())
        csv_file = tmp_path / "unknown_data_2026.csv"
        csv_file.write_text("1742475600,something\n")

        events = mod.parse(str(csv_file))
        assert events == []

    def test_parse_empty_csv_returns_empty(self, tmp_path):
        """parse() returns empty list for empty voice_meta CSV."""
        mod = create_module(_media_config())
        csv_file = tmp_path / "voice_meta_empty.csv"
        csv_file.write_text("")

        events = mod.parse(str(csv_file))
        assert events == []


# ────────────────────────────────────────────────────────────
# post_ingest edge cases
# ────────────────────────────────────────────────────────────


class TestPostIngestEdgeCases:
    """Cover post_ingest edge cases: no affected_dates, transcription error."""

    def test_post_ingest_no_affected_dates_uses_today(self, db):
        """When affected_dates is None, post_ingest uses today's date."""
        mod = create_module(_media_config())
        # No events for today, so no derived event — but code path is exercised
        mod.post_ingest(db, affected_dates=None)

        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 0

    def test_post_ingest_transcription_import_error(self, db):
        """Transcription import failure is handled gracefully."""
        mod = create_module(_media_config(auto_transcribe=True))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        with unittest.mock.patch.dict(
            "sys.modules",
            {"modules.media.transcribe": None}
        ):
            # Should not raise — import error is caught
            mod.post_ingest(db, affected_dates={TARGET_DATE})

    def test_post_ingest_transcription_whisper_available_and_transcribes(self, db):
        """When whisper is available and auto_transcribe=True, transcribe_pending is called."""
        mod = create_module(_media_config(auto_transcribe=True))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        with unittest.mock.patch(
            "modules.media.transcribe.is_whisper_available", return_value=True
        ), unittest.mock.patch(
            "modules.media.transcribe.transcribe_pending", return_value=["file1.wav"]
        ) as mock_transcribe:
            mod.post_ingest(db, affected_dates={TARGET_DATE})
            mock_transcribe.assert_called_once()

    def test_post_ingest_transcription_exception_handled(self, db):
        """Exception during transcription is caught and logged."""
        mod = create_module(_media_config(auto_transcribe=True))

        events = [
            _make_event("media.voice", "recording", value_text="memo.wav"),
        ]
        db.insert_events_for_module("media_voice", events)

        with unittest.mock.patch(
            "modules.media.transcribe.is_whisper_available",
            side_effect=RuntimeError("test error"),
        ):
            # Should not raise
            mod.post_ingest(db, affected_dates={TARGET_DATE})

        # Derived metric should still be computed
        rows = db.query_events(source_module="media.derived",
                               event_type="daily_media_count")
        assert len(rows) == 1
