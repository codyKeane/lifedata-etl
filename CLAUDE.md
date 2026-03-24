# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LifeData V4 is a personal behavioral data observatory — a local-first ETL pipeline that collects data from a phone (via Tasker + Syncthing), APIs (weather, news, markets), and sensors, then stores everything as universal `Event` objects in SQLite.

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

# Type checking
pyright
```

No test framework exists. Validation is inline during parsing (malformed rows are logged and skipped).

## Architecture

**Three-layer pipeline:** Collection → ETL Engine → SQLite Storage

### Core (`core/`)
- **`orchestrator.py`** — Main execution engine. Loads config, discovers modules, runs parse→insert pipeline with SAVEPOINT isolation per module.
- **`database.py`** — SQLite manager (WAL mode). Six tables: `events`, `modules`, `media`, `daily_summaries`, `correlations`, `events_fts`.
- **`event.py`** — Universal `Event` dataclass. All data across all modules is normalized into this schema. Deduplication via `raw_source_id` (SHA-256 hash) with `INSERT OR REPLACE`.
- **`module_interface.py`** — ABC that every module implements: `discover_files()`, `parse()`, optional `post_ingest()`, `get_daily_summary()`, `schema_migrations()`.
- **`logger.py`** — Dual-channel logging: JSON-lines to file, human-readable to console.

### Modules (`modules/`)
Eight sovereign modules: `device`, `body`, `mind`, `environment`, `social`, `world`, `media`, `meta`. Each has its own `module.py` (implements `ModuleInterface`) and `parsers.py`.

**Module sovereignty is the core design constraint:** no module imports another. Each owns its parsing, schema, and failure modes. Removing any module leaves the rest intact. The orchestrator wraps each module's writes in a SAVEPOINT — one module crashing never affects others.

### Analysis (`analysis/`)
- **`correlator.py`** — Pearson/Spearman correlation between daily metric pairs
- **`anomaly.py`** — Z-score anomaly detection
- **`hypothesis.py`** — Hypothesis testing (partially implemented)
- **`reports.py`** — Daily markdown report generator → `reports/`

### Scripts (`scripts/`)
Standalone data fetchers for APIs: `fetch_news.py`, `fetch_markets.py`, `fetch_rss.py`, `fetch_gdelt.py`, `process_sensors.py`. These write to `raw/api/`.

## Data Flow

Phone (Tasker CSVs) → Syncthing → `raw/LifeData/logs/` → Module `discover_files()` → `parse()` → `Event` objects → SQLite `events` table

API scripts → `raw/api/` → World module parses → same Event pipeline

## Key Configuration

- **`config.yaml`** — Master config. Module enable/disable, API params, analysis settings, cron schedules. Uses `${ENV_VAR}` placeholders resolved at runtime.
- **`.env`** — API keys (chmod 600, gitignored). Keys: `WEATHER_API_KEY`, `AIRNOW_API_KEY`, `AMBEE_API_KEY`, `NEWS_API_KEY`, `EIA_API_KEY`, `SYNCTHING_API_KEY`.
- **`pyrightconfig.json`** — Python 3.14, basic type checking.

## Design Rules

- **Raw data is sacred** — never modify files in `raw/`.
- **API keys stay in `.env`** — never version-controlled or Syncthing-synced.
- **Syncthing relays must be disabled** — device-to-device only.
- **Module allowlist** — only modules listed in `security.module_allowlist` in config are loaded.
- **Idempotent ingestion** — deterministic `event_id` (UUID from SHA-256) means re-running ETL produces identical results.
- **Path validation** — all file paths checked with `Path.is_relative_to(raw_base)` before parsing.

## Adding a New Module

1. Create `modules/<name>/module.py` implementing `ModuleInterface`
2. Create `modules/<name>/parsers.py` for file parsing logic
3. Add `modules/<name>/__init__.py` with `create_module(config)` factory
4. Add module to `security.module_allowlist` and `modules:` section in `config.yaml`
5. Module must emit `Event` objects — the only interface with core

# You should always test a code block before moving on to the next one. If the test fails, fix it before moving on. If the test passes, move on to the next one.

## Keep a running log of what you've done in a file called `CLAUDE_LOG.md` in the root directory. This log should be updated after every code block that you test. It should be in markdown format and should include the date and time of the test, the code block that was tested, and the result of the test. 