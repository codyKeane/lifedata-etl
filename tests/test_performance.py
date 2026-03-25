"""
LifeData V4 — Performance Benchmark Tests
tests/test_performance.py

Establishes performance baselines for parsing, ingestion, and queries.
Marked with @pytest.mark.slow — only run via:  make test-perf

After all tests complete, writes results to docs/PERFORMANCE_BASELINE.md.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import Database
from core.event import Event
from core.utils import safe_json

# ── Shared state for the final report ────────────────────────

_RESULTS: list[dict[str, Any]] = []

PROJECT_ROOT = Path(__file__).parent.parent
BASELINE_PATH = PROJECT_ROOT / "docs" / "PERFORMANCE_BASELINE.md"

# Base timestamp: 2026-01-01T00:00:00Z
_BASE_UTC = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _record(name: str, dataset: str, duration: float, throughput: str) -> None:
    """Append a result for the final report."""
    _RESULTS.append({
        "test": name,
        "dataset": dataset,
        "duration_sec": round(duration, 3),
        "throughput": throughput,
    })


def _make_event(
    i: int,
    source_module: str = "device.screen",
    event_type: str = "screen_on",
    value_numeric: float | None = None,
    value_text: str | None = None,
    day_offset: int = 0,
) -> Event:
    """Generate a unique Event deterministically from index i."""
    ts = _BASE_UTC + timedelta(days=day_offset, seconds=i * 15)
    ts_utc = ts.isoformat()
    ts_local = (ts - timedelta(hours=5)).isoformat()
    return Event(
        timestamp_utc=ts_utc,
        timestamp_local=ts_local,
        timezone_offset="-0500",
        source_module=source_module,
        event_type=event_type,
        value_numeric=value_numeric if value_numeric is not None else float(i % 100),
        value_text=value_text,
        tags=f"bench,{source_module.split('.')[0]}",
        confidence=1.0,
        parser_version="1.0.0",
    )


# ══════════════════════════════════════════════════════════════
# 1. PARSE LARGE CSV
# ══════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_parse_large_csv(tmp_path: Path) -> None:
    """Generate 100K-row screen CSV, parse with device parser, assert <10s."""
    from modules.device.parsers import parse_screen

    csv_path = tmp_path / "screen_bench.csv"
    rows: list[str] = []
    base_epoch = 1742475600  # 2026-03-20 08:00 CDT
    for i in range(100_000):
        epoch = base_epoch + i * 15
        state = "on" if i % 2 == 0 else "off"
        batt = 90 - (i % 50)
        h = 8 + (i * 15 // 3600) % 16
        m = (i * 15 // 60) % 60
        rows.append(f"{epoch},3-20-26,{h}:{m:02d},-0500,{state},{batt}")

    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    start = time.perf_counter()
    events = parse_screen(str(csv_path))
    elapsed = time.perf_counter() - start

    throughput = len(events) / elapsed if elapsed > 0 else 0
    print(f"\n  parse_screen: {len(events)} events from 100K rows in {elapsed:.2f}s "
          f"({throughput:,.0f} rows/sec)")

    _record("test_parse_large_csv", "100,000 rows", elapsed,
            f"{throughput:,.0f} rows/sec")

    assert len(events) == 100_000, f"Expected 100K events, got {len(events)}"
    assert elapsed < 10, f"Parsing took {elapsed:.1f}s (limit: 10s)"


# ══════════════════════════════════════════════════════════════
# 2. INSERT 10K EVENTS
# ══════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_insert_10k_events(tmp_path: Path) -> None:
    """Generate 10K events, insert via insert_events_for_module, assert <5s."""
    db = Database(str(tmp_path / "bench.db"))
    db.ensure_schema()

    events = [_make_event(i) for i in range(10_000)]

    start = time.perf_counter()
    inserted, skipped = db.insert_events_for_module("benchmark", events)
    elapsed = time.perf_counter() - start

    throughput = inserted / elapsed if elapsed > 0 else 0
    print(f"\n  insert: {inserted} events in {elapsed:.2f}s "
          f"({throughput:,.0f} events/sec)")

    _record("test_insert_10k_events", "10,000 events", elapsed,
            f"{throughput:,.0f} events/sec")

    assert inserted == 10_000
    assert skipped == 0
    assert elapsed < 5, f"Insertion took {elapsed:.1f}s (limit: 5s)"
    db.close()


# ══════════════════════════════════════════════════════════════
# 3. DAILY SUMMARY QUERY AT SCALE
# ══════════════════════════════════════════════════════════════


def _build_scale_db(db_path: str) -> Database:
    """Build a 500K-event database spanning 180 days across 5 modules.

    Used by both test_daily_summary_query_at_scale and
    test_correlation_query_at_scale.
    """
    db = Database(db_path)
    db.ensure_schema()

    modules = [
        ("mind.mood", "check_in"),
        ("device.screen", "screen_on"),
        ("environment.hourly", "snapshot"),
        ("body.caffeine", "intake"),
        ("environment.geomagnetic", "kp_index"),
    ]

    # 500K events / 5 modules = 100K per module, spread over 180 days
    # ~556 events per module per day
    batch: list[Event] = []
    events_per_module = 100_000
    batch_size = 5000

    for mod_idx, (source_module, event_type) in enumerate(modules):
        for i in range(events_per_module):
            day = i * 180 // events_per_module
            batch.append(_make_event(
                i + mod_idx * events_per_module,
                source_module=source_module,
                event_type=event_type,
                day_offset=day,
            ))
            if len(batch) >= batch_size:
                db.insert_events_for_module("benchmark", batch)
                batch.clear()
    if batch:
        db.insert_events_for_module("benchmark", batch)
        batch.clear()

    # Verify count
    count = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert count == 500_000, f"Expected 500K events, got {count}"
    return db


@pytest.mark.slow
def test_daily_summary_query_at_scale(tmp_path: Path) -> None:
    """Insert 500K events over 180 days, time a daily aggregation, assert <2s."""
    db = _build_scale_db(str(tmp_path / "scale.db"))

    # Pick a date in the middle of the range
    target_date = (_BASE_UTC + timedelta(days=90)).strftime("%Y-%m-%d")

    start = time.perf_counter()

    # Simulate the daily summary computation the device module does:
    # aggregate per source_module for one day
    rows = db.conn.execute(
        """
        SELECT source_module,
               COUNT(*) as cnt,
               AVG(value_numeric) as avg_val,
               MIN(value_numeric) as min_val,
               MAX(value_numeric) as max_val
        FROM events
        WHERE date(timestamp_local) = ?
          AND value_numeric IS NOT NULL
        GROUP BY source_module
        """,
        [target_date],
    ).fetchall()

    elapsed = time.perf_counter() - start

    print(f"\n  daily_summary: {len(rows)} module groups for {target_date} "
          f"in {elapsed:.3f}s (500K events in DB)")

    _record("test_daily_summary_query_at_scale",
            "500,000 events / 180 days", elapsed,
            f"{len(rows)} groups in {elapsed:.3f}s")

    assert len(rows) > 0, "No rows returned for target date"
    assert elapsed < 2, f"Query took {elapsed:.1f}s (limit: 2s)"
    db.close()


# ══════════════════════════════════════════════════════════════
# 4. CORRELATION QUERY AT SCALE
# ══════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_correlation_query_at_scale(tmp_path: Path) -> None:
    """Using 500K events, time a cross-correlation query, assert <3s."""
    db = _build_scale_db(str(tmp_path / "scale_corr.db"))

    start = time.perf_counter()

    # Simulate what Correlator._get_daily_series does for two metrics,
    # then align and correlate — this is the hot path.
    cutoff = (_BASE_UTC + timedelta(days=150)).isoformat()

    series_a_rows = db.conn.execute(
        """
        SELECT date(timestamp_local) as day, AVG(value_numeric) as avg_val
        FROM events
        WHERE source_module = 'mind.mood'
          AND value_numeric IS NOT NULL
          AND confidence >= 0.5
          AND timestamp_utc >= ?
        GROUP BY day ORDER BY day
        """,
        [cutoff],
    ).fetchall()

    series_b_rows = db.conn.execute(
        """
        SELECT date(timestamp_local) as day, AVG(value_numeric) as avg_val
        FROM events
        WHERE source_module = 'environment.geomagnetic'
          AND value_numeric IS NOT NULL
          AND confidence >= 0.5
          AND timestamp_utc >= ?
        GROUP BY day ORDER BY day
        """,
        [cutoff],
    ).fetchall()

    # Align by date
    b_map = {r[0]: r[1] for r in series_b_rows}
    aligned = [(r[0], r[1], b_map[r[0]]) for r in series_a_rows if r[0] in b_map]

    elapsed = time.perf_counter() - start

    # Print query plan for the correlation JOIN
    plan = db.conn.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT date(timestamp_local) as day, AVG(value_numeric) as avg_val
        FROM events
        WHERE source_module = 'mind.mood'
          AND value_numeric IS NOT NULL
          AND confidence >= 0.5
          AND timestamp_utc >= ?
        GROUP BY day
        """,
        [cutoff],
    ).fetchall()
    plan_lines = [f"    {dict(r)}" for r in plan]

    print(f"\n  correlation: {len(aligned)} aligned days in {elapsed:.3f}s "
          f"(500K events)\n  Query plan:\n" + "\n".join(plan_lines))

    _record("test_correlation_query_at_scale",
            "500,000 events / 30 days", elapsed,
            f"{len(aligned)} aligned days in {elapsed:.3f}s")

    assert len(aligned) > 0, "No aligned data points"
    assert elapsed < 3, f"Correlation took {elapsed:.1f}s (limit: 3s)"
    db.close()


