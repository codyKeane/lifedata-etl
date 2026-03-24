"""LifeData V4 — Oracle Module (XI)"""

from modules.oracle.module import OracleModule


def create_module(config: dict | None = None) -> OracleModule:
    """Factory function called by the orchestrator."""
    return OracleModule(config)
