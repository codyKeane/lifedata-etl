# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LifeData V4 is a personal behavioral data observatory — a local-first ETL pipeline that collects data from a phone (via Tasker + Syncthing), APIs (weather, news, markets, Schumann resonance), and sensors, then stores everything as universal `Event` objects in SQLite.

## Commands

```bash
# Activate venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Full ETL run
python run_etl.py

# Single module only
python run_etl.py --module device

# Parse without writing to DB
python run_etl.py --dry-run

# ETL + daily report generation
python run_etl.py --report

# Health summary
python run_etl.py --status

# Run tests (605 tests, 30s timeout)
make test

# Type checking
make typecheck

# Linting
make lint
```

## Architecture

**Three-layer pipeline:** Collection -> ETL Engine -> SQLite Storage

### Core (`core/`)
- **`orchestrator.py`** — Main execution engine. Loads config, discovers modules, runs parse->insert pipeline with SAVEPOINT isolation per module.
- **`database.py`** — SQLite manager (WAL mode, tuned PRAGMAs, `executemany()` batch inserts). Six tables: `events`, `modules`, `media`, `daily_summaries`, `correlations`, `events_fts`.
- **`event.py`** — Universal `Event` dataclass. All data normalized into this schema. Deduplication via `raw_source_id` (SHA-256 hash) with `INSERT OR REPLACE`.
- **`module_interface.py`** — ABC that every module implements: `discover_files()`, `parse()`, optional `post_ingest(db, affected_dates)`, `get_daily_summary()`, `schema_migrations()`.
- **`config_schema.py`** — Pydantic validation with 6-step startup checks.
- **`logger.py`** — Dual-channel logging: JSON-lines to file, human-readable to console.
- **`parser_utils.py`** — Shared `safe_parse_rows()` for all CSV parsers.
- **`sanitizer.py`** — PII/key redaction for log output.

### Modules (`modules/`)
Eleven sovereign modules: `device`, `body`, `mind`, `environment`, `social`, `world`, `media`, `meta`, `cognition`, `behavior`, `oracle`. Each has `module.py` (implements `ModuleInterface`), `parsers.py`, and `__init__.py` with `create_module()` factory.

**Module sovereignty is the core design constraint:** no module imports another. Each owns its parsing, schema, and failure modes. The orchestrator wraps each module's writes in a SAVEPOINT.

### Analysis (`analysis/`)
- **`correlator.py`** — Pearson/Spearman correlation with series caching
- **`anomaly.py`** — Z-score anomaly detection + 9 multi-variable compound patterns
- **`hypothesis.py`** — 10 pre-defined hypothesis tests
- **`reports.py`** — Daily markdown report generator

### Scripts (`scripts/`)
API fetchers with `retry_get()` exponential backoff: `fetch_news.py`, `fetch_markets.py`, `fetch_rss.py`, `fetch_gdelt.py`, `fetch_schumann.py`, `compute_planetary_hours.py`, `process_sensors.py`.

## Data Flow

Phone (Tasker CSVs) -> Syncthing -> `raw/LifeData/logs/` -> Module `discover_files()` -> `parse()` -> `Event` objects -> SQLite `events` table

API scripts -> `raw/api/` -> World/Oracle modules parse -> same Event pipeline

## Key Configuration

- **`config.yaml`** — Master config. Module enable/disable, API params, analysis settings, cron schedules. Uses `${ENV_VAR}` placeholders resolved at runtime.
- **`.env`** — API keys (chmod 600, gitignored). Keys: `WEATHER_API_KEY`, `AIRNOW_API_KEY`, `AMBEE_API_KEY`, `NEWS_API_KEY`, `EIA_API_KEY`, `SYNCTHING_API_KEY`.

## Design Rules

- **Raw data is sacred** — never modify files in `raw/`.
- **API keys stay in `.env`** — never version-controlled or Syncthing-synced.
- **Syncthing relays must be disabled** — device-to-device only.
- **Module allowlist** — only modules listed in `security.module_allowlist` in config are loaded (fail-closed).
- **Idempotent ingestion** — deterministic `event_id` (UUID from SHA-256) means re-running ETL produces identical results.
- **Path validation** — all file paths checked with `Path.is_relative_to(raw_base)` before parsing.
- **Read-only execute** — `Database.execute()` only allows SELECT/WITH/EXPLAIN/PRAGMA.
- **Derived metric timestamps** — All `post_ingest()` daily derived metrics use `f"{date_str}T23:59:00+00:00"` as their timestamp. This ensures deterministic hashing for `INSERT OR REPLACE` idempotency. Exceptions: meta uses `T00:00:00` (start-of-day), oracle uses `T23:59:01/02` offsets for rolling-window metrics that would otherwise collide.
- **CSV fields are never quoted** — Tasker CSVs use bare comma separation. `parser_utils.py` uses `str.split(",")` for performance. If a data source introduces quoted fields, migrate to Python's `csv` module.
- **PII_HMAC_KEY is mandatory** — The `PII_HMAC_KEY` environment variable must be set in `.env` for the social module to load. Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`.

## Adding a New Module

1. Create `modules/<name>/module.py` implementing `ModuleInterface`
2. Create `modules/<name>/parsers.py` for file parsing logic
3. Add `modules/<name>/__init__.py` with `create_module(config)` factory
4. Add module to `security.module_allowlist` and `modules:` section in `config.yaml`
5. Module must emit `Event` objects — the only interface with core

## Documentation

Detailed docs live in `docs/`:
- `docs/MASTER_WALKTHROUGH.md` — Complete system bible
- `docs/THREAT_MODEL.md` — Security model and remediation history
- `docs/EXAMINATION_REPORT.md` — Codebase audit report
- `docs/PERFORMANCE_BASELINE.md` — Benchmark baselines
- `docs/tasker/` — Tasker task definitions

# You should always test a code block before moving on to the next one. If the test fails, fix it before moving on.
