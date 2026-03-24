"""LifeData V4 — Cognition Module (NU)"""

from modules.cognition.module import CognitionModule


def create_module(config: dict | None = None) -> CognitionModule:
    """Factory function called by the orchestrator."""
    return CognitionModule(config)
