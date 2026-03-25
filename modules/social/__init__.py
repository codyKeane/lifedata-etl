"""LifeData V4 — Social Module"""

from __future__ import annotations

from typing import Any

from modules.social.module import SocialModule


def create_module(config: dict[str, Any] | None = None) -> SocialModule:
    """Factory function called by the orchestrator."""
    return SocialModule(config)
