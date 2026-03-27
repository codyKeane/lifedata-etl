# LifeData V4 — Architecture Analysis & Action Plan

**Date:** 2026-03-26
**Analyst:** Claude Opus 4.6
**Branch:** dev2
**Baseline:** 1291 tests passing, 84% coverage, mypy strict clean, 32 lint warnings

---

## 1. EXECUTIVE SUMMARY

LifeData V4 is a well-engineered personal behavioral data observatory. The codebase demonstrates strong architectural discipline: sovereign module boundaries, idempotent ingestion via deterministic SHA-256 hashing, SAVEPOINT-isolated writes, config-driven analysis, and defense-in-depth security. The project has completed the vast majority of its planned objectives (per CONDENSED_GOALS.md) and is production-operational.

This analysis identifies **17 actionable items** across four priority tiers. No critical blockers exist — the system works. The items below are improvements to robustness, coverage, consistency, and maintainability.

---

## 2. ARCHITECTURE ASSESSMENT

### 2.1 What's Working Well

| Area | Assessment |
|------|-----------|
| **Module sovereignty** | Clean separation. No cross-module imports. Each module owns parsing, schema, derived metrics. |
| **Event model** | Universal `Event` dataclass with cached deterministic IDs. Deduplication via `INSERT OR REPLACE` on `raw_source_id`. Size limits prevent DB bloat. |
| **Database layer** | WAL mode, tuned PRAGMAs, SAVEPOINT isolation per module, `executemany()` batch inserts (58K events/sec). Read-only `execute()` enforced. |
| **Config validation** | 6-step Pydantic validation with semantic checks (path existence, timezone validity, allowlist vs. directory). Fails fast with all errors at once. |
| **Security posture** | Fail-closed module allowlist, path traversal prevention, PII HMAC hashing, log sanitization, file permission checks, Syncthing relay prohibition. |
| **Per-metric configurability** | Every derived metric guarded by `is_metric_enabled()`. Users can disable individual metrics without code changes. |
| **Analysis layer** | Config-driven anomaly patterns (9), hypotheses (10), report sections, trend metrics. Z-score detection against rolling baselines. |
| **Test coverage** | 1291 tests at 84%. All 11 modules have parser + post_ingest tests. Analysis layer fully tested. Scripts tested. |
| **Idempotency** | Deterministic event IDs + `INSERT OR REPLACE` = re-running ETL produces identical results. Derived metrics use fixed timestamps. |
| **Operational tooling** | Structured logging (JSON + human), metrics.jsonl per run, DB backup/prune, log rotation, health status command, event tracing. |

### 2.2 Architecture Diagram (Data Flow)

```
Phone (Tasker CSVs) ──► Syncthing ──► raw/LifeData/logs/
API Scripts ──────────────────────────► raw/api/

         ┌──────────────────────────────────┐
         │         ORCHESTRATOR              │
         │  config validation ──► module     │
         │  discovery ──► file validation    │
         │  ──► parse ──► filter_events      │
         │  ──► INSERT (SAVEPOINT) ──►       │
         │  post_ingest ──► daily_summary    │
         └──────────┬───────────────────────┘
                    │
         ┌──────────▼───────────────────────┐
         │         SQLITE (WAL)              │
         │  events │ modules │ media         │
         │  daily_summaries │ correlations   │
         │  events_fts │ schema_versions     │
         └──────────┬───────────────────────┘
                    │
         ┌──────────▼───────────────────────┐
         │         ANALYSIS                  │
         │  correlator ──► hypothesis        │
         │  anomaly detector ──► reports     │
         │  metrics registry                 │
         └──────────────────────────────────┘
```

---

## 3. FINDINGS

### 3.1 Code Quality Issues

#### F-01: SQL Aggregate Function Injection Vector in reports.py
**Severity:** Medium
**Location:** `analysis/reports.py:225-248`

The `agg_fn` variable from `_resolve_trend_metrics()` is interpolated directly into SQL via f-string:
```python
SELECT date(timestamp_local) as d, {agg_fn}(value_numeric)
```
While `agg_fn` comes from config (not user HTTP input), a malicious or typo'd config entry could inject SQL. The `anomaly.py` module correctly uses a `_AGG_SQL` allowlist dict — `reports.py` should do the same.

