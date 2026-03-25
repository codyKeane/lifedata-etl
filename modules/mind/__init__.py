"""LifeData V4 — Mind Module"""

from __future__ import annotations

from typing import Any

from modules.mind.module import MindModule


def create_module(config: dict[str, Any] | None = None) -> MindModule:
    """Factory function called by the orchestrator."""
    return MindModule(config)
