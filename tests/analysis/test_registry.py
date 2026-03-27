"""
Tests for analysis/registry.py — Metrics Registry.
"""

from analysis.registry import MetricsRegistry


class _MockModule:
    """Minimal mock implementing get_metrics_manifest()."""

    def __init__(self, metrics):
        self._metrics = metrics

    def get_metrics_manifest(self):
        return {"metrics": self._metrics}


def _make_metric(name, **kwargs):
    base = {
        "name": name,
        "display_name": name,
        "unit": "count",
        "aggregate": "AVG",
        "trend_eligible": False,
        "anomaly_eligible": False,
    }
    base.update(kwargs)
    return base


class TestMetricsRegistry:
    def test_loads_metrics_from_modules(self):
        mod = _MockModule([_make_metric("test.a"), _make_metric("test.b")])
        reg = MetricsRegistry(modules=[mod])
        assert len(reg.get_all_metrics()) == 2

    def test_get_metric_by_name(self):
        mod = _MockModule([_make_metric("mind.mood", display_name="Mood")])
        reg = MetricsRegistry(modules=[mod])
        m = reg.get_metric("mind.mood")
        assert m is not None
        assert m["display_name"] == "Mood"

    def test_get_metric_missing(self):
        reg = MetricsRegistry(modules=[])
        assert reg.get_metric("nonexistent") is None

    def test_anomaly_eligible_filter(self):
        mod = _MockModule([
            _make_metric("a", anomaly_eligible=True),
            _make_metric("b", anomaly_eligible=False),
            _make_metric("c", anomaly_eligible=True),
        ])
        reg = MetricsRegistry(modules=[mod])
        eligible = reg.get_anomaly_eligible()
        assert len(eligible) == 2
        names = {m["name"] for m in eligible}
        assert names == {"a", "c"}

    def test_trend_metrics_from_manifest(self):
        mod = _MockModule([
            _make_metric("a", trend_eligible=True),
            _make_metric("b", trend_eligible=False),
        ])
        reg = MetricsRegistry(modules=[mod])
        trends = reg.get_trend_metrics()
        assert len(trends) == 1
        assert trends[0]["name"] == "a"

    def test_trend_metrics_from_config_override(self):
        mod = _MockModule([
            _make_metric("a", trend_eligible=True),
            _make_metric("b", trend_eligible=False),
        ])
        config = {
            "lifedata": {
                "analysis": {
                    "report": {
                        "trend_metrics": ["b"],
                    }
                }
            }
        }
        reg = MetricsRegistry(modules=[mod], config=config)
        trends = reg.get_trend_metrics()
        assert len(trends) == 1
        assert trends[0]["name"] == "b"

    def test_get_patterns_from_config(self):
        config = {
            "lifedata": {
                "analysis": {
                    "patterns": [
                        {"name": "p1", "enabled": True, "conditions": []},
                        {"name": "p2", "enabled": False, "conditions": []},
                        {"name": "p3", "conditions": []},
                    ]
                }
            }
        }
        reg = MetricsRegistry(config=config)
        patterns = reg.get_patterns()
        assert len(patterns) == 2
        names = {p["name"] for p in patterns}
        assert names == {"p1", "p3"}

    def test_get_hypotheses_from_config(self):
        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {"name": "h1", "metric_a": "a", "metric_b": "b", "direction": "positive", "enabled": True},
                        {"name": "h2", "metric_a": "c", "metric_b": "d", "direction": "negative", "enabled": False},
                    ]
                }
            }
        }
        reg = MetricsRegistry(config=config)
        hyps = reg.get_hypotheses()
        assert len(hyps) == 1
        assert hyps[0]["name"] == "h1"

    def test_get_report_sections(self):
        config = {
            "lifedata": {
                "analysis": {
                    "report": {
                        "sections": [
                            {"module": "device", "enabled": True},
                            {"module": "body", "enabled": False},
                            {"module": "mind", "enabled": True},
                        ]
                    }
                }
            }
        }
        reg = MetricsRegistry(config=config)
        sections = reg.get_report_sections()
        assert len(sections) == 2
        assert sections[0]["module"] == "device"
        assert sections[1]["module"] == "mind"

    def test_empty_config(self):
        reg = MetricsRegistry()
        assert reg.get_all_metrics() == []
        assert reg.get_patterns() == []
        assert reg.get_hypotheses() == []
        assert reg.get_report_sections() == []

    def test_evaluate_condition(self):
        assert MetricsRegistry.evaluate_condition("<", 5, 10) is True
        assert MetricsRegistry.evaluate_condition("<", 15, 10) is False
        assert MetricsRegistry.evaluate_condition(">", 15, 10) is True
        assert MetricsRegistry.evaluate_condition(">=", 10, 10) is True
        assert MetricsRegistry.evaluate_condition("==", 10, 10) is True
        assert MetricsRegistry.evaluate_condition("!=", 5, 10) is True

    def test_multiple_modules(self):
        mod1 = _MockModule([_make_metric("device.battery")])
        mod2 = _MockModule([_make_metric("mind.mood")])
        reg = MetricsRegistry(modules=[mod1, mod2])
        assert len(reg.get_all_metrics()) == 2
        assert reg.get_metric("device.battery") is not None
        assert reg.get_metric("mind.mood") is not None


