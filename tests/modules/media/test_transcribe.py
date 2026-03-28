"""
Tests for modules/media/transcribe.py — Whisper transcription helper.

Covers:
  - is_whisper_available() — import detection
  - _load_whisper() — lazy model loading with caching
  - transcribe_pending() — file discovery, transcription, error handling
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import modules.media.transcribe as transcribe_mod
from modules.media.transcribe import (
    is_whisper_available,
    transcribe_pending,
)


@pytest.fixture(autouse=True)
def reset_whisper_model_cache():
    """Reset the module-level _whisper_model cache before each test."""
    transcribe_mod._whisper_model = None
    yield
    transcribe_mod._whisper_model = None


# ────────────────────────────────────────────────────────────
# is_whisper_available
# ────────────────────────────────────────────────────────────


class TestIsWhisperAvailable:
    """is_whisper_available() — detect whether whisper can be imported."""

    def test_returns_true_when_importable(self):
        """When whisper module exists, returns True."""
        fake_whisper = MagicMock()
        with patch.dict(sys.modules, {"whisper": fake_whisper}):
            assert is_whisper_available() is True

    def test_returns_false_when_not_installed(self):
        """When whisper is absent, returns False."""
        with patch.dict(sys.modules, {"whisper": None}):
            assert is_whisper_available() is False


# ────────────────────────────────────────────────────────────
# _load_whisper
# ────────────────────────────────────────────────────────────


class TestLoadWhisper:
    """_load_whisper() — lazy model loading with caching."""

    def test_returns_none_when_whisper_unavailable(self):
        """If whisper cannot be imported, returns None."""
        with patch.dict(sys.modules, {"whisper": None}):
            result = transcribe_mod._load_whisper("base")
            assert result is None

    def test_caches_model_on_second_call(self):
        """Model is loaded once and returned from cache on subsequent calls."""
        fake_model = MagicMock(name="whisper_model")
        fake_whisper = MagicMock()
        fake_whisper.load_model.return_value = fake_model

        with patch.dict(sys.modules, {"whisper": fake_whisper}):
            first = transcribe_mod._load_whisper("base")
            second = transcribe_mod._load_whisper("base")

        assert first is fake_model
        assert second is fake_model
        # load_model should only be called once due to caching
        fake_whisper.load_model.assert_called_once_with("base")

    def test_returns_none_on_load_exception(self):
        """If whisper.load_model raises, returns None gracefully."""
        fake_whisper = MagicMock()
        fake_whisper.load_model.side_effect = RuntimeError("CUDA OOM")

        with patch.dict(sys.modules, {"whisper": fake_whisper}):
            result = transcribe_mod._load_whisper("base")
            assert result is None


# ────────────────────────────────────────────────────────────
# transcribe_pending
# ────────────────────────────────────────────────────────────


class TestTranscribePending:
    """transcribe_pending() — discover and transcribe audio files."""

    def test_no_voice_dir_returns_empty(self, tmp_path):
        """If media_dir/voice does not exist, returns empty list."""
        result = transcribe_pending(str(tmp_path), model_name="base")
        assert result == []

    def test_existing_transcripts_skipped(self, tmp_path):
        """Audio files with existing .txt transcripts are skipped."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        # Create an audio file
        (voice_dir / "memo1.m4a").write_bytes(b"fake audio")

        # Create transcript in the transcript output directory
        transcript_dir = os.path.join(
            os.path.expanduser("~/LifeData/media"), "transcripts"
        )
        os.makedirs(transcript_dir, exist_ok=True)
        txt_path = os.path.join(transcript_dir, "memo1.txt")
        with open(txt_path, "w") as f:
            f.write("Already transcribed")

        fake_model = MagicMock()
        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        # Should skip memo1.m4a since transcript exists
        assert result == []
        fake_model.transcribe.assert_not_called()

        # Clean up the transcript we created
        os.remove(txt_path)

    def test_existing_transcript_in_voice_dir_skipped(self, tmp_path):
        """Audio files with .txt in the old location (voice_dir) are also skipped."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "memo2.wav").write_bytes(b"fake audio")
        (voice_dir / "memo2.txt").write_text("Old location transcript")

        fake_model = MagicMock()
        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        assert result == []
        fake_model.transcribe.assert_not_called()

    def test_successful_transcription_writes_txt(self, tmp_path):
        """Mocked successful transcription writes .txt and returns result."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "dream_recording.m4a").write_bytes(b"fake audio")

        fake_model = MagicMock()
        fake_model.transcribe.return_value = {
            "text": "I had a dream about flying.",
            "language": "en",
            "duration": 42.5,
        }

        transcript_dir = os.path.join(
            os.path.expanduser("~/LifeData/media"), "transcripts"
        )
        txt_path = os.path.join(transcript_dir, "dream_recording.txt")
        # Remove any pre-existing transcript file
        if os.path.exists(txt_path):
            os.remove(txt_path)

        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        assert len(result) == 1
        assert result[0]["transcript"] == "I had a dream about flying."
        assert result[0]["language"] == "en"
        assert result[0]["duration_sec"] == 42.5

        # Verify .txt was written
        assert os.path.exists(txt_path)
        with open(txt_path) as f:
            assert f.read() == "I had a dream about flying."

        # Clean up
        os.remove(txt_path)

    def test_transcription_exception_handled_gracefully(self, tmp_path):
        """If model.transcribe() raises, that file is skipped and others continue."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "bad_audio.ogg").write_bytes(b"corrupt")
        (voice_dir / "good_audio.wav").write_bytes(b"good data")

        # Remove any pre-existing transcript files
        transcript_dir = os.path.join(
            os.path.expanduser("~/LifeData/media"), "transcripts"
        )
        os.makedirs(transcript_dir, exist_ok=True)
        for name in ["bad_audio.txt", "good_audio.txt"]:
            path = os.path.join(transcript_dir, name)
            if os.path.exists(path):
                os.remove(path)

        fake_model = MagicMock()

        def side_effect(path):
            if "bad_audio" in path:
                raise RuntimeError("Corrupt audio file")
            return {"text": "Good transcription", "language": "en", "duration": 10.0}

        fake_model.transcribe.side_effect = side_effect

        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        # Only the good audio should produce a result
        assert len(result) == 1
        assert result[0]["transcript"] == "Good transcription"

        # Clean up
        good_txt = os.path.join(transcript_dir, "good_audio.txt")
        if os.path.exists(good_txt):
            os.remove(good_txt)

    def test_whisper_unavailable_returns_empty(self, tmp_path):
        """If whisper model cannot be loaded, returns empty list."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "audio.m4a").write_bytes(b"fake audio")

        with patch.object(transcribe_mod, "_load_whisper", return_value=None):
            result = transcribe_pending(str(tmp_path), model_name="base")

        assert result == []

    def test_non_audio_files_ignored(self, tmp_path):
        """Files without matching audio extensions are ignored."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "notes.txt").write_text("not audio")
        (voice_dir / "image.jpg").write_bytes(b"not audio")

        fake_model = MagicMock()
        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        assert result == []
        fake_model.transcribe.assert_not_called()

    def test_empty_transcript_not_saved(self, tmp_path):
        """If whisper returns empty text, no file is written and no result returned."""
        voice_dir = tmp_path / "voice"
        voice_dir.mkdir()
        (voice_dir / "silence.wav").write_bytes(b"silence")

        transcript_dir = os.path.join(
            os.path.expanduser("~/LifeData/media"), "transcripts"
        )
        os.makedirs(transcript_dir, exist_ok=True)
        txt_path = os.path.join(transcript_dir, "silence.txt")
        if os.path.exists(txt_path):
            os.remove(txt_path)

        fake_model = MagicMock()
        fake_model.transcribe.return_value = {"text": "   ", "language": "en", "duration": 3.0}

        with patch.object(transcribe_mod, "_load_whisper", return_value=fake_model):
            result = transcribe_pending(str(tmp_path), model_name="base")

        assert result == []
        assert not os.path.exists(txt_path)
