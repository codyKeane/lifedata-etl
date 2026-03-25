"""LifeData V4 — Oracle Module (XI)"""

from __future__ import annotations

from typing import Any

from modules.oracle.module import OracleModule


def create_module(config: dict[str, Any] | None = None) -> OracleModule:
    """Factory function called by the orchestrator."""
    return OracleModule(config)