#### F-02: Version String Inconsistency
**Severity:** Low
**Location:** `pyproject.toml:3`, `config.yaml:9`, `analysis/reports.py:19`

Three different version strings:
- `pyproject.toml`: `"4.0.0"`
- `config.yaml`: `"4.0"`
- `reports.py _REPORT_VERSION`: `"4.3.0"`

These should either be synchronized or the report version should be derived from pyproject.toml.

#### F-03: Hardcoded Hypothesis List is Redundant
**Severity:** Low
**Location:** `analysis/hypothesis.py:98-163`

The `HYPOTHESES` list (lines 98–163) duplicates the config.yaml `hypotheses` section. The `load_hypotheses()` function falls back to this list when config is absent. Since config.yaml is always present in production, this hardcoded list is dead code that will drift from config over time. Consider removing it and making config the sole source of truth.

#### F-04: 32 Pre-existing Lint Warnings
**Severity:** Low

Breakdown: 29 E501 (line length), 2 UP038 (isinstance union syntax), 1 SIM105 (contextlib.suppress). These are style issues documented as pre-existing in CONDENSED_GOALS.md.

### 3.2 Coverage Gaps

Per actual coverage run (2026-03-26):

| File | Coverage | Gap Lines | Priority |
|------|----------|-----------|----------|
| `scripts/compute_planetary_hours.py` | 55% | 33-35, 125-176 | Medium |
| `modules/media/parsers.py` | 61% | 40-42, 81-82, 112-201, 272-274, 301-410 | Medium |
| `modules/meta/quality.py` | 69% | 89-156, 167, 211-236 | Low |
| `core/orchestrator.py` | 73% | 91-175, 228-304, 340-398, 544-628 | Medium |
| `modules/oracle/module.py` | 80% | 55-93, 133-209, 635-671 | Low |
| `modules/behavior/module.py` | 80% | 147-247, 1141-1282 | Low |
| `core/database.py` | 82% | 182-190, 413-453, 593-617 | Low |

### 3.3 Design Observations

#### F-05: Correlator Code Duplication
**Location:** `analysis/correlator.py:82-141` vs `143-188`

`correlate()` and `_correlate_from_series()` share ~50 identical lines of alignment, statistical computation, and result formatting. Noted as ARCH-3 in CONDENSED_GOALS (deferred). A private `_compute_from_aligned()` helper would eliminate the duplication cleanly.

#### F-06: Period Report Date Generation Uses Hardcoded 30-Day Sequence
**Location:** `analysis/reports.py:459-479`

The weekly/monthly report generates date sequences using a UNION ALL of literal integers (0-29). This works but is fragile — it silently caps at 30 days. A `recursive CTE` or Python `date_range` would be more robust for arbitrary periods.

#### F-07: Database Connection Not Thread-Safe
**Location:** `core/database.py:154`

The `Database` class stores a single `self.conn`. SQLite connections are not thread-safe by default. This is fine for the current nightly-batch model but would be a blocker for any future concurrent/streaming architecture. Noted as SCALE-3 in CONDENSED_GOALS (correctly deferred).

#### F-08: CI Matrix Tests Python 3.14 (Pre-release)
**Location:** `.github/workflows/ci.yml:14`

Python 3.14 is in development. This is forward-looking but may cause spurious CI failures from upstream changes. Consider using `3.14-dev` or `3.14.0-alpha.*` to make the intent explicit.

### 3.4 Documentation vs. Reality

| Claim (CONDENSED_GOALS) | Verified? | Notes |
|--------------------------|-----------|-------|
| 1291 tests passing | **Yes** | `1291 passed, 11 deselected in 3.92s` |
| 84% coverage | **Yes** | `TOTAL 6940 1088 84%` |
| mypy strict clean | **Yes** | `Success: no issues found in 12 source files` |
| 0 DeprecationWarnings | **Yes** | No warnings in test output |
| 29 lint errors (style) | **No** | Actually 32 lint errors (3 new since doc update) |
| All security findings resolved | **Yes** | Verified: path traversal, PII, allowlist, FTS5 trigger, permissions |
| Per-metric guards on all post_ingest | **Yes** | Every `is_metric_enabled()` call confirmed per module |