# ══════════════════════════════════════════════════════════════
# 5. FTS SEARCH AT SCALE
# ══════════════════════════════════════════════════════════════


@pytest.mark.slow
def test_fts_search_at_scale(tmp_path: Path) -> None:
    """Insert 50K events with value_text, time FTS search, assert <1s."""
    db = Database(str(tmp_path / "fts_bench.db"))
    db.ensure_schema()

    # Check FTS5 availability
    has_fts = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'events_fts'"
    ).fetchone()
    if not has_fts:
        pytest.skip("FTS5 not available in this SQLite build")

    # Generate 50K events with varied text content
    words = [
        "battery", "screen", "charging", "bluetooth", "notification",
        "morning", "evening", "weather", "sunny", "cloudy",
        "sleep", "caffeine", "exercise", "meditation", "reading",
        "work", "meeting", "commute", "lunch", "dinner",
    ]
    rare_word = "serendipitous"  # uncommon term we'll search for

    batch: list[Event] = []
    batch_size = 5000
    for i in range(50_000):
        # Every 500th event gets the rare word
        if i % 500 == 0:
            text = f"A {rare_word} encounter during {words[i % len(words)]} activity"
        else:
            w1 = words[i % len(words)]
            w2 = words[(i * 7) % len(words)]
            text = f"{w1} event during {w2} period, value={i % 100}"

        batch.append(_make_event(
            i,
            source_module="mind.journal",
            event_type="entry",
            value_text=text,
            day_offset=i // 278,  # ~180 days
        ))
        if len(batch) >= batch_size:
            db.insert_events_for_module("benchmark", batch)
            batch.clear()
    if batch:
        db.insert_events_for_module("benchmark", batch)

    total = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert total == 50_000

    start = time.perf_counter()
    results = db.conn.execute(
        "SELECT event_id FROM events_fts WHERE events_fts MATCH ?",
        [rare_word],
    ).fetchall()
    elapsed = time.perf_counter() - start

    expected_matches = 50_000 // 500  # = 100
    print(f"\n  FTS search: {len(results)} matches for '{rare_word}' "
          f"in {elapsed:.4f}s (50K events)")

    _record("test_fts_search_at_scale", "50,000 events", elapsed,
            f"{len(results)} matches in {elapsed:.4f}s")

    assert len(results) == expected_matches, (
        f"Expected {expected_matches} FTS matches, got {len(results)}"
    )
    assert elapsed < 1, f"FTS search took {elapsed:.2f}s (limit: 1s)"
    db.close()


