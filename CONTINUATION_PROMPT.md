# Continuation Prompt for Claude Code

Copy everything below the line and paste it as your first message in a new Claude Code session.

---

Act as a master full-stack developer. You are picking up work on the LifeData V4 project. Read `ANALYSIS_ACTION_PLAN.md` (especially Section 7 — Implementation Log) and `CONDENSED_GOALS.md` for full context.

## What's Done

**All 13 action items (A-01 through A-13) across 3 phases are complete.** Everything is on the `dev2` branch, unstaged. Current state: **1385 tests passing**, 0 lint errors, mypy strict clean.

### Phase 1 (Foundation) — Complete
- A-01: SQL aggregate injection fix in `reports.py` (`_AGG_SQL` allowlist)
- A-02: All 32 lint warnings fixed to 0 across 19 source files
- A-03: Updated CONDENSED_GOALS lint count
- A-04: Version string synchronization (single source from `pyproject.toml`)

### Phase 2 (Coverage Push) — Complete
- A-05: `orchestrator.py` coverage 73% → 87% (+32 tests)
- A-06: `media/parsers.py` coverage 61% → 98% (+31 tests)
- A-07: `compute_planetary_hours.py` coverage 55% → 95% (+12 tests)
- A-08: `meta/quality.py` coverage 69% → 100% (+18 tests, new file `tests/modules/meta/test_quality.py`)
- A-09: Replaced hardcoded 30-entry UNION ALL date sequence in `reports.py` with Python date range loop (supports arbitrary period lengths)

### Phase 3 (Structural Improvements) — Complete
- A-10: Correlator deduplication — extracted `_compute_from_aligned()` shared method
- A-11: Removed 65-line hardcoded `HYPOTHESES` list — config.yaml is now single source of truth
- A-12: CI matrix hardened — `allow-prereleases: true` + `fail-fast: false` for Python 3.14
- A-13: E2E integration test for ETL → report pipeline (2 tests in `test_etl_integration.py`)

### Bug Fixes Along the Way
- Fixed pre-existing flaky `test_concurrent_insert_no_deadlock` (serialized DB creation + retry on WAL lock contention)
- Fixed 4 hardcoded-date test failures in `test_anomaly.py` (replaced with relative date helpers)

## What Remains

### Tier 4 — Deferred (A-14 through A-17)
These were explicitly deferred in the action plan as low-priority. Read Section 5 of `ANALYSIS_ACTION_PLAN.md` for details:
- A-14: Remaining coverage gaps (world 55%, process_sensors 58%, cognition 72%, fetch_news 74%)
- A-15: Reports.py coverage (currently 67%)
- A-16: Database edge case tests
- A-17: Script edge case tests

### Other Remaining Work (from CONDENSED_GOALS.md)
Coverage targets for files still below 80%:
| File | Current | Target |
|------|---------|--------|
| world/module.py | 55% | 80%+ |
| scripts/process_sensors.py | 58% | 80%+ |
| media/parsers.py | ~~61%~~ 98% ✅ | — |
| reports.py | 67% | 80%+ |
| cognition/module.py | 72% | 80%+ |
| orchestrator.py | ~~73%~~ 87% ✅ | — |
| scripts/fetch_news.py | 74% | 80%+ |

## Important Context

1. **All changes are unstaged on `dev2`** — the user may want to commit, stage, or create a PR.
2. **Do NOT modify source code to boost coverage** — only write tests (unless fixing actual bugs).
3. **Test after each change** — run specific test file, then `make test` for full suite.
4. **Follow existing test patterns** — check existing test files for fixtures and conventions.
5. **Update `ANALYSIS_ACTION_PLAN.md` Section 7** after completing any new item.
6. **Update test count in `CONDENSED_GOALS.md`** if it changes.

## Quick Commands

```bash
source venv/bin/activate
make test              # Full suite (1385 tests)
make typecheck         # mypy --strict core/
make lint              # ruff check
pytest tests/<path> -v --cov=<module> --cov-report=term-missing  # Targeted coverage
```

Ask the user what they'd like to work on next.