---

## 4. ACTION PLAN

### Tier 1: Quick Wins (< 30 min each)

| # | Action | File(s) | Rationale |
|---|--------|---------|-----------|
| **A-01** | Add `_AGG_SQL` allowlist validation for `agg_fn` in reports.py trend queries | `analysis/reports.py` | Closes SQL injection vector F-01. Copy pattern from `anomaly.py:53-54`. |
| **A-02** | Fix lint warnings (32 → 0) | Various | 29 E501 (break long lines), 2 UP038 (modernize isinstance), 1 SIM105 (use contextlib.suppress). All mechanical. |
| **A-03** | Update CONDENSED_GOALS lint count from 29 to current | `CONDENSED_GOALS.md` | Documentation accuracy (F-04). |
| **A-04** | Synchronize version strings or add `__version__` to single source | `pyproject.toml`, `analysis/reports.py` | Use `importlib.metadata.version("lifedata")` in reports.py instead of hardcoded string (F-02). |

### Tier 2: Coverage & Robustness (1-3 hours each)

| # | Action | File(s) | Rationale |
|---|--------|---------|-----------|
| **A-05** | Increase `orchestrator.py` coverage from 73% to 80%+ | `tests/core/test_orchestrator.py` | Exercise security check paths (disk encryption, .env permissions), dry-run report generation, WAL checkpoint failure handling, quarantine collection. |
| **A-06** | Increase `media/parsers.py` coverage from 61% to 80%+ | `tests/modules/media/test_parsers.py` | Uncovered: EXIF extraction paths, video thumbnail generation, edge cases in photo/voice/video parsing. |
| **A-07** | Increase `scripts/compute_planetary_hours.py` coverage from 55% to 80%+ | `tests/scripts/test_compute_planetary_hours.py` | Uncovered: main execution path, file I/O, edge cases around sunrise/sunset at extreme latitudes. |
| **A-08** | Increase `meta/quality.py` coverage from 69% to 80%+ | `tests/modules/meta/test_quality.py` | Uncovered: quality check failure paths, validation edge cases. |
| **A-09** | Add period report date-sequence robustness (F-06) | `analysis/reports.py` | Replace hardcoded UNION ALL with a Python date range or recursive CTE to support arbitrary period lengths. |

### Tier 3: Structural Improvements (2-4 hours each)

| # | Action | File(s) | Rationale |
|---|--------|---------|-----------|
| **A-10** | Deduplicate correlator methods (F-05) | `analysis/correlator.py` | Extract shared correlation logic from `correlate()` and `_correlate_from_series()` into `_compute_from_aligned()`. ~50 lines eliminated. |
| **A-11** | Remove hardcoded HYPOTHESES list (F-03) | `analysis/hypothesis.py` | Make config.yaml the single source of truth. Keep `load_hypotheses()` but have it raise if config is None (production always has config). |
| **A-12** | Strengthen CI matrix for Python 3.14 (F-08) | `.github/workflows/ci.yml` | Use `allow-prereleases: true` with `3.14` to make intent explicit and handle failures gracefully. |
| **A-13** | Add integration test for full ETL → report pipeline | `tests/` | End-to-end test: config load → module discovery → parse → insert → post_ingest → daily_summary → report generation → verify output contains expected sections. |

### Tier 4: Strategic / Deferred (Aligned with CONDENSED_GOALS)

| # | Action | Rationale | When |
|---|--------|-----------|------|
| **A-14** | Pagination in `query_events()` (cursor already implemented) | Dataset at ~13K events; needed at 500K+. Cursor pagination is already wired. | When dataset exceeds 100K events |
| **A-15** | Connection pooling / concurrent writes | Current WAL batch model handles nightly runs. Needed only for streaming. | If architecture shifts to real-time |
| **A-16** | Bonferroni correction for multiple hypothesis testing | 10 hypotheses is small. If count grows past 20, false-positive rate matters. | When hypothesis count > 20 |
| **A-17** | Configurable app classification keywords (social module) | Hardcoded productive/distraction lists work for personal use. | If multi-user or app categories change frequently |

---

## 5. RECOMMENDED EXECUTION ORDER

