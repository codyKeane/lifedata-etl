"""LifeData V4 — Environment Module"""

from __future__ import annotations

from typing import Any

from modules.environment.module import EnvironmentModule


def create_module(config: dict[str, Any] | None = None) -> EnvironmentModule:
    """Factory function called by the orchestrator."""
    return EnvironmentModule(config)
