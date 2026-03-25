"""LifeData V4 — Device Module"""

from __future__ import annotations

from typing import Any

from modules.device.module import DeviceModule


def create_module(config: dict[str, Any] | None = None) -> DeviceModule:
    """Factory function called by the orchestrator."""
    return DeviceModule(config)