```
Phase 1 (Immediate — tighten the ship)
  A-01  SQL injection fix in reports.py         [30 min]
  A-02  Fix all 32 lint warnings                [45 min]
  A-04  Version string consolidation            [15 min]
  A-03  Update CONDENSED_GOALS accuracy         [5 min]

Phase 2 (Next session — coverage push to 87%+)
  A-05  orchestrator.py  73% → 80%+            [2 hr]
  A-06  media/parsers.py  61% → 80%+           [2 hr]
  A-07  compute_planetary_hours.py  55% → 80%+ [1 hr]
  A-08  meta/quality.py  69% → 80%+            [1 hr]

Phase 3 (Polish — structural cleanup)
  A-10  Correlator deduplication               [1 hr]
  A-11  Remove hardcoded HYPOTHESES            [30 min]
  A-09  Period report date robustness          [1 hr]
  A-12  CI matrix hardening                    [30 min]
  A-13  E2E integration test                   [2 hr]
```

---

## 6. METRICS AFTER FULL EXECUTION

| Metric | Current | Target |
|--------|---------|--------|
| Tests | 1291 | ~1400+ |
| Coverage | 84% | 87%+ |
| Lint errors | 32 | 0 |
| mypy strict | Clean | Clean |
| Version consistency | 3 different strings | Single source |
| SQL injection vectors | 1 (reports.py) | 0 |

---

## 7. IMPLEMENTATION LOG

### Phase 1 — Completed (2026-03-26)

All Phase 1 items are done. 1291 tests passing, 0 lint errors in source code.

**A-01: SQL aggregate injection fix** ✅
- Added `_AGG_SQL` allowlist dict to `analysis/reports.py` (module-level)
- Both `generate_daily_report()` and `_generate_period_report()` now validate `agg_fn` through the allowlist before SQL interpolation
- Mirrors the same pattern already used in `analysis/anomaly.py:54`

**A-02: Fix all 32 lint warnings → 0** ✅
- 19 source files modified across `core/`, `modules/`, `analysis/`
- Categories fixed: E501 (line length), SIM105 (contextlib.suppress), UP038 (isinstance union syntax), SIM102 (nested if merge), SIM103 (inline return), B027 (empty ABC method)
- Also fixed 4 pre-existing test failures in `tests/analysis/test_anomaly.py` caused by hardcoded dates falling outside the 14-day rolling lookback window. Replaced all hardcoded date references with relative `_today()` / `_days_ago()` helpers so tests remain stable over time.
- `ruff check analysis/ core/ modules/ scripts/` → All checks passed

**A-04: Version string synchronization** ✅
- `analysis/reports.py`: Replaced hardcoded `_REPORT_VERSION = "4.3.0"` with `_read_version()` that reads from `pyproject.toml` at import time — single source of truth
- `config.yaml`: Updated `version: "4.0"` → `version: "4.0.0"` (full semver)
- `pyproject.toml`: Already `"4.0.0"` — no change needed

**A-03: Update CONDENSED_GOALS lint count** ✅
- Updated lint error count from "29 pre-existing (style preferences)" to "0 in source code (all 32 warnings fixed)"

### Phase 2 — Completed (2026-03-26)

All Phase 2 items are done. 1384 tests passing (up from 1291), 0 lint errors.

**A-05: Increase orchestrator.py coverage 73% → 87%** ✅
- Added 32 new tests in `tests/core/test_orchestrator.py` across 6 test classes
- Covered: startup security checks (.env permissions, .stfolder detection, disk encryption via LUKS/fscrypt/no-encryption), module discovery (allowlist, disabled modules, disabled_metrics validation), run() dry-run mode, report generation, WAL checkpoint failure, quarantine collection, post_ingest failure isolation, metrics write failure, _persist_correlations

**A-06: Increase media/parsers.py coverage 61% → 98%** ✅
- Added 31 new tests in `tests/modules/media/test_parsers.py` across 9 test classes
- Covered: `_safe_media_path` traversal blocking, `_read_transcript` (voice/dream/empty/unsafe/OSError), `_extract_exif` (no Pillow, GPS+metadata, exception), `_convert_gps` (N/S/W/None/invalid), `_get_video_info` (ffprobe success/failure/timeout/JSON error), VADER lazy loading, photo EXIF integration, parse error catch blocks for all 3 parsers

