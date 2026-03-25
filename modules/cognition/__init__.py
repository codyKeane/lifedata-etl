"""LifeData V4 — Cognition Module (NU)"""

from __future__ import annotations

from typing import Any

from modules.cognition.module import CognitionModule


def create_module(config: dict[str, Any] | None = None) -> CognitionModule:
    """Factory function called by the orchestrator."""
    return CognitionModule(config)