# ══════════════════════════════════════════════════════════════
# BASELINE REPORT GENERATOR
# ══════════════════════════════════════════════════════════════


def _get_hardware_info() -> dict[str, str]:
    """Collect hardware info from /proc and system tools."""
    info: dict[str, str] = {}

    # CPU
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = line.split(":", 1)[1].strip()
                    break
    except OSError:
        info["cpu"] = "unknown"

    # RAM
    try:
        result = subprocess.run(
            ["free", "-h", "--si"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if line.startswith("Mem:"):
                info["ram"] = line.split()[1]
                break
    except (OSError, subprocess.TimeoutExpired):
        info["ram"] = "unknown"

    # Disk type
    try:
        result = subprocess.run(
            ["lsblk", "-d", "-o", "NAME,ROTA,SIZE,MODEL", "--noheadings"],
            capture_output=True, text=True, timeout=5,
        )
        disks: list[str] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 3:
                rota = "HDD" if parts[1] == "1" else "SSD/NVMe"
                model = " ".join(parts[3:]) if len(parts) > 3 else ""
                disks.append(f"{parts[0]} ({rota}, {parts[2]}) {model}".strip())
        info["disk"] = "; ".join(disks) if disks else "unknown"
    except (OSError, subprocess.TimeoutExpired):
        info["disk"] = "unknown"

    return info


@pytest.fixture(autouse=True, scope="session")
def write_baseline_report(request: pytest.FixtureRequest) -> Any:  # noqa: ANN401
    """After all tests in this session complete, write PERFORMANCE_BASELINE.md."""
    yield  # run all tests first

    if not _RESULTS:
        return

    hw = _get_hardware_info()
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content (if any) to append
    existing = ""
    if BASELINE_PATH.exists():
        existing = BASELINE_PATH.read_text(encoding="utf-8")

    # Build the new section
    lines = [
        f"## Baseline — {date_str}\n",
        f"**Hardware:** {hw.get('cpu', '?')} | RAM: {hw.get('ram', '?')} "
        f"| Disk: {hw.get('disk', '?')}\n",
        "",
        "| Test | Dataset | Duration (s) | Throughput |",
        "|------|---------|-------------|------------|",
    ]
    for r in _RESULTS:
        lines.append(
            f"| {r['test']} | {r['dataset']} | "
            f"{r['duration_sec']:.3f} | {r['throughput']} |"
        )
    lines.append("")

    new_section = "\n".join(lines)

    if existing:
        # Prepend new baseline after header
        if existing.startswith("# "):
            header_end = existing.index("\n") + 1
            content = existing[:header_end] + "\n" + new_section + "\n---\n\n" + existing[header_end:]
        else:
            content = new_section + "\n---\n\n" + existing
    else:
        content = (
            "# LifeData V4 — Performance Baselines\n\n"
            "Benchmarks run on synthetic data. Compare future runs against these\n"
            "numbers to detect performance regressions.\n\n"
            + new_section
        )

    BASELINE_PATH.write_text(content, encoding="utf-8")
    print(f"\n  Baseline written to {BASELINE_PATH}")