**A-07: Increase compute_planetary_hours.py coverage 55% → 95%** ✅
- Added 12 new tests in `tests/scripts/test_compute_planetary_hours.py` across 4 test classes
- Covered: `load_config()`, `main()` (output file creation, zero-coordinate warning, default coordinates), all 7 day rulers, high latitude (Oslo summer), southern hemisphere (Sydney winter)

**A-08: Increase meta/quality.py coverage 69% → 100%** ✅
- Created new test file `tests/modules/meta/test_quality.py` with 18 tests across 6 test classes
- Covered: `validate_events` integration, `_check_future_timestamps` (clean/detected/exception), `_check_numeric_ranges` (in-range/above/below/exception), `_check_suspicious_duplicates` (clean/detected/exception), `detect_time_gaps` (no-gaps/detected/single-event/exception/invalid-timestamp), `_check_time_gaps` integration

**A-09: Period report date-sequence robustness** ✅
- Replaced hardcoded 30-entry UNION ALL SQL date sequence in `analysis/reports.py` with Python-generated date range using `date.fromisoformat()` + `timedelta(days=1)` loop
- Now supports arbitrary period lengths (was capped at 30 days)
- All 68 existing report tests pass unchanged

| Dead code (hypothesis list) | 65 lines | 0 |
| Correlator duplication | ~50 lines | 0 |

### Phase 3 — Completed (2026-03-26)

All Phase 3 items are done. 1385 tests passing, 0 lint errors.

**A-10: Deduplicate correlator methods** ✅
- Extracted shared correlation logic from `correlate()` and `_correlate_from_series()` into `_compute_from_aligned()`
- Both methods now delegate to the shared implementation — ~30 lines of duplication eliminated
- All 35 correlator tests pass unchanged

**A-11: Remove hardcoded HYPOTHESES list** ✅
- Removed 65-line hardcoded `HYPOTHESES` list from `analysis/hypothesis.py`
- `load_hypotheses()` now returns `[]` when no config (config.yaml is the single source of truth)
- Updated 3 test files: `test_hypothesis.py` (replaced `TestHypothesesList` with `TestLoadHypotheses`), `test_registry.py`
- Updated `docs/MASTER_WALKTHROUGH.md` to show config.yaml-based hypothesis creation

**A-12: Strengthen CI matrix for Python 3.14** ✅
- Added `allow-prereleases: true` to `actions/setup-python@v5` in `.github/workflows/ci.yml`
- Added `fail-fast: false` to strategy so a Python 3.14 failure doesn't cancel the 3.13 run

**A-13: Add E2E integration test for ETL → report pipeline** ✅
- Added `TestETLToReportPipeline` class to `tests/test_etl_integration.py` with 2 tests
- `test_full_pipeline_produces_report`: config → 3 modules → parse → insert → post_ingest → daily_summary → report file → verify sections
- `test_dry_run_produces_no_report`: dry_run + report=True skips report generation
- Also fixed pre-existing flaky `test_concurrent_insert_no_deadlock` by serializing DB creation and adding retry on WAL lock contention

---

## 7. THINGS NOT TO CHANGE

The following are deliberate design decisions that should be preserved:

1. **Module sovereignty** — No cross-module imports. The orchestrator is the only integration point.
2. **SQLite single-file DB** — Correct for a personal observatory. PostgreSQL would be overengineering.
3. **Batch ETL model** — Nightly cron is the right cadence. Real-time streaming adds complexity without proportional value.
4. **`str.split(",")` for CSV parsing** — Tasker CSVs are unquoted. This is 10x faster than `csv.reader()`.
5. **Hardcoded CST/CDT fallback** — `-0500` fallback in `utils.py` is correct for the user's timezone.
6. **INSERT OR REPLACE dedup strategy** — Deterministic event IDs make re-runs idempotent without upsert locks.
7. **SAVEPOINT isolation per module** — A failing module cannot corrupt other modules' data.
8. **Deferred items in CONDENSED_GOALS** — All 9 deferrals are correctly prioritized as non-urgent.

---

*Generated 2026-03-26 by Claude Opus 4.6*
