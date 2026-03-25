"""
LifeData V4 — ETL Metrics
core/metrics.py

Typed dataclasses for structured ETL run telemetry. Each run produces
one ETLMetrics instance that is serialized as a single JSON line in
~/LifeData/logs/metrics.jsonl.
"""

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ModuleMetrics:
    """Per-module telemetry collected during a single ETL run."""

    module_id: str
    status: str  # "success" | "failed" | "skipped"
    files_discovered: int = 0
    files_parsed: int = 0
    files_quarantined: int = 0
    events_parsed: int = 0
    events_ingested: int = 0
    events_skipped: int = 0
    duration_sec: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModuleMetrics":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ETLMetrics:
    """Top-level telemetry for a complete ETL run."""

    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_utc: str = ""
    finished_utc: str = ""
    duration_sec: float = 0.0
    total_events_parsed: int = 0
    total_events_ingested: int = 0
    total_events_skipped: int = 0
    total_files_discovered: int = 0
    total_files_quarantined: int = 0
    modules: dict[str, ModuleMetrics] = field(default_factory=dict)
    db_size_mb: float = 0.0
    disk_free_gb: float = 0.0
    config_validation_warnings: list[str] = field(default_factory=list)

    def failed_modules(self) -> list[str]:
        """Return module IDs that have status 'failed'."""
        return [m.module_id for m in self.modules.values() if m.status == "failed"]

    def to_dict(self) -> dict:
        d = asdict(self)
        # asdict converts ModuleMetrics to plain dicts already
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: dict) -> "ETLMetrics":
        modules_raw = d.pop("modules", {})
        modules = {
            k: ModuleMetrics.from_dict(v) if isinstance(v, dict) else v
            for k, v in modules_raw.items()
        }
        safe = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        safe["modules"] = modules
        return cls(**safe)

    @classmethod
    def from_json(cls, line: str) -> "ETLMetrics":
        return cls.from_dict(json.loads(line))


METRICS_PATH = os.path.expanduser("~/LifeData/logs/metrics.jsonl")


def write_metrics(metrics: ETLMetrics, path: str | None = None) -> None:
    """Append a single ETLMetrics entry as one JSON line."""
    if path is None:
        path = METRICS_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(metrics.to_json() + "\n")


def read_last_n_metrics(n: int = 7, path: str | None = None) -> list[ETLMetrics]:
    """Read the last N ETLMetrics entries from the metrics file."""
    if path is None:
        path = METRICS_PATH
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return []
            chunk = min(size, 262144)  # 256KB — plenty for 7 entries
            f.seek(size - chunk)
            raw_lines = f.read().decode("utf-8").strip().splitlines()
            raw_lines = raw_lines[-n:]
    except FileNotFoundError:
        return []

    entries = []
    for line in raw_lines:
        try:
            entries.append(ETLMetrics.from_json(line))
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
    return entries
