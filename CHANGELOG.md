# Changelog

All notable changes to LifeData will be documented in this file.

## [4.4.0] — 2026-03-26

### Added
- **Correlations table wired up** — `correlator.persist_matrix()` stores pairwise correlation results in the `correlations` table after each ETL run. Reports hypothesis section and `--trace` now return real data.
- **Per-metric report inclusion** — `get_daily_summary()` in all modules now respects `disabled_metrics`. Disabled metrics are omitted from report bullets, not just from data collection.
- **Report YAML frontmatter** — all three report types (daily, weekly, monthly) include machine-parseable YAML frontmatter with type, date, event_count, anomaly_count, and version.
- **Time-lagged hypothesis testing** — `lag_days` parameter in hypothesis config allows testing delayed effects (e.g., "afternoon caffeine disrupts next-day sleep").
- **Operational runbook** — `docs/OPERATIONAL_RUNBOOK.md` (372 lines) covering daily ops, backup/recovery, DB maintenance, key rotation, failure scenarios, monitoring checklists.
- **`requirements.lock`** — full dependency lockfile with exact versions for reproducible builds.

### Added — Testing
- Additional tests across world, reports, and cognition modules.
- Flaky `test_concurrent_insert_no_deadlock` stabilized with increased busy timeout.

### Improved
- **Config-driven timezone offset** — all 10 modules now read `_default_tz_offset` from config instead of hardcoding `-0500`. The orchestrator computes and injects this from the configured timezone.
- **Registry-based trend metrics** — `reports.py` uses `MetricsRegistry.get_trend_metrics()` as fallback instead of hardcoded metric names. Zero hardcoded `source_module` strings remain in the primary code path.
- **Media manifest complete** — `media.derived:daily_media_count` added to `get_metrics_manifest()` so `disabled_metrics` validation works correctly.
- **vaderSentiment replaced** — migrated from unmaintained `vaderSentiment` to `nltk.sentiment.vader`. Zero DeprecationWarnings.
- **CI Python matrix** — tests run on Python 3.13 and 3.14.

### Improved — Documentation
- All documents updated with current test count and coverage metrics.
- `CONDENSED_GOALS.md` — 11 previously "remaining" items reclassified as complete.
- `HERE_WE_GO_AGAIN.md` — comprehensive full-system audit report.

## [4.3.0] — 2026-03-26

### Added — Testing
- 139 new tests (1024 → 1163) across 6 modules with targeted coverage improvements.
- Module coverage gains: behavior 66% → 80%, oracle 66% → 80%, body 63% → 95%, media 49% → 100%, meta 65% → 100%, social 65% → 99%.

### Improved
- Overall coverage: 77% → 81%. CI floor remains 70%.
- **WAL checkpoint after ETL** — explicit `PRAGMA wal_checkpoint(TRUNCATE)` at end of each ETL run to prevent unbounded WAL growth.
- **Event ID caching** — `raw_source_id` and `event_id` computation memoized via property caching, eliminating redundant SHA-256 hashing on re-ingestion of unchanged events.

### Improved — Documentation
- `USER_GUIDE.md` — updated test count, cron schedule (Sunday midnight weekly report).
- `docs/MASTER_WALKTHROUGH.md` — added Per-Metric Configurability section, Schema Migrations section, weekly/monthly report CLI flags and cron entries.
- `docs/PERFORMANCE_BASELINE.md` — re-run baselines (insert throughput improved 42K → 58K events/sec).

## [4.2.0] — 2026-03-26

### Added — Configurability
- **Per-metric enable/disable** — `disabled_metrics: []` config on all 11 modules. Exact match (`device.derived:screen_time_minutes`) and prefix match (`device.derived` disables all derived). Validated against metrics manifest at startup.
- **Configurable composite weights** — `subjective_day_score_weights` (mind), `density_score_weights` (social), `cognitive_load_weights` (cognition) moved from hardcoded to config.yaml with sensible defaults.
- **Weekly report generation** — `python run_etl.py --weekly-report` generates 7-day aggregated report to `reports/weekly/`.
- **Monthly report generation** — `python run_etl.py --monthly-report` generates 30-day aggregated report to `reports/monthly/`.
- **Schema migrations framework** — `schema_versions` table tracks per-module DDL versions. `apply_migrations()` runs only new versions in all-or-nothing transactions.
- **Log rotation enforcement** — `enforce_log_rotation()` auto-deletes `.log` and `.jsonl` files older than `retention.log_rotation_days` at every ETL startup.

### Added — Testing
- 99 new tests (925 → 1024) covering: per-metric filtering, environment post-ingest (0% → 86%), media transcription (19% → 79%), deep post-ingest for oracle/world/body/social, schema migrations, log rotation.
- `tests/core/test_module_interface.py` — is_metric_enabled() and filter_events() coverage.
- `tests/modules/environment/test_post_ingest.py` — 16 tests for weather composite, location diversity, astro summary.
- `tests/modules/media/test_transcribe.py` — 13 tests for Whisper transcription with mocked model.

### Improved
- Coverage: 75% → 77% overall. CI floor remains 70%.
- All `post_ingest()` methods guard derived metric computations with `is_metric_enabled()`.
- Orchestrator validates `disabled_metrics` names against module manifests, logs warnings for typos.
- Parse-time filtering: disabled raw metrics are removed before database insertion.
- E402 lint fixes in `scripts/fetch_markets.py` and `scripts/fetch_schumann.py`.

