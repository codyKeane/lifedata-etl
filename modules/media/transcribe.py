"""
LifeData V4 — Media Module: Whisper Transcription Helper
modules/media/transcribe.py

Scans voice recording directories for audio files without companion
.txt transcripts and runs OpenAI Whisper on them.

Whisper is an OPTIONAL dependency (~1GB+). This module gracefully
returns empty results when Whisper is not installed.

Usage:
    # As module (from project root):
    python -m modules.media.transcribe

    # Called from the media module's post_ingest hook
"""

from __future__ import annotations

import os
import sys
from typing import Any

# Lazy Whisper import — only load when actually called
_whisper_model: Any = None


def _load_whisper(model_name: str = "base") -> Any:
    """Load Whisper model, returning None if not available."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    try:
        import whisper
        print(f"Loading Whisper model '{model_name}'...")
        _whisper_model = whisper.load_model(model_name)
        return _whisper_model
    except ImportError:
        return None
    except Exception as e:
        print(f"Whisper load failed: {e}")
        return None


def transcribe_pending(
    media_dir: str,
    model_name: str = "base",
    extensions: tuple[str, ...] = (".3gp", ".m4a", ".mp3", ".wav", ".ogg"),
) -> list[dict[str, Any]]:
    """Find and transcribe audio files that don't have a .txt companion.

    Args:
        media_dir: Directory containing audio files
        model_name: Whisper model size (tiny/base/small/medium/large)
        extensions: Audio file extensions to look for

    Returns:
        List of dicts with: audio_file, transcript, language, duration_sec
    """
    voice_dir = os.path.join(media_dir, "voice")
    if not os.path.isdir(voice_dir):
        return []

    model = _load_whisper(model_name)
    if model is None:
        return []

    # Write transcripts to a separate directory outside raw/ to honor
    # the "raw data is sacred" design rule (never modify files in raw/)
    transcript_dir = os.path.join(
        os.path.expanduser("~/LifeData/media"), "transcripts"
    )
    os.makedirs(transcript_dir, exist_ok=True)

    results = []
    for filename in sorted(os.listdir(voice_dir)):
        _, ext = os.path.splitext(filename)
        if ext.lower() not in extensions:
            continue

        audio_path = os.path.join(voice_dir, filename)
        txt_name = os.path.splitext(filename)[0] + ".txt"
        txt_path = os.path.join(transcript_dir, txt_name)

        # Also check the old location (voice_dir) for backwards compat
        old_txt_path = os.path.join(voice_dir, txt_name)
        if os.path.exists(txt_path) or os.path.exists(old_txt_path):
            continue  # Already transcribed

        try:
            print(f"  Transcribing: {filename}...")
            result = model.transcribe(audio_path)
            transcript = result.get("text", "").strip()

            if transcript:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(transcript)

                results.append({
                    "audio_file": audio_path,
                    "transcript": transcript,
                    "language": result.get("language", "en"),
                    "duration_sec": result.get("duration", 0),
                })
                print(f"    → {len(transcript)} chars, {result.get('language', '?')}")
            else:
                print("    → (empty transcript)")

        except Exception as e:
            print(f"    → ERROR: {e}")

    return results


def is_whisper_available() -> bool:
    """Check if Whisper can be imported."""
    try:
        import whisper  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> None:
    """CLI entry point for standalone transcription."""
    media_dir = os.path.expanduser("~/LifeData/raw/LifeData/logs/media")
    model = "base"

    if len(sys.argv) > 1:
        media_dir = sys.argv[1]
    if len(sys.argv) > 2:
        model = sys.argv[2]

    if not is_whisper_available():
        print("Whisper is not installed.")
        print("Install with: pip install openai-whisper")
        print("Then re-run this script.")
        sys.exit(1)

    print(f"Transcribing audio in: {media_dir}")
    print(f"Model: {model}")
    results = transcribe_pending(media_dir, model)
    print(f"\nTranscribed {len(results)} file(s)")


if __name__ == "__main__":
    main()
