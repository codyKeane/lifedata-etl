"""
LifeData V4 — Metrics System Tests
tests/test_metrics.py

Tests for:
  1. ETLMetrics / ModuleMetrics dataclass serialization roundtrip
  2. Orchestrator integration producing valid structured metrics
  3. _print_status formatting and warning thresholds
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.metrics import ETLMetrics, ModuleMetrics, read_last_n_metrics, write_metrics

# ══════════════════════════════════════════════════════════════
# 1. DATACLASS SERIALIZATION
# ══════════════════════════════════════════════════════════════


class TestModuleMetrics:

    def test_defaults(self):
        mm = ModuleMetrics(module_id="device", status="success")
        assert mm.files_discovered == 0
        assert mm.events_ingested == 0
        assert mm.error is None

    def test_to_dict_roundtrip(self):
        mm = ModuleMetrics(
            module_id="device",
            status="failed",
            files_discovered=10,
            files_parsed=8,
            files_quarantined=1,
            events_parsed=100,
            events_ingested=95,
            events_skipped=5,
            duration_sec=1.23,
            error="timeout",
        )
        d = mm.to_dict()
        mm2 = ModuleMetrics.from_dict(d)
        assert mm2.module_id == "device"
        assert mm2.status == "failed"
        assert mm2.files_quarantined == 1
        assert mm2.events_ingested == 95
        assert mm2.error == "timeout"
        assert mm2.duration_sec == 1.23

    def test_from_dict_ignores_extra_keys(self):
        d = {"module_id": "x", "status": "success", "future_field": 99}
        mm = ModuleMetrics.from_dict(d)
        assert mm.module_id == "x"


class TestETLMetrics:

    def test_defaults(self):
        m = ETLMetrics()
        assert len(m.run_id) == 36  # UUID
        assert m.total_events_ingested == 0
        assert m.modules == {}
        assert m.config_validation_warnings == []

    def test_to_json_roundtrip(self):
        mm = ModuleMetrics(module_id="mind", status="success", events_ingested=42)
        m = ETLMetrics(
            started_utc="2026-03-24T00:00:00+00:00",
            finished_utc="2026-03-24T00:01:00+00:00",
            duration_sec=60.0,
            total_events_parsed=50,
            total_events_ingested=42,
            total_events_skipped=8,
            total_files_discovered=5,
            total_files_quarantined=1,
            modules={"mind": mm},
            db_size_mb=123.4,
            disk_free_gb=50.0,
            config_validation_warnings=["missing API key"],
        )
        j = m.to_json()
        m2 = ETLMetrics.from_json(j)
        assert m2.run_id == m.run_id
        assert m2.total_events_ingested == 42
        assert m2.modules["mind"].events_ingested == 42
        assert m2.db_size_mb == 123.4
        assert m2.config_validation_warnings == ["missing API key"]

    def test_failed_modules(self):
        m = ETLMetrics(modules={
            "device": ModuleMetrics(module_id="device", status="success"),
            "env": ModuleMetrics(module_id="env", status="failed", error="boom"),
            "mind": ModuleMetrics(module_id="mind", status="success"),
        })
        assert m.failed_modules() == ["env"]

    def test_from_dict_ignores_extra_keys(self):
        d = {"run_id": "abc", "future_field": True, "modules": {}}
        m = ETLMetrics.from_dict(d)
        assert m.run_id == "abc"


class TestWriteAndRead:

    def test_write_then_read(self, tmp_path):
        path = str(tmp_path / "metrics.jsonl")
        m1 = ETLMetrics(total_events_ingested=10)
        m2 = ETLMetrics(total_events_ingested=20)
        write_metrics(m1, path=path)
        write_metrics(m2, path=path)

        entries = read_last_n_metrics(7, path=path)
        assert len(entries) == 2
        assert entries[0].total_events_ingested == 10
        assert entries[1].total_events_ingested == 20

    def test_read_empty_file(self, tmp_path):
        path = str(tmp_path / "metrics.jsonl")
        open(path, "w").close()
        assert read_last_n_metrics(7, path=path) == []

    def test_read_missing_file(self, tmp_path):
        assert read_last_n_metrics(7, path=str(tmp_path / "nope.jsonl")) == []

    def test_read_last_n_limits(self, tmp_path):
        path = str(tmp_path / "metrics.jsonl")
        for i in range(10):
            write_metrics(ETLMetrics(total_events_ingested=i), path=path)
        entries = read_last_n_metrics(3, path=path)
        assert len(entries) == 3
        assert entries[0].total_events_ingested == 7
        assert entries[2].total_events_ingested == 9

    def test_corrupt_lines_skipped(self, tmp_path):
        path = str(tmp_path / "metrics.jsonl")
        write_metrics(ETLMetrics(total_events_ingested=1), path=path)
        with open(path, "a") as f:
            f.write("NOT JSON\n")
        write_metrics(ETLMetrics(total_events_ingested=3), path=path)
        entries = read_last_n_metrics(7, path=path)
        assert len(entries) == 2
        assert entries[0].total_events_ingested == 1
        assert entries[1].total_events_ingested == 3


# ══════════════════════════════════════════════════════════════
# 2. ORCHESTRATOR INTEGRATION
# ══════════════════════════════════════════════════════════════


class TestOrchestratorMetrics:
    """Verify the orchestrator produces valid structured ETLMetrics."""

    def test_run_produces_metrics_in_summary(self, tmp_path):
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )

        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)

        assert "metrics" in summary
        m = summary["metrics"]
        assert isinstance(m, ETLMetrics)
        assert len(m.run_id) == 36
        assert m.started_utc != ""
        assert m.finished_utc != ""
        assert m.duration_sec >= 0
        assert m.total_events_ingested > 0
        assert m.total_files_discovered > 0
        orch.db.close()

    def test_per_module_metrics_populated(self, tmp_path):
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _populate_environment_csvs,
            _write_config_yaml,
        )

        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device", "environment"]
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        summary = orch.run(report=False)
        m = summary["metrics"]

        assert "device" in m.modules
        assert "environment" in m.modules

        dev = m.modules["device"]
        assert dev.status == "success"
        assert dev.files_discovered > 0
        assert dev.files_parsed > 0
        assert dev.events_parsed > 0
        assert dev.events_ingested > 0
        assert dev.duration_sec >= 0

        env = m.modules["environment"]
        assert env.status == "success"
        orch.db.close()

    def test_failed_module_recorded(self, tmp_path):
        from unittest.mock import patch

        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _populate_environment_csvs,
            _write_config_yaml,
        )

        config_path, env_path = _write_config_yaml(
            tmp_path, allowlist=["device", "environment"]
        )
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)
        _populate_environment_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        with patch(
            "modules.environment.module.EnvironmentModule.discover_files",
            side_effect=RuntimeError("boom"),
        ):
            summary = orch.run(report=False)

        m = summary["metrics"]
        assert m.modules["environment"].status == "failed"
        assert "boom" in m.modules["environment"].error
        assert m.modules["device"].status == "success"
        orch.db.close()

    def test_metrics_written_to_file(self, tmp_path):
        from tests.test_etl_integration import (
            _make_orchestrator,
            _populate_device_csvs,
            _write_config_yaml,
        )

        config_path, env_path = _write_config_yaml(tmp_path, allowlist=["device"])
        raw_dir = str(tmp_path / "raw" / "LifeData")
        _populate_device_csvs(raw_dir)

        orch = _make_orchestrator(config_path, env_path)
        orch.run(report=False)

        # The metrics file is written to ~/LifeData/logs/metrics.jsonl
        metrics_path = os.path.expanduser("~/LifeData/logs/metrics.jsonl")
        assert os.path.exists(metrics_path)

        entries = read_last_n_metrics(1, path=metrics_path)
        assert len(entries) >= 1
        latest = entries[-1]
        assert latest.total_events_ingested > 0
        orch.db.close()


# ══════════════════════════════════════════════════════════════
# 3. --STATUS FORMATTING AND WARNINGS
# ══════════════════════════════════════════════════════════════


class TestPrintStatus:

    def _write_entries(self, path, entries):
        """Write a list of ETLMetrics to a file."""
        for e in entries:
            write_metrics(e, path=path)

    def _run_status(self, tmp_path, entries, capsys):
        """Helper: write entries to a temp metrics file, run _print_status
        with METRICS_PATH monkeypatched, return captured stdout."""
        path = str(tmp_path / "metrics.jsonl")
        if entries is not None:
            self._write_entries(path, entries)

        import core.metrics as cm
        original = cm.METRICS_PATH
        cm.METRICS_PATH = path if entries is not None else str(tmp_path / "nope.jsonl")
        try:
            import run_etl
            result = run_etl._print_status()
        finally:
            cm.METRICS_PATH = original
        return capsys.readouterr().out, result

    def test_no_metrics_file(self, tmp_path, capsys):
        """When no metrics file exists, print helpful message."""
        out, result = self._run_status(tmp_path, None, capsys)
        assert "No metrics found" in out
        assert result == 0

    def test_table_format_with_entries(self, tmp_path, capsys):
        """Status table should show date, duration, ingested, failed, db size, disk free."""
        entries = [
            ETLMetrics(
                started_utc="2026-03-24T23:55:00+00:00",
                finished_utc="2026-03-24T23:56:00+00:00",
                duration_sec=60.0,
                total_events_ingested=150,
                db_size_mb=50.0,
                disk_free_gb=100.0,
                modules={
                    "device": ModuleMetrics(module_id="device", status="success", events_ingested=100),
                    "mind": ModuleMetrics(module_id="mind", status="success", events_ingested=50),
                },
            ),
        ]
        out, result = self._run_status(tmp_path, entries, capsys)
        assert result == 0
        assert "150" in out
        assert "60.0s" in out
        assert "50.0MB" in out
        assert "100.0GB" in out

    def test_warning_module_failures_last_3(self, tmp_path, capsys):
        """Warn if any module failed in the last 3 runs."""
        entries = [
            ETLMetrics(
                started_utc=f"2026-03-{20+i}T23:55:00+00:00",
                total_events_ingested=100,
                db_size_mb=50.0,
                disk_free_gb=100.0,
                modules={
                    "device": ModuleMetrics(module_id="device", status="success"),
                    "env": ModuleMetrics(
                        module_id="env",
                        status="failed" if i == 2 else "success",
                        error="crash" if i == 2 else None,
                    ),
                },
            )
            for i in range(4)
        ]
        out, _ = self._run_status(tmp_path, entries, capsys)
        assert "Module failure" in out
        assert "env" in out

    def test_warning_db_over_5gb(self, tmp_path, capsys):
        """Warn if database is over 5 GB."""
        entries = [
            ETLMetrics(
                started_utc="2026-03-24T23:55:00+00:00",
                total_events_ingested=100,
                db_size_mb=6000.0,
                disk_free_gb=100.0,
            ),
        ]
        out, _ = self._run_status(tmp_path, entries, capsys)
        assert "5 GB" in out or "5.9 GB" in out

    def test_warning_disk_under_20gb(self, tmp_path, capsys):
        """Warn if disk free < 20 GB."""
        entries = [
            ETLMetrics(
                started_utc="2026-03-24T23:55:00+00:00",
                total_events_ingested=100,
                db_size_mb=50.0,
                disk_free_gb=15.3,
            ),
        ]
        out, _ = self._run_status(tmp_path, entries, capsys)
        assert "15.3 GB" in out
        assert "20 GB" in out

    def test_warning_events_drop_50_pct(self, tmp_path, capsys):
        """Warn if events ingested dropped >50% vs historical average."""
        entries = [
            ETLMetrics(
                started_utc=f"2026-03-{20+i}T23:55:00+00:00",
                total_events_ingested=200,
                db_size_mb=50.0,
                disk_free_gb=100.0,
            )
            for i in range(5)
        ]
        entries.append(
            ETLMetrics(
                started_utc="2026-03-26T23:55:00+00:00",
                total_events_ingested=50,
                db_size_mb=50.0,
                disk_free_gb=100.0,
            )
        )
        out, _ = self._run_status(tmp_path, entries, capsys)
        assert "dropped" in out.lower() or "drop" in out.lower()
        assert "75%" in out

    def test_no_warnings_when_healthy(self, tmp_path, capsys):
        """No warnings when everything is healthy."""
        entries = [
            ETLMetrics(
                started_utc=f"2026-03-{20+i}T23:55:00+00:00",
                total_events_ingested=200,
                db_size_mb=50.0,
                disk_free_gb=100.0,
                modules={
                    "device": ModuleMetrics(module_id="device", status="success"),
                },
            )
            for i in range(4)
        ]
        out, _ = self._run_status(tmp_path, entries, capsys)
        assert "!!" not in out
