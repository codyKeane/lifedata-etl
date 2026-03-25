"""LifeData V4 — Meta Module"""

from __future__ import annotations

from typing import Any

from modules.meta.module import MetaModule


def create_module(config: dict[str, Any] | None = None) -> MetaModule:
    """Factory function called by the orchestrator."""
    return MetaModule(config)
