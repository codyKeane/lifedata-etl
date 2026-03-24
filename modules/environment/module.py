"""
LifeData V4 — Environment Module
modules/environment/module.py

Handles environmental data: hourly snapshots, geofence location, astronomy.
"""

import os

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files
from modules.environment.parsers import PARSER_REGISTRY

log = get_logger("lifedata.environment")


class EnvironmentModule(ModuleInterface):
    """Environment module — parses environmental sensor and location data."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "environment"

    @property
    def display_name(self) -> str:
        return "Environment Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "environment.hourly",
            "environment.location",
            "environment.astro",
            "environment.pressure",
            "environment.light",
            "environment.emf",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find environment, location, and astro CSVs in the raw data tree."""
        files = []
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "environment"),
            os.path.join(raw_base, "logs", "environment"),
            os.path.join(raw_base, "location"),
            os.path.join(raw_base, "logs", "location"),
            os.path.join(raw_base, "astro"),
            os.path.join(raw_base, "logs", "astro"),
            os.path.join(raw_base, "logs", "sensors"),  # Sensor Logger summaries
        ]

        for search_dir in search_dirs:
            expanded = os.path.expanduser(search_dir)
            if not os.path.isdir(expanded):
                continue
            for csv_file in glob_files(expanded, "*.csv", recursive=True):
                basename = os.path.basename(csv_file)
                if any(basename.startswith(prefix) for prefix in PARSER_REGISTRY):
                    files.append(csv_file)

        seen = set()
        unique = []
        for f in files:
            real = os.path.realpath(f)
            if real not in seen:
                seen.add(real)
                unique.append(f)

        return unique

    def parse(self, file_path: str) -> list[Event]:
        """Parse a single environment CSV file."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for environment file: {basename}")
        return []


def create_module(config: dict | None = None) -> EnvironmentModule:
    """Factory function called by the orchestrator."""
    return EnvironmentModule(config)
