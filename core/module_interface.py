"""
LifeData V4 — Module Interface Contract
core/module_interface.py

Abstract base class that every LifeData module must implement.
This is the contract between modules and the orchestrator.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.database import Database

from core.event import Event


class ModuleInterface(ABC):
    """Every LifeData module implements this contract.

    Modules are sovereign: they own their collection, parsing, and schema.
    No module imports or depends on another module.
    """

    # Subclasses set self._config in __init__; declare here for type safety.
    _config: dict[str, Any]

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

    def post_ingest(  # noqa: B027
        self, db: Database, affected_dates: set[str] | None = None,
    ) -> None:
        """Optional hook: runs after all events are ingested.

        Use for materialized views, daily summaries, derived metrics, etc.

        Args:
            db: Database instance for queries and writes.
            affected_dates: Set of YYYY-MM-DD date strings that had events
                ingested this run. Modules should limit recomputation to
                these dates when possible. If None, recompute all.
        """

    def get_daily_summary(self, db: Database, date_str: str) -> dict[str, Any] | None:
        """Optional: return a dict of daily metrics for this module."""
        return None

    def get_metrics_manifest(self) -> dict[str, Any]:
        """Declare this module's metrics for the analysis layer.

        Returns a dict with:
            metrics: list of metric declarations, each containing:
                name: str — source_module value (e.g., "device.battery")
                display_name: str — human-readable label
                unit: str — unit of measurement
                aggregate: str — default SQL aggregate (AVG, SUM, COUNT)
                event_type: str | None — optional event_type filter
                trend_eligible: bool — show in report trends
                anomaly_eligible: bool — include in z-score detection
        """
        return {"metrics": []}

    def is_metric_enabled(self, metric_name: str) -> bool:
        """Check if a metric is enabled (not in the disabled_metrics list).

        Supports both exact match ("device.battery") and prefix match
        ("device.derived" matches "device.derived:screen_time_minutes").

        Args:
            metric_name: The metric name to check, using the same naming
                convention as get_metrics_manifest() (e.g., "device.battery",
                "device.derived:screen_time_minutes").
        """
        disabled = self._config.get("disabled_metrics", [])
        if not disabled:
            return True
        for pattern in disabled:
            if metric_name == pattern:
                return False
            # Allow disabling all derived metrics with "module.derived"
            if ":" in metric_name and metric_name.split(":")[0] == pattern:
                return False
        return True

    def filter_events(self, events: list[Event]) -> list[Event]:
        """Remove events whose source_module matches a disabled metric.

        Called by the orchestrator after parse() returns, before insertion.
        """
        disabled = self._config.get("disabled_metrics", [])
        if not disabled:
            return events
        return [e for e in events if self.is_metric_enabled(e.source_module)]

    def schema_migrations(self) -> list[str]:
        """Return ordered SQL DDL statements for module-specific tables.

        Each entry is a version. The framework tracks which versions have been
        applied and only runs new ones. Append new migrations to the end —
        never modify or reorder existing entries.
        """
        return []
