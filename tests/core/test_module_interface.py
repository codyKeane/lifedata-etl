"""
Tests for ModuleInterface base class — metric filtering and enablement.

Validates that:
- is_metric_enabled() respects disabled_metrics config
- filter_events() removes events matching disabled metrics
- Prefix matching works (disabling "X.derived" disables "X.derived:foo")
- Empty disabled_metrics means everything is enabled (backward compat)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Any

from core.event import Event
from core.module_interface import ModuleInterface


# ── Concrete test implementation ────────────────────────────────


class _StubModule(ModuleInterface):
    """Minimal concrete module for testing base class methods."""

    def __init__(self, config: dict[str, Any] | None = None):
        self._config = config or {}

    @property
    def module_id(self) -> str:
        return "stub"

    @property
    def display_name(self) -> str:
        return "Stub Module"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def source_types(self) -> list[str]:
        return ["stub.raw", "stub.derived"]

    def discover_files(self, raw_base: str) -> list[str]:
        return []

    def parse(self, file_path: str) -> list[Event]:
        return []

    def get_metrics_manifest(self) -> dict[str, Any]:
        return {
            "metrics": [
                {"name": "stub.raw", "display_name": "Raw", "unit": "count",
                 "aggregate": "COUNT", "event_type": None,
                 "trend_eligible": True, "anomaly_eligible": True},
                {"name": "stub.derived:alpha", "display_name": "Alpha", "unit": "score",
                 "aggregate": "AVG", "event_type": "alpha",
                 "trend_eligible": True, "anomaly_eligible": True},
                {"name": "stub.derived:beta", "display_name": "Beta", "unit": "score",
                 "aggregate": "AVG", "event_type": "beta",
                 "trend_eligible": False, "anomaly_eligible": True},
            ],
        }


def _make_event(source_module: str, event_type: str = "test") -> Event:
    return Event(
        timestamp_utc="2026-03-20T13:00:00+00:00",
        timestamp_local="2026-03-20T08:00:00-05:00",
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=1.0,
        confidence=1.0,
    )


# ── is_metric_enabled() tests ──────────────────────────────────


class TestIsMetricEnabled:

    def test_all_enabled_by_default(self):
        """Empty disabled_metrics means everything is enabled."""
        mod = _StubModule(config={})
        assert mod.is_metric_enabled("stub.raw") is True
        assert mod.is_metric_enabled("stub.derived:alpha") is True
        assert mod.is_metric_enabled("stub.derived:beta") is True

    def test_exact_match_disables(self):
        """Exact metric name in disabled_metrics disables it."""
        mod = _StubModule(config={"disabled_metrics": ["stub.raw"]})
        assert mod.is_metric_enabled("stub.raw") is False
        assert mod.is_metric_enabled("stub.derived:alpha") is True

    def test_prefix_match_disables_derived(self):
        """Disabling 'stub.derived' disables all stub.derived:* metrics."""
        mod = _StubModule(config={"disabled_metrics": ["stub.derived"]})
        assert mod.is_metric_enabled("stub.derived:alpha") is False
        assert mod.is_metric_enabled("stub.derived:beta") is False
        assert mod.is_metric_enabled("stub.raw") is True

    def test_specific_derived_disable(self):
        """Disabling one derived metric doesn't affect siblings."""
        mod = _StubModule(config={"disabled_metrics": ["stub.derived:alpha"]})
        assert mod.is_metric_enabled("stub.derived:alpha") is False
        assert mod.is_metric_enabled("stub.derived:beta") is True

    def test_multiple_disables(self):
        """Multiple entries in disabled_metrics all apply."""
        mod = _StubModule(config={
            "disabled_metrics": ["stub.raw", "stub.derived:beta"]
        })
        assert mod.is_metric_enabled("stub.raw") is False
        assert mod.is_metric_enabled("stub.derived:alpha") is True
        assert mod.is_metric_enabled("stub.derived:beta") is False

    def test_no_config_key_means_enabled(self):
        """Missing disabled_metrics key entirely means everything enabled."""
        mod = _StubModule(config={"enabled": True})
        assert mod.is_metric_enabled("stub.raw") is True
        assert mod.is_metric_enabled("stub.derived:alpha") is True

    def test_empty_list_means_enabled(self):
        """Explicit empty disabled_metrics means everything enabled."""
        mod = _StubModule(config={"disabled_metrics": []})
        assert mod.is_metric_enabled("stub.raw") is True


# ── filter_events() tests ──────────────────────────────────────


class TestFilterEvents:

    def test_no_filtering_by_default(self):
        """Empty disabled list returns all events unchanged."""
        mod = _StubModule(config={})
        events = [
            _make_event("stub.raw"),
            _make_event("stub.derived", "alpha"),
        ]
        result = mod.filter_events(events)
        assert len(result) == 2

    def test_filters_disabled_source_module(self):
        """Events with disabled source_module are removed."""
        mod = _StubModule(config={"disabled_metrics": ["stub.raw"]})
        events = [
            _make_event("stub.raw"),
            _make_event("stub.derived", "alpha"),
        ]
        result = mod.filter_events(events)
        assert len(result) == 1
        assert result[0].source_module == "stub.derived"

    def test_prefix_filtering(self):
        """Disabling 'stub.derived' filters all stub.derived events."""
        mod = _StubModule(config={"disabled_metrics": ["stub.derived"]})
        events = [
            _make_event("stub.raw"),
            _make_event("stub.derived", "alpha"),
            _make_event("stub.derived", "beta"),
        ]
        result = mod.filter_events(events)
        assert len(result) == 1
        assert result[0].source_module == "stub.raw"

    def test_empty_input(self):
        """Empty events list returns empty list."""
        mod = _StubModule(config={"disabled_metrics": ["stub.raw"]})
        assert mod.filter_events([]) == []

    def test_all_disabled(self):
        """Disabling all metrics returns empty list."""
        mod = _StubModule(config={
            "disabled_metrics": ["stub.raw", "stub.derived"]
        })
        events = [
            _make_event("stub.raw"),
            _make_event("stub.derived", "alpha"),
        ]
        result = mod.filter_events(events)
        assert len(result) == 0
