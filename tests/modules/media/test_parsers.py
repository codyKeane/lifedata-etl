"""
Tests for modules/media/parsers.py — voice_meta, photo_meta, video_meta CSVs.

Note: EXIF extraction (Pillow), VADER sentiment, and ffprobe are optional
dependencies. These tests cover the CSV parsing logic without requiring
those external tools.
"""

import json

from modules.media.parsers import (
    parse_voice_meta,
    parse_photo_meta,
    parse_video_meta,
    _is_safe_media_id,
)


# ──────────────────────────────────────────────────────────────
# Media ID safety
# ──────────────────────────────────────────────────────────────


class TestMediaIdSafety:
    def test_safe_id(self):
        assert _is_safe_media_id("voice_001") is True
        assert _is_safe_media_id("photo-2026.03.24") is True

    def test_path_traversal_blocked(self):
        assert _is_safe_media_id("../../etc/passwd") is False
        assert _is_safe_media_id("") is False

    def test_space_rejected(self):
        assert _is_safe_media_id("file name") is False


# ──────────────────────────────────────────────────────────────
# Voice meta parser
# ──────────────────────────────────────────────────────────────


class TestParseVoiceMeta:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00,vm001,45.5,home",
            "1711306800,11:00,vm002,120.0,office",
        ]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert len(events) == 2
        assert events[0].source_module == "media.voice"
        assert events[0].event_type == "memo"
        assert events[0].value_numeric == 45.5

    def test_dream_event_type(self, csv_file_factory):
        lines = ["1711303200,10:00,dm001,60.0,bedroom"]
        path = csv_file_factory("dream_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert len(events) == 1
        assert events[0].event_type == "dream_journal"

    def test_voice_id_in_json(self, csv_file_factory):
        lines = ["1711303200,10:00,vm001,45.5,home"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        data = json.loads(events[0].value_json)
        assert data["voice_id"] == "vm001"
        assert data["duration_sec"] == 45.5
        assert data["location"] == "home"

    def test_transcript_loaded(self, tmp_path):
        """If a companion .txt file exists, its content is loaded."""
        csv = tmp_path / "voice_meta_2026.csv"
        csv.write_text("1711303200,10:00,vm001,45.5,home\n")
        transcript = tmp_path / "voice_vm001.txt"
        transcript.write_text("This is a test transcript for the voice memo.")
        events = parse_voice_meta(str(csv))
        assert len(events) == 1
        assert "test transcript" in events[0].value_text

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert len(events) == 0

    def test_non_epoch_skipped(self, csv_file_factory):
        lines = ["header,time,id,dur,loc"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert len(events) == 0

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("voice_meta_2026.csv", [])
        assert parse_voice_meta(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00,vm001,45.5,home"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        for e in parse_voice_meta(path):
            assert e.is_valid

    def test_timezone_offset_default(self, csv_file_factory):
        """Voice meta uses DEFAULT_TZ_OFFSET (-0500)."""
        lines = ["1711303200,10:00,vm001,45.5,home"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert events[0].timezone_offset == "-0500"

    def test_deterministic(self, csv_file_factory):
        lines = ["1711303200,10:00,vm001,45.5,home"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        ids1 = [e.event_id for e in parse_voice_meta(path)]
        ids2 = [e.event_id for e in parse_voice_meta(path)]
        assert ids1 == ids2


# ──────────────────────────────────────────────────────────────
# Photo meta parser
# ──────────────────────────────────────────────────────────────


class TestParsePhotoMeta:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00,img001,Landscape,park",
            "1711306800,11:00,img002,Document,office",
        ]
        path = csv_file_factory("photo_meta_2026.csv", lines)
        events = parse_photo_meta(path)
        assert len(events) == 2
        assert events[0].source_module == "media.photo"
        assert events[0].event_type == "capture"
        assert events[0].value_text == "Landscape"
        assert events[1].event_type == "document"

    def test_category_in_json(self, csv_file_factory):
        lines = ["1711303200,10:00,img001,Landscape,park"]
        path = csv_file_factory("photo_meta_2026.csv", lines)
        events = parse_photo_meta(path)
        data = json.loads(events[0].value_json)
        assert data["photo_id"] == "img001"
        assert data["category"] == "Landscape"

    def test_too_few_fields_skipped(self, csv_file_factory):
        lines = ["1711303200,10:00"]
        path = csv_file_factory("photo_meta_2026.csv", lines)
        assert parse_photo_meta(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("photo_meta_2026.csv", [])
        assert parse_photo_meta(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00,img001,Landscape,park"]
        path = csv_file_factory("photo_meta_2026.csv", lines)
        for e in parse_photo_meta(path):
            assert e.is_valid


# ──────────────────────────────────────────────────────────────
# Video meta parser
# ──────────────────────────────────────────────────────────────


class TestParseVideoMeta:
    def test_happy_path(self, csv_file_factory):
        lines = [
            "1711303200,10:00,vid001,sunset timelapse",
        ]
        path = csv_file_factory("video_meta_2026.csv", lines)
        events = parse_video_meta(path)
        assert len(events) == 1
        assert events[0].source_module == "media.video"
        assert events[0].event_type == "clip"
        assert events[0].value_text == "sunset timelapse"

    def test_no_note_produces_none_text(self, csv_file_factory):
        lines = ["1711303200,10:00,vid001,"]
        path = csv_file_factory("video_meta_2026.csv", lines)
        events = parse_video_meta(path)
        assert len(events) == 1
        assert events[0].value_text is None

    def test_too_few_fields(self, csv_file_factory):
        lines = ["1711303200"]
        path = csv_file_factory("video_meta_2026.csv", lines)
        assert parse_video_meta(path) == []

    def test_empty_file(self, csv_file_factory):
        path = csv_file_factory("video_meta_2026.csv", [])
        assert parse_video_meta(path) == []

    def test_events_valid(self, csv_file_factory):
        lines = ["1711303200,10:00,vid001,clip note"]
        path = csv_file_factory("video_meta_2026.csv", lines)
        for e in parse_video_meta(path):
            assert e.is_valid
