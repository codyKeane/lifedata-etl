"""
LifeData V4 — Device Module
modules/device/module.py

Handles device-level events from Tasker:
  battery, screen on/off, charging, bluetooth

Implements the ModuleInterface contract.
"""

import os

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files
from modules.device.parsers import PARSER_REGISTRY

log = get_logger("lifedata.device")


class DeviceModule(ModuleInterface):
    """Device module — parses phone hardware and OS events."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "device"

    @property
    def display_name(self) -> str:
        return "Device Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "device.battery",
            "device.screen",
            "device.charging",
            "device.bluetooth",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all device CSV files in the raw data tree.

        Searches recursively for files matching any known parser prefix
        within the device/ and logs/device/ subdirectories.
        """
        files = []

        # Search in all common locations:
        # - raw_base/device/
        # - raw_base/logs/device/
        # - raw_base directly (if files are at root)
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "device"),
            os.path.join(raw_base, "logs", "device"),
        ]

        for search_dir in search_dirs:
            expanded = os.path.expanduser(search_dir)
            if not os.path.isdir(expanded):
                continue
            for csv_file in glob_files(expanded, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                # Only include files matching a known parser prefix
                if any(basename.startswith(prefix) for prefix in PARSER_REGISTRY):
                    files.append(csv_file)

        # Deduplicate (same file found via different search paths)
        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single device CSV file using the appropriate parser."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(
                        f"Parsed {len(events)} events from {basename}"
                    )
                return events

        log.warning(f"No parser found for device file: {basename}")
        return []

    def post_ingest(self, db) -> None:
        """Compute derived device metrics after ingestion."""
        # Future: compute screen_time_minutes, unlock_count, etc.
        pass


def create_module(config: dict | None = None) -> DeviceModule:
    """Factory function called by the orchestrator."""
    return DeviceModule(config)
