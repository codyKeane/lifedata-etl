# CONDENSED GOALS — LifeData V4

**Last Updated:** 2026-03-26
**Current State:** 1385 tests, 84% coverage, mypy strict clean, all critical findings resolved, 0 deprecation warnings

---

## COMPLETED OBJECTIVES

Every item below has been verified against the current codebase.

### Security (All Resolved)

| ID | Objective | Verification |
|----|-----------|-------------|
| U-07 | Remove PII HMAC hostname fallback | `grep hostname modules/social/parsers.py` returns nothing |
| U-07b | Make PII_HMAC_KEY mandatory (RuntimeError) | Tests confirm import-time error without key |
| U-20 | Create .env.example with all required keys | `.env.example` exists in root |
| SEC-1 | Fail-closed module allowlist | `config_schema.py` validates non-empty allowlist |
| SEC-2 | Path traversal prevention | `_is_safe_path()` uses `Path.resolve().is_relative_to()` |
| SEC-3 | Log sanitization (API keys, GPS, phone, email) | `sanitizer.py` at 100% coverage |
| SEC-4 | FTS5 DELETE trigger | Trigger present in `database.py` schema DDL |
| SEC-5 | File permissions enforcement (0600) | Startup checks in `orchestrator.py` |
| SEC-6 | Syncthing relay prohibition | Config validator + META module runtime check |

### Architecture (All Resolved)

| ID | Objective | Verification |
|----|-----------|-------------|
| U-S3 | Eliminate hardcoded source_module strings in analysis | `reports.py` uses `get_daily_summary()` + registry-based trend metrics |
| U-S4 | Config-driven anomaly thresholds | 9 patterns in `config.yaml` with `enabled` flags |
| GAP-2 | Metrics Registry pattern | `get_metrics_manifest()` on all 11 modules, `analysis/registry.py` |
| GAP-2b | Config-driven hypotheses | 10 hypotheses in `config.yaml` with direction/threshold/enabled |
| GAP-2c | Config-driven report sections | `report.sections` and `report.trend_metrics` in config |
| U-09 | Standardize derived metric timestamps | All modules use `T23:59:00+00:00` (meta: `T00:00:00`, oracle: `:01/:02` offsets) |
| TZ-1 | Config-driven timezone offset | All modules read `_default_tz_offset` from config; orchestrator computes from configured timezone |

### Code Quality (All Resolved)

| ID | Objective | Verification |
|----|-----------|-------------|
| U-06 | Fix hypothesis operator precedence | Explicit parentheses in `hypothesis.py` |
| U-08 | Document CSV parser no-quoted-fields assumption | Comment in `parser_utils.py:73` + CLAUDE.md design rule |
| U-10 | SQL aggregate dict-based lookup (no f-string) | `_AGG_SQL` dict in `anomaly.py` |
| U-17 | Cognition parser registry assertion | `assert` present in `cognition/module.py` |
| U-24 | Schumann regex handles integer Hz | Pattern `(\d+(?:\.\d+)?)` in `fetch_schumann.py` |
| LINT | Fix E402 imports in scripts | `# noqa: E402` on affected lines; `ruff check scripts/` clean |
| DEP-1 | Replace vaderSentiment with NLTK VADER | `nltk==3.9.1`; all imports use `nltk.sentiment.vader`; 0 DeprecationWarnings |

### Testing (All Resolved)

| ID | Objective | Verification |
|----|-----------|-------------|
| GAP-1 | Analysis layer test coverage (was 0%) | `test_correlator.py`, `test_hypothesis.py`, `test_anomaly.py`, `test_reports.py`, `test_registry.py` |
| GAP-1b | Post-ingest tests for all modules | All 11 modules have `test_post_ingest.py` |
| GAP-5 | Script test coverage (was 0%) | 8 test files in `tests/scripts/` |
| GAP-4 | CI/CD pipeline (Python 3.13 + 3.14 matrix) | `.github/workflows/ci.yml` with lint + typecheck + 70% coverage floor |
| HEALTH-3 | Environment post-ingest tests (was 0%) | 16 tests in `test_post_ingest.py` (86% coverage) |
| HEALTH-4 | Media transcription tests (was 19%) | 13 tests in `test_transcribe.py` (79% coverage) |

### Configurability (All Resolved)

| ID | Objective | Verification |
|----|-----------|-------------|
| HEALTH-C1 | Per-metric enable/disable | `disabled_metrics: []` in all 11 module configs; `is_metric_enabled()` guards in all post_ingest() |
| HEALTH-C2 | Composite weight configuration | `subjective_day_score_weights`, `density_score_weights`, `cognitive_load_weights` in config |
| HEALTH-C3 | Weekly/monthly report generation | `generate_weekly_report()`, `generate_monthly_report()` in `reports.py`; CLI flags in `run_etl.py` |
| HEALTH-C4 | Schema migrations framework | `schema_versions` table, `apply_migrations()` in `database.py` |
| HEALTH-C5 | Log rotation enforcement | `enforce_log_rotation()` in `orchestrator.py` |

### Features & Infrastructure (Completed in v4.3–v4.4)

