"""LifeData V4 — Body Module"""

from __future__ import annotations

from typing import Any

from modules.body.module import BodyModule


def create_module(config: dict[str, Any] | None = None) -> BodyModule:
    """Factory function called by the orchestrator."""
    return BodyModule(config)