### Improved — Documentation
- `USER_GUIDE.md` — comprehensive rewrite documenting all configurability features, CLI flags, report types, pattern/hypothesis config format, data retention, and updated file structure.
- `README.md` — updated with current test count, new CLI flags, configurability emphasis, and CONDENSED_GOALS.md reference.
- `CONDENSED_GOALS.md` — consolidated 8 planning documents into single status tracker; superseded docs removed.
- Planning document cleanup: removed 8 root-level analysis/planning files (COMPARISON_REPORT, EXECUTION_STRATEGY, FINAL_PLAN, GEMINI_ANALYSIS, LIFEDATA_GAP_COVERAGE, TERNARY_CLAUDE_ANALYSIS, ULTIMATE_REVIEW, CLAUDE_HEALTH_REPORT).

## [4.1.0] — 2026-03-25

### Added — New Modules
- **Cognition module** — Objective cognitive probes: reaction time, working memory (digit span), time perception, typing speed. Derived: cognitive load index, impairment flag, peak cognition hour, subjective-objective gap.
- **Behavior module** — Passive behavioral metrics: app switching, unlock latency, step distribution, dream journaling. Derived: fragmentation index, digital restlessness, attention span, morning inertia, movement entropy, behavioral consistency (10 derived metrics total).
- **Oracle module** — Esoteric data: I Ching castings, hardware RNG sampling, Schumann resonance, planetary hours. Derived: hexagram frequency, entropy test, RNG deviation, Schumann summary, activity by planet.

### Added — Infrastructure
- 605 tests (pytest) with 30s timeout per test
- Pydantic config schema validation (489 lines, 6-step startup checks)
- `core/parser_utils.py` — shared `safe_parse_rows()` with quarantine detection
- `core/sanitizer.py` — PII/key redaction for log output
- `core/metrics.py` — structured ETL telemetry (metrics.jsonl)
- `scripts/_http.py` — shared `retry_get()` with exponential backoff
- `scripts/fetch_schumann.py` — Schumann resonance fetcher
- `scripts/compute_planetary_hours.py` — astronomical calculations
- `--status` CLI flag for health summary
- `--trace` CLI flag for event provenance tracing
- Event provenance stamping (file, line, parser, version)

### Added — Analysis
- 9 multi-variable anomaly patterns (burnout, caffeine-sleep, restlessness, etc.)
- 10 pre-defined hypothesis tests
- 24-metric weekly correlation matrix
- Sparkline trend charts in daily reports

### Improved — Security Audit (21 findings remediated)
- Fail-closed module allowlist (empty = no modules loaded)
- `execute_migration()` restricts modules to CREATE/ALTER DDL only
- `execute()` restricted to read-only SQL (SELECT/WITH/EXPLAIN/PRAGMA)
- File permissions enforced: db 0600, dirs 0700, logs 0600, backups 0600
- File extension whitelist (.csv, .json only)
- File stability window (60s) prevents parsing mid-sync files
- FTS5 DELETE trigger for INSERT OR REPLACE correctness
- 5-point startup security check (env, config, dir, stfolder, encryption)

### Improved — Performance Optimizations
- SQLite PRAGMA tuning: synchronous=NORMAL, 40MB cache, memory temp, 30MB mmap
- `executemany()` batch inserts (replaces per-event execute loops)
- `affected_dates` parameter in `post_ingest()` — modules only recompute changed dates
- Expression index `idx_events_date_local` for all date-based queries
- Correlator series pre-fetch cache (N queries instead of 2*C(N,2))
- Oracle N+1 fix: 72 queries per day reduced to 1
- Behavior/cognition query consolidation (6→2, 3→1)
- Database backup via `conn.backup()` API (replaces unsafe `shutil.copy2`)
- Cursor-based keyset pagination in `query_events()`

### Improved — Code Quality
- 254 ruff lint fixes (auto-fixed), 36 remaining (style preferences)
- mypy --strict clean on all core/ files
- Standardized `create_module()` factory in all 11 `__init__.py` files
- Legacy `lifedata_etl_v3.py` archived to `legacy/`

### Improved — Documentation
- `docs/MASTER_WALKTHROUGH.md` — comprehensive system bible (17 sections)
- `USER_GUIDE.md` — accessible operational guide
- `docs/EXAMINATION_REPORT.md` — codebase audit with all findings and implementations
- `docs/THREAT_MODEL.md` — security model with remediation history
- `docs/PERFORMANCE_BASELINE.md` — benchmark baselines
- Consolidated 14 root-level docs to 4 (README, CLAUDE, CHANGELOG, USER_GUIDE)

## [4.0.0] — 2026-03-24

### Summary
Complete rewrite from monolithic v3 script to modular v4 architecture.

### Added
- Modular ETL architecture with sovereign module design (device, body, mind, environment, social, world, media, meta)
- Universal `Event` dataclass — all data normalized into a single schema
- SQLite storage with WAL mode, FTS5 full-text search, and SAVEPOINT isolation per module
- Security hardening: module allowlist, path validation, env-var-only secrets, flock-based ETL locking
- Idempotent ingestion via deterministic SHA-256 event IDs
- Dual-channel logging (JSON-lines file + human-readable console)
- Analysis engine: Pearson/Spearman correlation, z-score anomaly detection, daily markdown reports
- API fetch scripts for weather, news, markets, GDELT, and sensor data
- Configuration via `config.yaml` with `${ENV_VAR}` placeholder resolution

### Changed
- Migrated from single `lifedata_etl_v3.py` to `core/` + `modules/` + `analysis/` + `scripts/` layout
- Database schema redesigned around universal Event model
- Raw data handling moved to Syncthing-synced `raw/` directory with strict read-only policy

### Security
- API keys isolated to `.env` (chmod 600, gitignored)
- Syncthing relay connections disabled — device-to-device only
- Module loading restricted to explicit allowlist in config
- All file paths validated with `Path.is_relative_to()` before parsing