| Objective | Verification |
|-----------|-------------|
| WAL checkpoint after ETL | `database.py` `checkpoint()` + `orchestrator.py` calls it after all modules complete |
| Event ID caching (memoized SHA-256) | `_cached_raw_source_id` / `_cached_event_id` in `event.py` |
| Time-lagged hypothesis testing | `lag_days` parameter in `hypothesis.py`; config.yaml caffeine hypothesis uses `lag_days: 1` |
| Report YAML frontmatter | `_yaml_frontmatter()` in `reports.py` for all 3 report types |
| Operational runbook | `docs/OPERATIONAL_RUNBOOK.md` (372 lines) |
| Correlations table wired up | `correlator.persist_matrix()` stores pairwise results in `correlations` table |
| Per-metric report inclusion | `get_daily_summary()` respects `disabled_metrics`; disabled metrics omitted from reports |
| Transitive dependencies pinned | `requirements.lock` with exact versions |
| Performance baselines re-run | `docs/PERFORMANCE_BASELINE.md` 2026-03-26 baseline (insert: 58K events/sec) |
| Module coverage: behavior 80%, oracle 80%, body 94%, media 98%, meta 99%, social 98% | All post_ingest test files in place |

### Documentation (All Resolved)

| Objective | Verification |
|-----------|-------------|
| USER_GUIDE weekly/monthly flags | Documented in USER_GUIDE.md |
| MASTER_WALKTHROUGH per-metric docs | Per-Metric Configurability section added |
| CHANGELOG through v4.4.0 | All implementation entries present |

---

## DEFERRED OBJECTIVES (Strategic / Not Urgent)

These items were identified across audits but explicitly deferred as non-critical for the current batch-processing model.

| ID | Objective | Rationale for Deferral |
|----|-----------|----------------------|
| SCALE-3 | Connection pooling / concurrent writes | SQLite WAL handles nightly batch model; pooling needed only for real-time streaming |
| SCALE-5 | Pagination in query_events() | Current dataset (~13K events) fits in memory; needed at 500K+ |
| PII-2 | Field-level encryption (Fernet) for value_json PII | HMAC hashing covers contact identifiers; Fernet would break FTS5 |
| PII-3 | SQLCipher for database-at-rest encryption | FDE (LUKS/fscrypt) is primary control |
| ARCH-3 | Correlator code deduplication (~95 lines) | Functional, not a correctness issue |
| ARCH-4 | Bonferroni correction for multiple hypothesis testing | 10 hypotheses is small enough; needed if count grows significantly |
| CONFIG-1 | Configurable app classification keywords (social) | Hardcoded productive/distraction lists work for personal use |
| CONFIG-2 | Config-driven fetch parameters (news, markets, GDELT) | RSS feeds already config-driven; others rarely change |
| CURSOR-1 | Database cursor handling consistency | Low-priority cleanup; no bugs from current inconsistency |

---

## REMAINING OBJECTIVES (Low Priority)

### Testing Depth

Below-target coverage files. None are blocking; all are incremental improvements.

| File | Current | Target | Effort |
|------|---------|--------|--------|
| world/module.py | 55% | 80%+ | 2-3 hr |
| scripts/process_sensors.py | 58% | 80%+ | 2-3 hr |
| scripts/compute_planetary_hours.py | 55% | 80%+ | 1-2 hr |
| media/parsers.py | 61% | 80%+ | 2-3 hr |
| reports.py | 67% | 80%+ | 2-3 hr |
| cognition/module.py | 72% | 80%+ | 1-2 hr |
| orchestrator.py | 73% | 80%+ | 2-3 hr |
| scripts/fetch_news.py | 74% | 80%+ | 1 hr |

---

## ARCHIVED DOCUMENTS

Root-level planning and analysis documents consolidated into this file across two cleanup passes:

**First cleanup (v4.2):** COMPARISON_REPORT.md, EXECUTION_STRATEGY.md, FINAL_PLAN.md, GEMINI_ANALYSIS.md, LIFEDATA_GAP_COVERAGE.md, TERNARY_CLAUDE_ANALYSIS.md, ULTIMATE_REVIEW.md, CLAUDE_HEALTH_REPORT.md

**Second cleanup (v4.4):** ANOTHER_PLAN.md (implementation roadmap — all items complete or captured above), QUATERNARY_ANALYSIS.md (stale analysis — superseded), HERE_WE_GO_AGAIN.md (audit snapshot — findings captured above)

Permanent reference documents in `docs/`:
- `docs/MASTER_WALKTHROUGH.md` — System bible (authoritative architecture reference)
- `docs/THREAT_MODEL.md` — Security model with remediation history
- `docs/EXAMINATION_REPORT.md` — Historical audit record (2026-03-25)
- `docs/OPERATIONAL_RUNBOOK.md` — Operations, maintenance, and recovery procedures
- `docs/PERFORMANCE_BASELINE.md` — Benchmark baselines for regression detection

---

## METRICS SNAPSHOT

| Metric | Value |
|--------|-------|
| Tests | 1291 passing |
| Coverage | 84% overall |
| mypy strict (core/) | 0 issues |
| Lint errors | 0 in source code (all 32 warnings fixed) |
| DeprecationWarnings | 0 |
| Modules | 11/11 with full interface |
| Derived metrics | 37 across all modules |
| Anomaly patterns | 9 (config-driven) |
| Hypotheses | 10 (config-driven) |
| Report types | Daily, Weekly, Monthly |
| Schema migrations | Framework active (version-tracked) |

---

*Last updated 2026-03-26.*
