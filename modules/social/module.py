"""
LifeData V4 — Social Module
modules/social/module.py

Handles communication and social interaction data: notifications, calls,
SMS, app usage, and WiFi connectivity.
"""

import os

from core.event import Event
from core.logger import get_logger
from core.module_interface import ModuleInterface
from core.utils import glob_files
from modules.social.parsers import PARSER_REGISTRY

log = get_logger("lifedata.social")


class SocialModule(ModuleInterface):
    """Social module — parses communication and app usage data."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "social"

    @property
    def display_name(self) -> str:
        return "Social Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return [
            "social.notification",
            "social.call",
            "social.sms",
            "social.app_usage",
            "social.wifi",
        ]

    def discover_files(self, raw_base: str) -> list[str]:
        """Find all social/communication CSV files in the raw data tree."""
        files = []
        search_dirs = [
            raw_base,
            os.path.join(raw_base, "communication"),
            os.path.join(raw_base, "logs", "communication"),
            os.path.join(raw_base, "apps"),
            os.path.join(raw_base, "logs", "apps"),
            os.path.join(raw_base, "network"),
            os.path.join(raw_base, "logs", "network"),
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
        """Parse a single social CSV file."""
        basename = os.path.basename(file_path)

        for prefix, parser_fn in PARSER_REGISTRY.items():
            if basename.startswith(prefix):
                events = parser_fn(file_path)
                if events:
                    log.info(f"Parsed {len(events)} events from {basename}")
                return events

        log.warning(f"No parser found for social file: {basename}")
        return []


def create_module(config: dict | None = None) -> SocialModule:
    """Factory function called by the orchestrator."""
    return SocialModule(config)
