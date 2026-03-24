"""
LifeData V4 — Module Interface Contract
core/module_interface.py

Abstract base class that every LifeData module must implement.
This is the contract between modules and the orchestrator.
"""

from abc import ABC, abstractmethod
from typing import Optional

from core.event import Event


class ModuleInterface(ABC):
    """Every LifeData module implements this contract.

    Modules are sovereign: they own their collection, parsing, and schema.
    No module imports or depends on another module.
    """

    @property
    @abstractmethod
    def module_id(self) -> str:
        """Unique dot-notation ID. e.g., 'device', 'body', 'world'."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string."""
        ...

    @property
    @abstractmethod
    def source_types(self) -> list[str]:
        """List of source_module values this module emits.

        e.g., ['device.screen', 'device.battery', 'device.bluetooth']
        """
        ...

    @abstractmethod
    def discover_files(self, raw_base: str) -> list[str]:
        """Return list of file paths this module wants to parse.

        Called by orchestrator with the raw data directory.
        """
        ...

    @abstractmethod
    def parse(self, file_path: str) -> list[Event]:
        """Parse a single file into a list of Events.

        Must handle malformed data gracefully (skip bad rows, log warnings).
        Never crash the module on bad input.
        """
        ...

    def post_ingest(self, db) -> None:
        """Optional hook: runs after all events are ingested.

        Use for materialized views, daily summaries, derived metrics, etc.
        """
        pass

    def get_daily_summary(self, db, date_str: str) -> Optional[dict]:
        """Optional: return a dict of daily metrics for this module."""
        return None

    def schema_migrations(self) -> list[str]:
        """Optional: return SQL statements for module-specific tables."""
        return []
