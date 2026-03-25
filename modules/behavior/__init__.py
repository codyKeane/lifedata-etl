"""LifeData V4 — Behavior Module (OMICRON)"""

from __future__ import annotations

from typing import Any

from modules.behavior.module import BehaviorModule


def create_module(config: dict[str, Any] | None = None) -> BehaviorModule:
    """Factory function called by the orchestrator."""
    return BehaviorModule(config)
