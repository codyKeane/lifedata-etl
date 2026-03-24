# Changelog

All notable changes to LifeData will be documented in this file.

## [4.0.0] — Unreleased

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
