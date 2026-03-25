"""LifeData V4 — Media Module"""

from __future__ import annotations

from typing import Any

from modules.media.module import MediaModule


def create_module(config: dict[str, Any] | None = None) -> MediaModule:
    """Factory function called by the orchestrator."""
    return MediaModule(config)
