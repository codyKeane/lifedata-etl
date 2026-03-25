"""LifeData V4 — World Module"""

from __future__ import annotations

from typing import Any

from modules.world.module import WorldModule


def create_module(config: dict[str, Any] | None = None) -> WorldModule:
    """Factory function called by the orchestrator."""
    return WorldModule(config)
