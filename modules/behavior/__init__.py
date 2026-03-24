"""LifeData V4 — Behavior Module (OMICRON)"""

from modules.behavior.module import BehaviorModule


def create_module(config: dict | None = None) -> BehaviorModule:
    """Factory function called by the orchestrator."""
    return BehaviorModule(config)
