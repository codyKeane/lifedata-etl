# Changelog

All notable changes to LifeData will be documented in this file.

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
