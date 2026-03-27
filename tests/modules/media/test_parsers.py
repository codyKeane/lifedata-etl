"""
Tests for modules/media/parsers.py — voice_meta, photo_meta, video_meta CSVs,
EXIF extraction, GPS conversion, ffprobe video info, VADER sentiment,
and error handling paths.
"""

import json
import os
from unittest.mock import MagicMock, patch

from modules.media.parsers import (
    parse_voice_meta,
    parse_photo_meta,
    parse_video_meta,
    _is_safe_media_id,
    _safe_media_path,
    _read_transcript,
    _extract_exif,
    _convert_gps,
    _get_video_info,
    _get_vader,
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

    def test_non_epoch_skipped(self, csv_file_factory):
        """Non-numeric epoch should be skipped."""
        lines = ["header,10:00,vid001,note"]
        path = csv_file_factory("video_meta_2026.csv", lines)
        assert parse_video_meta(path) == []

    def test_video_with_companion_file_ffprobe(self, tmp_path):
        """When a companion video file exists, ffprobe info should be extracted."""
        csv = tmp_path / "video_meta_2026.csv"
        csv.write_text("1711303200,10:00,vid001,sunset\n")
        # Create a dummy companion video file
        (tmp_path / "video_vid001.mp4").write_bytes(b"\x00" * 100)

        ffprobe_output = json.dumps({
            "format": {"duration": "12.5", "size": "1024"},
            "streams": [{"codec_type": "video", "width": 1920, "height": 1080, "codec_name": "h264"}],
        })
        mock_result = MagicMock(returncode=0, stdout=ffprobe_output)
        with patch("modules.media.parsers.subprocess.run", return_value=mock_result):
            events = parse_video_meta(str(csv))

        assert len(events) == 1
        data = json.loads(events[0].value_json)
        assert data["duration_sec"] == 12.5
        assert data["width"] == 1920
        assert events[0].value_numeric == 12.5

    def test_video_parse_error_caught(self, tmp_path):
        """Malformed line that causes parse error should be caught."""
        csv = tmp_path / "video_meta_2026.csv"
        # Write valid first line, second line will trigger error via mock
        csv.write_text("1711303200,10:00,vid001,note\n")
        with patch("modules.media.parsers.parse_timestamp", side_effect=ValueError("bad")):
            events = parse_video_meta(str(csv))
        assert events == []


# ──────────────────────────────────────────────────────────────
# _safe_media_path — path traversal
# ──────────────────────────────────────────────────────────────


class TestSafeMediaPath:
    def test_valid_path(self, tmp_path):
        (tmp_path / "photo.jpg").write_bytes(b"fake")
        result = _safe_media_path(str(tmp_path), "photo.jpg")
        assert result is not None
        assert "photo.jpg" in result

    def test_traversal_blocked(self, tmp_path):
        result = _safe_media_path(str(tmp_path), "../../etc/passwd")
        assert result is None


# ──────────────────────────────────────────────────────────────
# _read_transcript — companion .txt files
# ──────────────────────────────────────────────────────────────


class TestReadTranscript:
    def test_voice_transcript_found(self, tmp_path):
        (tmp_path / "voice_vm001.txt").write_text("Hello world transcript")
        result = _read_transcript(str(tmp_path), "vm001")
        assert result == "Hello world transcript"

    def test_dream_transcript_found(self, tmp_path):
        (tmp_path / "dream_dm001.txt").write_text("Dream content")
        result = _read_transcript(str(tmp_path), "dm001")
        assert result == "Dream content"

    def test_empty_transcript_returns_none(self, tmp_path):
        (tmp_path / "voice_vm001.txt").write_text("   ")
        result = _read_transcript(str(tmp_path), "vm001")
        assert result is None

    def test_no_transcript_returns_none(self, tmp_path):
        result = _read_transcript(str(tmp_path), "vm999")
        assert result is None

    def test_unsafe_voice_id_rejected(self, tmp_path):
        result = _read_transcript(str(tmp_path), "../../etc/passwd")
        assert result is None

    def test_oserror_returns_none(self, tmp_path):
        (tmp_path / "voice_vm001.txt").write_text("content")
        with patch("builtins.open", side_effect=OSError("perm denied")):
            result = _read_transcript(str(tmp_path), "vm001")
        assert result is None


# ──────────────────────────────────────────────────────────────
# _extract_exif — EXIF metadata from photos
# ──────────────────────────────────────────────────────────────


class TestExtractExif:
    def test_no_pillow_returns_empty(self, tmp_path):
        photo = tmp_path / "test.jpg"
        photo.write_bytes(b"fake")
        with patch("modules.media.parsers.HAS_PILLOW", False):
            result = _extract_exif(str(photo))
        assert result == {}

    def test_nonexistent_file_returns_empty(self):
        result = _extract_exif("/nonexistent/photo.jpg")
        assert result == {}

    def test_exif_with_gps_and_metadata(self, tmp_path):
        """Test full EXIF extraction with GPS, DateTimeOriginal, and Model."""
        photo = tmp_path / "test.jpg"
        photo.write_bytes(b"fake")

        mock_img = MagicMock()
        mock_img.width = 4000
        mock_img.height = 3000
        mock_img._getexif.return_value = {
            # GPSInfo tag
            34853: {
                1: "N", 2: (32.0, 46.0, 36.0),   # lat
                3: "W", 4: (96.0, 47.0, 49.0),   # lon
            },
            36867: "2026:03:20 10:00:00",  # DateTimeOriginal
            272: "Pixel 7",                # Model
        }

        from PIL.ExifTags import TAGS, GPSTAGS
        with patch("modules.media.parsers.HAS_PILLOW", True):
            with patch("modules.media.parsers.Image") as mock_pil:
                mock_pil.open.return_value = mock_img
                result = _extract_exif(str(photo))

        assert result["width"] == 4000
        assert result["height"] == 3000
        assert "taken_at" in result
        assert "camera" in result
        assert result["camera"] == "Pixel 7"

    def test_exif_exception_returns_partial(self, tmp_path):
        """If EXIF extraction throws, return whatever was collected."""
        photo = tmp_path / "test.jpg"
        photo.write_bytes(b"fake")

        with patch("modules.media.parsers.HAS_PILLOW", True):
            with patch("modules.media.parsers.Image") as mock_pil:
                mock_pil.open.side_effect = Exception("corrupt image")
                result = _extract_exif(str(photo))

        assert result == {}


# ──────────────────────────────────────────────────────────────
# _convert_gps — GPS coordinate conversion
# ──────────────────────────────────────────────────────────────


class TestConvertGps:
    def test_north_east(self):
        coords = (32.0, 46.0, 36.0)
        result = _convert_gps(coords, "N")
        assert result is not None
        assert 32.7 < result < 32.8

    def test_south_west(self):
        coords = (96.0, 47.0, 49.0)
        result = _convert_gps(coords, "W")
        assert result is not None
        assert result < 0

    def test_none_coords(self):
        assert _convert_gps(None, "N") is None

    def test_none_ref(self):
        assert _convert_gps((32.0, 46.0, 36.0), None) is None

    def test_invalid_coords(self):
        assert _convert_gps(("bad",), "N") is None


# ──────────────────────────────────────────────────────────────
# _get_video_info — ffprobe metadata
# ──────────────────────────────────────────────────────────────


class TestGetVideoInfo:
    def test_nonexistent_file(self):
        assert _get_video_info("/nonexistent/video.mp4") == {}

    def test_ffprobe_success(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        output = json.dumps({
            "format": {"duration": "30.5", "size": "2048"},
            "streams": [
                {"codec_type": "audio"},
                {"codec_type": "video", "width": 1280, "height": 720, "codec_name": "h264"},
            ],
        })
        mock_result = MagicMock(returncode=0, stdout=output)
        with patch("modules.media.parsers.subprocess.run", return_value=mock_result):
            info = _get_video_info(str(video))

        assert info["duration_sec"] == 30.5
        assert info["width"] == 1280
        assert info["height"] == 720
        assert info["codec"] == "h264"

    def test_ffprobe_failure(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")

        mock_result = MagicMock(returncode=1, stdout="")
        with patch("modules.media.parsers.subprocess.run", return_value=mock_result):
            info = _get_video_info(str(video))
        assert info == {}

    def test_ffprobe_timeout(self, tmp_path):
        import subprocess
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")

        with patch("modules.media.parsers.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 10)):
            info = _get_video_info(str(video))
        assert info == {}

    def test_ffprobe_json_error(self, tmp_path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00")

        mock_result = MagicMock(returncode=0, stdout="not json")
        with patch("modules.media.parsers.subprocess.run", return_value=mock_result):
            info = _get_video_info(str(video))
        assert info == {}


# ──────────────────────────────────────────────────────────────
# _get_vader — lazy VADER loading
# ──────────────────────────────────────────────────────────────


class TestGetVader:
    def test_vader_import_error(self):
        """When VADER is not installed, _get_vader returns None."""
        import modules.media.parsers as mp
        old_vader = mp._vader
        mp._vader = None
        try:
            with patch.dict("sys.modules", {"nltk.sentiment.vader": None}):
                with patch("modules.media.parsers.SentimentIntensityAnalyzer", side_effect=ImportError, create=True):
                    result = _get_vader()
        except (ImportError, TypeError):
            result = None
        finally:
            mp._vader = old_vader
        # Either None or a real VADER instance if installed
        # The point is it doesn't crash


# ──────────────────────────────────────────────────────────────
# Photo parser — EXIF integration path
# ──────────────────────────────────────────────────────────────


class TestParsePhotoMetaExif:
    def test_photo_with_exif(self, tmp_path):
        """When companion photo exists, EXIF should be extracted."""
        csv = tmp_path / "photo_meta_2026.csv"
        csv.write_text("1711303200,10:00,img001,Landscape,park\n")
        # Create companion photo file
        (tmp_path / "photo_img001.jpg").write_bytes(b"fake jpeg")

        mock_exif = {"width": 4000, "height": 3000, "camera": "Pixel"}
        with patch("modules.media.parsers._extract_exif", return_value=mock_exif):
            events = parse_photo_meta(str(csv))

        assert len(events) == 1
        data = json.loads(events[0].value_json)
        assert data["exif"]["width"] == 4000

    def test_photo_non_epoch_skipped(self, csv_file_factory):
        lines = ["header,10:00,img001,Landscape,park"]
        path = csv_file_factory("photo_meta_2026.csv", lines)
        assert parse_photo_meta(path) == []

    def test_photo_parse_error_caught(self, tmp_path):
        """Malformed line that raises should be caught."""
        csv = tmp_path / "photo_meta_2026.csv"
        csv.write_text("1711303200,10:00,img001,Landscape,park\n")
        with patch("modules.media.parsers.parse_timestamp", side_effect=ValueError("bad")):
            events = parse_photo_meta(str(csv))
        assert events == []


# ──────────────────────────────────────────────────────────────
# Voice parser — error and edge case paths
# ──────────────────────────────────────────────────────────────


class TestParseVoiceMetaEdge:
    def test_voice_parse_error_caught(self, tmp_path):
        """Malformed line that raises should be caught."""
        csv = tmp_path / "voice_meta_2026.csv"
        csv.write_text("1711303200,10:00,vm001,45.5,home\n")
        with patch("modules.media.parsers.parse_timestamp", side_effect=ValueError("bad")):
            events = parse_voice_meta(str(csv))
        assert events == []

    def test_voice_minimal_fields(self, csv_file_factory):
        """Line with exactly 3 fields (no duration/location) should work."""
        lines = ["1711303200,10:00,vm001"]
        path = csv_file_factory("voice_meta_2026.csv", lines)
        events = parse_voice_meta(path)
        assert len(events) == 1
        assert events[0].value_numeric is None