class TestLoadHypothesesFromConfig:
    """Test hypothesis loading from config via hypothesis.py."""

    def test_load_from_config(self):
        from analysis.hypothesis import load_hypotheses

        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {
                            "name": "Test hypothesis",
                            "metric_a": "test.a",
                            "metric_b": "test.b",
                            "direction": "positive",
                            "threshold": 0.01,
                            "enabled": True,
                        },
                    ]
                }
            }
        }
        hyps = load_hypotheses(config)
        assert len(hyps) == 1
        assert hyps[0].name == "Test hypothesis"
        assert hyps[0].direction == "positive"
        assert hyps[0].threshold == 0.01

    def test_disabled_hypothesis_skipped(self):
        from analysis.hypothesis import load_hypotheses

        config = {
            "lifedata": {
                "analysis": {
                    "hypotheses": [
                        {"name": "h1", "metric_a": "a", "metric_b": "b", "direction": "any", "enabled": True},
                        {"name": "h2", "metric_a": "c", "metric_b": "d", "direction": "any", "enabled": False},
                    ]
                }
            }
        }
        hyps = load_hypotheses(config)
        assert len(hyps) == 1
        assert hyps[0].name == "h1"

    def test_no_config_returns_empty(self):
        from analysis.hypothesis import load_hypotheses

        hyps = load_hypotheses(None)
        assert hyps == []

    def test_empty_hypotheses_returns_empty(self):
        from analysis.hypothesis import load_hypotheses

        config = {"lifedata": {"analysis": {"hypotheses": []}}}
        hyps = load_hypotheses(config)
        assert hyps == []


class TestConfigDrivenPatterns:
    """Test that AnomalyDetector.check_config_patterns works."""

    def test_config_pattern_fires(self, db):
        from analysis.anomaly import AnomalyDetector
        from core.event import Event

        # Insert data matching a simple pattern
        e1 = Event(
            timestamp_utc="2026-03-24T12:00:00+00:00",
            timestamp_local="2026-03-24T07:00:00-05:00",
            timezone_offset="-0500",
            source_module="test.metric_a",
            event_type="measurement",
            value_numeric=5.0,
        )
        db.insert_events_for_module("test", [e1])

        config = {
            "lifedata": {
                "analysis": {
                    "patterns": [
                        {
                            "name": "test_pattern",
                            "enabled": True,
                            "description_template": "Test pattern fired",
                            "conditions": [
                                {"metric": "test.metric_a", "operator": "<", "threshold": 10},
                            ],
                        },
                    ]
                }
            }
        }

        detector = AnomalyDetector(db, config=config)
        patterns = detector.check_config_patterns("2026-03-24")
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "test_pattern"

    def test_config_pattern_not_fired(self, db):
        from analysis.anomaly import AnomalyDetector
        from core.event import Event

        e1 = Event(
            timestamp_utc="2026-03-24T12:00:00+00:00",
            timestamp_local="2026-03-24T07:00:00-05:00",
            timezone_offset="-0500",
            source_module="test.metric_a",
            event_type="measurement",
            value_numeric=15.0,
        )
        db.insert_events_for_module("test", [e1])

        config = {
            "lifedata": {
                "analysis": {
                    "patterns": [
                        {
                            "name": "test_pattern",
                            "enabled": True,
                            "conditions": [
                                {"metric": "test.metric_a", "operator": "<", "threshold": 10},
                            ],
                        },
                    ]
                }
            }
        }

        detector = AnomalyDetector(db, config=config)
        patterns = detector.check_config_patterns("2026-03-24")
        assert len(patterns) == 0

    def test_disabled_config_pattern_skipped(self, db):
        from analysis.anomaly import AnomalyDetector

        config = {
            "lifedata": {
                "analysis": {
                    "patterns": [
                        {"name": "disabled_pattern", "enabled": False, "conditions": []},
                    ]
                }
            }
        }

        detector = AnomalyDetector(db, config=config)
        patterns = detector.check_config_patterns("2026-03-24")
        assert len(patterns) == 0

    def test_check_pattern_anomalies_uses_config_when_present(self, db):
        from analysis.anomaly import AnomalyDetector
        from core.event import Event

        e1 = Event(
            timestamp_utc="2026-03-24T12:00:00+00:00",
            timestamp_local="2026-03-24T07:00:00-05:00",
            timezone_offset="-0500",
            source_module="test.x",
            event_type="val",
            value_numeric=1.0,
        )
        db.insert_events_for_module("test", [e1])

        config = {
            "lifedata": {
                "analysis": {
                    "patterns": [
                        {
                            "name": "config_pattern",
                            "enabled": True,
                            "description_template": "From config",
                            "conditions": [
                                {"metric": "test.x", "operator": ">", "threshold": 0},
                            ],
                        },
                    ]
                }
            }
        }

        detector = AnomalyDetector(db, config=config)
        # check_pattern_anomalies should delegate to config patterns
        patterns = detector.check_pattern_anomalies("2026-03-24")
        assert len(patterns) == 1
        assert patterns[0]["pattern"] == "config_pattern"
