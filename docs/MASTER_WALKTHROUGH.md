# LifeData V4 — Master Walkthrough Bible

**Version:** 4.3.0
**Last Updated:** 2026-03-26
**Codebase:** ~26,000 lines of Python across 143 files, 11 sovereign modules

This document describes every moving part of the LifeData V4 system: how data enters, how it transforms, how modules interact through the orchestrator, and how the analysis layer derives insight. It is the single source of truth for anyone who needs to understand, operate, extend, or debug this system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Directory Structure](#2-directory-structure)
3. [Data Flow — End to End](#3-data-flow--end-to-end)
4. [Core Engine](#4-core-engine)
5. [The Universal Event Schema](#5-the-universal-event-schema)
6. [The Module System](#6-the-module-system)
7. [Module Catalog](#7-module-catalog)
8. [Database Layer](#8-database-layer)
9. [Configuration System](#9-configuration-system)
10. [Analysis Engine](#10-analysis-engine)
11. [Report Generation](#11-report-generation)
12. [API Fetcher Scripts](#12-api-fetcher-scripts)
13. [Security Model](#13-security-model)
14. [Observability & Debugging](#14-observability--debugging)
15. [Cron Scheduling](#15-cron-scheduling)
16. [Extension Guide](#16-extension-guide)
17. [Glossary](#17-glossary)

---

## 1. System Overview

LifeData V4 is a **personal behavioral data observatory**. It collects data from three source families:

| Source | Transport | Landing Zone |
|--------|-----------|--------------|
| Phone (Tasker CSVs) | Syncthing device-to-device sync | `raw/LifeData/logs/` |
| APIs (weather, news, markets, Schumann) | HTTP fetcher scripts on cron | `raw/api/` |
| Sensors (accelerometer, magnetometer, barometer) | Syncthing / Sensor Logger app | `raw/LifeData/logs/sensors/` |

A nightly ETL pipeline parses these raw files into **universal Event objects**, stores them in SQLite, then derives daily metrics, detects anomalies, computes cross-domain correlations, and generates markdown reports.

**Design philosophy:** Local-first. No cloud. No telemetry. Raw data is sacred (never modified). Modules are sovereign (no inter-module imports). Ingestion is idempotent (re-running produces identical results).

---

## 2. Directory Structure

```
~/LifeData/
├── core/                    # ETL engine (orchestrator, database, event model, config)
│   ├── orchestrator.py      # Main execution engine
│   ├── database.py          # SQLite manager (WAL, SAVEPOINT isolation)
│   ├── event.py             # Universal Event dataclass
│   ├── module_interface.py  # ABC contract for all modules
│   ├── config.py            # YAML + .env loader
│   ├── config_schema.py     # Pydantic validation (489 lines)
│   ├── logger.py            # JSON-line file + console logging
│   ├── metrics.py           # Per-run ETL telemetry
│   ├── parser_utils.py      # safe_parse_rows() — shared CSV parsing
│   ├── sanitizer.py         # PII/key redaction for logs
│   └── utils.py             # Timestamp parsing, safe_float, glob_files
│
├── modules/                 # 11 sovereign data modules
│   ├── device/              # Phone hardware: battery, screen, charging, bluetooth
│   ├── body/                # Biometrics: steps, heart rate, sleep, caffeine
│   ├── mind/                # Subjective: mood, energy, stress, productivity
│   ├── environment/         # External: weather, air quality, location, astro
│   ├── social/              # Interaction: calls, SMS, notifications, app usage
│   ├── world/               # Global: news sentiment, markets, RSS, GDELT
│   ├── media/               # Rich: photos, video, voice memos, transcription
│   ├── meta/                # Health: completeness, quality, storage, sync checks
│   ├── cognition/           # Probes: reaction time, memory, time perception, typing
│   ├── behavior/            # Patterns: app switching, unlock latency, dreams, steps
│   └── oracle/              # Esoteric: I Ching, hardware RNG, Schumann, planetary hours
│
├── analysis/                # Statistical analysis layer
│   ├── correlator.py        # Pearson/Spearman pairwise correlation
│   ├── anomaly.py           # Z-score anomaly + multi-variable pattern detection
│   ├── hypothesis.py        # Formal hypothesis testing framework
│   └── reports.py           # Daily markdown report generator
│
├── scripts/                 # Standalone API fetchers
│   ├── _http.py             # Shared retry_get() with exponential backoff
│   ├── fetch_news.py        # NewsAPI headlines + VADER sentiment
│   ├── fetch_markets.py     # Bitcoin (CoinGecko), gas (EIA)
│   ├── fetch_rss.py         # RSS feed processor (feedparser)
│   ├── fetch_gdelt.py       # GDELT global event database
│   ├── fetch_schumann.py    # Schumann resonance (HeartMath)
│   ├── compute_planetary_hours.py  # Astral library sunrise/sunset
│   └── process_sensors.py   # Sensor Logger CSV aggregation
│
├── tests/                   # 1291 tests (pytest, 30s timeout)
├── db/                      # SQLite database + daily backups
├── raw/                     # Sacred source data (never modified)
├── media/                   # Photos, video, voice, thumbnails
├── logs/                    # ETL logs (JSON-line) + metrics.jsonl
├── reports/                 # Generated daily/weekly/monthly markdown reports
├── legacy/                  # Archived v3 code
│
├── run_etl.py               # CLI entry point
├── config.yaml              # Master configuration
├── .env                     # API keys (chmod 600, gitignored)
├── Makefile                 # Build/test/lint targets
└── pyproject.toml           # Ruff, mypy, pytest configuration
```

---

## 3. Data Flow — End to End

```
  COLLECTION                    ETL ENGINE                        STORAGE & ANALYSIS
  ──────────                    ──────────                        ──────────────────

  ┌─────────────┐
  │ Tasker CSVs  │──Syncthing──▶ raw/LifeData/logs/
  │ (phone)      │                    │
  └─────────────┘                     │
                                      ▼
  ┌─────────────┐           ┌──────────────────┐        ┌───────────────┐
  │ API Scripts  │──cron──▶ │  raw/api/         │        │ SQLite DB     │
  │ (fetch_*)    │          └──────────────────┘        │ (WAL mode)    │
  └─────────────┘                     │                  │               │
                                      ▼                  │  events       │
  ┌─────────────┐           ┌──────────────────┐        │  modules      │
  │ Sensor Logger│──Sync──▶ │  raw/.../sensors/ │        │  media        │
  │ (phone app)  │          └──────────────────┘        │  daily_summ.  │
  └─────────────┘                     │                  │  correlations │
                                      ▼                  │  events_fts   │
                              ┌──────────────┐           └───────┬───────┘
                              │ Orchestrator  │                   │
                              │ run_etl.py    │                   ▼
                              │               │           ┌──────────────┐
                              │ For each      │           │ Analysis     │
                              │  module:      │           │  correlator  │
                              │  1. discover  │           │  anomaly     │
                              │  2. validate  │           │  hypothesis  │
                              │  3. parse     │           │  reports     │
                              │  4. insert    │           └──────┬───────┘
                              │  5. derive    │                  │
                              └──────────────┘                  ▼
                                                         ┌──────────────┐
                                                         │ reports/     │
                                                         │ daily/*.md   │
                                                         └──────────────┘
```

### Step-by-step execution:

1. **`run_etl.py`** acquires an exclusive flock, creates the `Orchestrator`.
2. **Config loading:** `config.py` reads `config.yaml`, resolves `${ENV_VAR}` from `.env`, validates via Pydantic schema (6-step validation).
3. **Security checks:** `.env` permissions (0o600), config permissions, directory permissions, Syncthing folder detection, disk encryption probe.
4. **Schema ensure:** Creates all 6 tables + indexes + FTS5 if not present.
5. **Backup:** Uses SQLite `conn.backup()` API for a safe snapshot before writes.
6. **Module discovery:** Iterates `modules/`, checks allowlist, checks enabled flag, imports `create_module()`, instantiates.
7. **For each module (SAVEPOINT-isolated):**
   - `schema_migrations()` — DDL-only (CREATE/ALTER)
   - `discover_files(raw_base)` — returns file paths
   - Path validation — `_is_safe_path()` prevents traversal
   - Extension filter — only `.csv` and `.json` allowed
   - Stability check — skip files modified within 60 seconds (mid-sync protection)
   - `parse(file_path)` — returns `list[Event]`
   - `insert_events_for_module()` — SAVEPOINT + INSERT OR REPLACE
   - `post_ingest(db, affected_dates)` — compute derived metrics
8. **Metrics:** Write structured JSON telemetry to `logs/metrics.jsonl`.
9. **Report:** If `--report`, generate daily markdown via `analysis/reports.py`.
10. **Lock release:** Close file descriptor (flock auto-releases).

---

## 4. Core Engine

### 4.1 Orchestrator (`core/orchestrator.py` — 502 lines)

The orchestrator is the conductor. It never parses data itself — it delegates to modules. Its responsibilities:

- **Config loading and validation** — Fails fast with all errors.
- **Security posture checks** — Advisory warnings, never blocks the ETL.
- **Module discovery** — Allowlist-restricted, fail-closed (empty list = no modules).
- **File pipeline** — discover → validate path → check extension → check stability → parse.
- **SAVEPOINT isolation** — Each module's writes are atomic. A crash in module B cannot corrupt module A's data.
- **Metrics collection** — Per-module file counts, event counts, durations, errors.
- **Report orchestration** — Lazy-imports `analysis.reports` to avoid import-time scipy overhead.

Key design decision: The orchestrator imports modules via `importlib.import_module()`, not static imports. This means a module can be added or removed without touching orchestrator code.

### 4.2 Database Manager (`core/database.py` — ~500 lines)

SQLite in WAL mode with these guarantees:

| Feature | Implementation |
|---------|---------------|
| Concurrent reads | WAL journal mode |
| Atomic module writes | SAVEPOINT per module |
| Batch ingestion | `executemany()` for all valid events per module |
| Idempotent ingestion | INSERT OR REPLACE on `raw_source_id` |
| DDL-only migrations | `execute_migration()` rejects non-CREATE/ALTER |
| Read-only execute | `execute()` rejects non-SELECT/WITH/EXPLAIN/PRAGMA |
| Safe backups | `conn.backup()` API (not file copy) |
| Full-text search | FTS5 content-sync with INSERT + DELETE triggers |
| Date-based queries | Expression index on `date(timestamp_local)` |
| Cursor pagination | Keyset pagination via `(sort_col, event_id)` |

**Performance PRAGMAs (applied at connection time):**

| PRAGMA | Value | Purpose |
|--------|-------|---------|
| `journal_mode` | WAL | Concurrent reads during writes |
| `synchronous` | NORMAL | Safe for WAL; reduces fsync overhead |
| `cache_size` | -40000 (40MB) | Larger page cache reduces disk I/O |
| `temp_store` | MEMORY | Temp tables in RAM, not disk |
| `mmap_size` | 30000000 (30MB) | Memory-mapped reads for large queries |
| `busy_timeout` | 5000 | 5-second retry on lock contention |

**Six tables:**

| Table | Purpose | Key |
|-------|---------|-----|
| `events` | All data points from all modules | `event_id` (deterministic UUID) |
| `modules` | Module registry + last run status | `module_id` |
| `media` | Photo/video/voice metadata | `media_id` |
| `daily_summaries` | Aggregated daily metrics per module | `(date, module, metric)` |
| `correlations` | Pairwise correlation results | `corr_id` |
| `events_fts` | Full-text search on tags + value_text | FTS5 virtual table |

**Seven indexes:**

| Index | Columns | Used By |
|-------|---------|---------|
| `idx_events_time` | `timestamp_utc` | Time-range queries |
| `idx_events_source` | `source_module` | Module-specific queries |
| `idx_events_type` | `event_type` | Type-specific queries |
| `idx_events_source_time` | `(source_module, timestamp_utc)` | Module + time queries |
| `idx_events_tags` | `tags` | Tag filtering |
| `idx_events_date_local` | `date(timestamp_local)` | All date-based queries (expression index) |
| `raw_source_id UNIQUE` | Implicit on column | Deduplication |

### 4.3 Logger (`core/logger.py` — 101 lines)

Dual-channel logging:
- **File:** JSON-lines to `logs/etl.log` — machine-parseable, `chmod 0o600`
- **Console:** Human-readable `asctime [module] LEVEL: message`
- **Sanitization:** Embedded newlines stripped (prevents log injection from CSV data)

### 4.4 Metrics (`core/metrics.py` — 122 lines)

Each ETL run produces one `ETLMetrics` object appended as a JSON line to `logs/metrics.jsonl`. Contains:
- Run ID (UUID), start/finish timestamps, duration
- Per-module: files discovered/parsed/quarantined, events parsed/ingested/skipped, duration, errors
- System: DB size (MB), disk free (GB)

The `--status` CLI flag reads the last 7 entries and prints a health summary table with warnings.

### 4.5 Parser Utilities (`core/parser_utils.py` — 112 lines)

`safe_parse_rows()` is the shared parsing engine used by all module parsers:

1. Opens CSV file with `errors='replace'` (corrupt bytes become `?`)
2. Splits each line on commas
3. Calls the module's row-level parser function
4. Catches exceptions per-row (never crashes the file)
5. Stamps provenance on every event: `file=X:line=Y:parser=Z:v=W`
6. Quarantines the file if >50% of rows are skipped (logs WARNING)

### 4.6 Sanitizer (`core/sanitizer.py` — 92 lines)

Before logging raw data, `sanitize_for_log()` applies four redaction passes:
1. GPS coordinates truncated to 2 decimal places (`32.776700` → `32.77***`)
2. Phone numbers replaced with `[REDACTED_PHONE]`
3. Email addresses replaced with `[REDACTED_EMAIL]`
4. API keys/tokens (32+ chars) replaced with `[REDACTED_KEY]`

Order matters: coordinates are processed before keys (shorter patterns first).

### 4.7 Utilities (`core/utils.py` — 211 lines)

| Function | Purpose |
|----------|---------|
| `parse_timestamp(raw, tz_offset)` | Parses epoch, ISO 8601, local datetime → `(utc_iso, local_iso)` |
| `format_offset(tz_offset)` | Normalizes `-5` → `-0500`, `+05:30` → `+0530` |
| `glob_files(dir, pattern)` | Safe recursive glob with traversal rejection |
| `safe_float(value)` | Parses to float, returns None on failure, rejects NaN/Inf |
| `safe_int(value)` | Parses to int, returns None on failure |
| `safe_json(obj)` | JSON serialize with fallback for non-serializable types |
| `today_local(tz)` | Today's date string in given timezone |
| `now_utc_iso()` | Current UTC time as ISO 8601 |

---

## 5. The Universal Event Schema

Every data point in the system — from a screen unlock to a mood rating to a geomagnetic reading to an I Ching casting — is represented as an `Event` object:

```python
@dataclass
class Event:
    timestamp_utc: str          # When it happened (UTC ISO 8601)
    timestamp_local: str        # When it happened (local time)
    timezone_offset: str        # Tasker-style offset: "-0500"
    source_module: str          # Dot-notation: "device.battery"
    event_type: str             # Subtype: "pulse", "screen_on"
    value_numeric: float | None # Numeric payload (battery=72, mood=7)
    value_text: str | None      # Text payload (headline, dream journal)
    value_json: str | None      # Complex payload as JSON string
    tags: str | None            # Comma-separated tags
    location_lat: float | None  # GPS latitude
    location_lon: float | None  # GPS longitude
    media_ref: str | None       # UUID → media table
    confidence: float           # 0.0–1.0 reliability score
    parser_version: str | None  # Semver of the parser
    created_at: str             # ETL ingestion timestamp
    provenance: str | None      # Debug trace (not stored in DB)
```

### Deduplication

- `raw_source_id` = SHA-256 of `timestamp_utc|source_module|event_type|value_text|value_numeric`, truncated to 32 hex chars.
- `event_id` = UUID derived from SHA-256 of `raw_source_id`.
- Both are deterministic: re-running the ETL on the same data produces identical IDs.
- `INSERT OR REPLACE` on `raw_source_id` means duplicates overwrite, not accumulate.

### Validation

`event.validate()` checks: required fields present, `source_module` uses dot-notation, at least one value field set, confidence in [0,1], `value_json` is valid JSON, field lengths within limits (50K text, 100K JSON, 1K tags).

---

## 6. The Module System

### 6.1 Module Interface Contract (`core/module_interface.py`)

Every module implements this ABC:

| Method | Required | Purpose |
|--------|----------|---------|
| `module_id` | Yes (property) | Unique identifier, e.g. `"device"` |
| `display_name` | Yes (property) | Human name, e.g. `"Device Module"` |
| `version` | Yes (property) | Semver string |
| `source_types` | Yes (property) | List of `source_module` values emitted |
| `discover_files(raw_base)` | Yes | Return file paths to parse |
| `parse(file_path)` | Yes | Parse one file → `list[Event]` |
| `post_ingest(db, affected_dates)` | No | Compute derived metrics |
| `get_daily_summary(db, date_str)` | No | Return daily metric dict |
| `schema_migrations()` | No | Return DDL SQL statements |

### 6.2 Module Sovereignty

The cardinal rule: **no module imports another module**. Modules communicate only through the events table. If mind needs to know about sleep, it queries `body.sleep` events from the database — it never imports body's code.

This means:
- Removing any module leaves the rest intact.
- A crash in one module cannot affect another (SAVEPOINT isolation).
- Modules can be developed, tested, and versioned independently.
- The orchestrator is the only code that knows about multiple modules.

### 6.3 Module Lifecycle

```
  Orchestrator discovers module
       │
       ▼
  create_module(config) → instance
       │
       ▼
  schema_migrations() → DDL SQL
       │
       ▼
  discover_files(raw_base) → [file_paths]
       │
       ▼
  For each file:
    _is_safe_path() → validates path
    extension check → .csv or .json only
    stability check → skip if modified < 60s ago
       │
       ▼
  parse(file_path) → [Events]
       │
       ▼
  insert_events_for_module() → SAVEPOINT wrapped
       │
       ▼
  post_ingest(db, affected_dates) → derived metrics
       │
       ▼
  update_module_status() → success/failed
```

### 6.4 Factory Pattern

Every module has a `create_module(config)` factory function in both `module.py` and `__init__.py`. The orchestrator imports from `modules.{name}.module`:

```python
mod = importlib.import_module(f"modules.{module_name}.module")
instance = mod.create_module(module_config)
```

### 6.5 Per-Metric Configurability

Every module supports a `disabled_metrics` list in `config.yaml`. This allows granular control over which metrics are collected and computed without disabling the entire module.

**Configuration:**

```yaml
modules:
  behavior:
    enabled: true
    disabled_metrics:
      - "behavior.derived:digital_restlessness"   # Exact match: disables only this metric
      - "device.derived"                           # Prefix match: disables ALL device.derived:* metrics
```

**Matching rules:**

- **Exact match:** `"behavior.derived:digital_restlessness"` disables only that specific metric.
- **Prefix match:** `"device.derived"` disables all metrics whose name starts with `device.derived:` (e.g., `device.derived:screen_time_minutes`, `device.derived:unlock_count`, etc.).
- **Default `[]`** means everything is enabled (backward compatible).

**How it works — two enforcement points:**

1. **`filter_events(events)`** — Called by the orchestrator after `parse()`. Removes raw events whose `source_module` matches any disabled metric pattern before database insertion. This is the parse-time gate.

2. **`is_metric_enabled("metric_name")`** — Called inside each module's `post_ingest()` method to guard derived metric computation. Every derived metric computation is wrapped:

```python
def post_ingest(self, db, affected_dates):
    for date_str in affected_dates:
        if self.is_metric_enabled("behavior.derived:digital_restlessness"):
            self._compute_digital_restlessness(db, date_str)
        if self.is_metric_enabled("behavior.derived:fragmentation_index"):
            self._compute_fragmentation(db, date_str)
```

**Startup validation:** The orchestrator validates all `disabled_metrics` names against the module's `get_metrics_manifest()`. Typos produce a warning in the log, preventing silent misconfiguration.

**Example — disable a single derived metric:**

```yaml
modules:
  behavior:
    enabled: true
    disabled_metrics:
      - "behavior.derived:digital_restlessness"
```

This keeps all behavior raw event parsing and all other derived metrics (fragmentation_index, movement_entropy, etc.) active, while skipping only the digital_restlessness computation in `post_ingest()`.

### 6.6 Schema Migrations

Modules that need custom database tables implement `schema_migrations()`, returning an ordered list of DDL SQL statements (CREATE TABLE, ALTER TABLE only). The framework tracks applied versions per module in the `schema_versions` table:

- Migrations are append-only: never reorder or modify existing entries.
- New migrations are appended to the end of the list.
- The orchestrator runs only migrations with version numbers higher than the last applied version.
- All migrations for a module run in an all-or-nothing transaction.

```python
def schema_migrations(self) -> list[str]:
    return [
        "CREATE TABLE IF NOT EXISTS my_module_cache (key TEXT PRIMARY KEY, value TEXT)",
        # Append new migrations here — never reorder above entries
    ]
```

---

## 7. Module Catalog

### 7.1 Device Module

**Purpose:** Phone hardware events from Tasker CSVs.

| Source Type | Event Type | Value | Confidence |
|-------------|-----------|-------|------------|
| `device.battery` | `pulse` | Battery % | 1.0 |
| `device.screen` | `screen_on`, `screen_off` | Battery % | 1.0 |
| `device.charging` | `charge_start`, `charge_stop` | Battery % | 1.0 |
| `device.bluetooth` | `bt_event` | on/off | 1.0 |

**Derived (post_ingest):**

| Derived Type | Metric | Method |
|-------------|--------|--------|
| `device.derived` | `unlock_count` | COUNT of screen_on events |
| `device.derived` | `screen_time_minutes` | Inter-unlock gap analysis (capped at 10 min/session, confidence=0.7) |
| `device.derived` | `charging_duration` | Charge start/stop pairing |
| `device.derived` | `battery_drain_rate` | %/hour during non-charging segments |

**Parser:** Handles both v3 (no timezone field) and v4 (with `%TIMEZONE`) CSV formats. Unresolved Tasker variables (`%TEMP`, `%MFREE`) detected and treated as missing.

---

### 7.2 Body Module

**Purpose:** Biometric and health tracking.

| Source Type | Event Types | Notes |
|-------------|------------|-------|
| `body.steps` | `step_count` | Hourly from Tasker |
| `body.heart_rate` | `measurement` | Samsung Health / sensors |
| `body.hrv` | `measurement` | Heart rate variability |
| `body.spo2` | `measurement` | Blood oxygen |
| `body.sleep` | `sleep_start`, `sleep_end` | Manual or app-tracked |
| `body.caffeine` | `intake` | mg consumed |
| `body.meal` | `logged` | Timing + notes |
| `body.vape` | `session` | Nicotine tracking |
| `body.exercise` | `session` | Type + duration |
| `body.pain` | `report` | Location + severity |
| `body.weight` | `measurement` | kg or lbs |
| `body.blood_pressure` | `measurement` | sys/dia |
| `body.water` | `intake` | ml consumed |
| `body.supplement` | `taken` | Name + dose |

**Derived:** `daily_step_total` (SUM), `caffeine_level` (pharmacokinetic decay with configurable half-life), `sleep_duration` (start/end pairing).

**Config:** `caffeine_half_life_hours` (default 5.0), `sleep_target_hours` (7.5), `step_goal` (8000).

---

### 7.3 Mind Module

**Purpose:** Subjective self-reported psychological state.

| Source Type | Event Type | Scale |
|-------------|-----------|-------|
| `mind.morning` | `assessment` | Composite JSON (mood, energy, sleep quality, dream recall) |
| `mind.evening` | `assessment` | Composite JSON (productivity, social, gratitude) |
| `mind.mood` | `check_in` | 1–10 |
| `mind.energy` | `check_in` | 1–10 |
| `mind.stress` | `check_in` | 1–10 |
| `mind.sleep` | `check_in` | 1–10 (quality) |
| `mind.productivity` | `check_in` | 1–10 |
| `mind.social_satisfaction` | `check_in` | 1–10 |

**Derived:**
- `subjective_day_score` — Weighted composite: mood(0.3) + energy(0.2) + productivity(0.2) + sleep(0.15) + stress_inverted(0.15)
- `mood_trend_7d` — 7-day rolling average
- `energy_stability` — Coefficient of variation (lower = more stable)

---

### 7.4 Environment Module

**Purpose:** External physical environment.

| Source Type | Event Type | Data |
|-------------|-----------|------|
| `environment.hourly` | `snapshot` | Temperature, humidity, pressure, wind, conditions |
| `environment.location` | `geofence` | Lat/lon with geofence name |
| `environment.astro` | `daily` | Sunrise, sunset, moon phase |
| `environment.pressure` | `local_barometer` | Phone barometer reading |
| `environment.light` | `lux_reading` | Ambient light sensor |
| `environment.emf` | `magnetometer` | EMF magnitude (microtesla) |

**Derived:** `daily_weather_composite`, `location_diversity` (unique locations at ~111m resolution), `astro_summary`.

**Config:** Three API keys (weather, AirNow, Ambee), home coordinates, sensor intervals.

---

### 7.5 Social Module

**Purpose:** Human interaction and digital communication.

| Source Type | Event Type | Data |
|-------------|-----------|------|
| `social.notification` | `received` | App name, category |
| `social.call` | `incoming`, `outgoing`, `missed` | Duration, contact hash |
| `social.sms` | `received`, `sent` | Contact hash (anonymized) |
| `social.app_usage` | `foreground` | App name, duration |
| `social.wifi` | `connected`, `disconnected` | Network name |

**Derived:**
- `density_score` — Weighted interaction: calls(3.0) + SMS(2.0) + notifications(0.1)
- `digital_hygiene` — Productive app % vs distraction apps
- `notification_load` — Notifications per active hour

**Config:** `anonymize_contacts: true` (SHA-256 hashes contact names).

---

### 7.6 World Module

**Purpose:** Global information environment.

| Source Type | Event Type | Data |
|-------------|-----------|------|
| `world.news` | `headline` | Title, source, category, VADER sentiment |
| `world.markets` | `indicator_name` | Bitcoin price, gas price |
| `world.rss` | `article` | Title, source, category |
| `world.gdelt` | `global_event` | URL, title, country, tone |

**Derived:** `news_sentiment_index` (daily average), `information_entropy` (Shannon entropy of topic distribution).

**Config:** NewsAPI key, EIA key, 3 RSS feeds.

---

### 7.7 Media Module

**Purpose:** Rich media metadata and transcription.

| Source Type | Event Type | Data |
|-------------|-----------|------|
| `media.voice` | `memo`, `dream_journal` | Duration, transcript (Whisper), sentiment |
| `media.photo` | `capture`, `document` | EXIF metadata, GPS, category |
| `media.video` | `clip` | Duration, thumbnail path |

**Derived:** `daily_media_count` (total + per-type breakdown).

**Config:** `whisper_model: "base"`, `auto_transcribe: true`, `photo_categories: [8 categories]`.

**Optional dependency:** OpenAI Whisper for voice transcription (not installed by default).

---

### 7.8 Meta Module

**Purpose:** System health monitoring. Does not parse external files — generates synthetic events.

| Check | Source Type | What It Measures |
|-------|-----------|-----------------|
| Completeness | `meta.completeness` | % of expected modules that produced events today |
| Quality | `meta.quality` | Count of data quality issues (nulls, outliers) |
| Storage | `meta.storage` | Database size in MB |
| Sync lag | `meta.sync` | Minutes since last Syncthing sync |
| Backup age | `meta.sync` | Hours since last database backup |
| Relay check | `meta.sync` | Syncthing relay enabled (should be false) |

**Submodules:** `completeness.py`, `quality.py`, `storage.py`, `sync.py` — each implements a single health check.

---

### 7.9 Cognition Module

**Purpose:** Objective cognitive performance probes.

| Source Type | Event Types | Measures |
|-------------|------------|----------|
| `cognition.reaction` | `simple_rt`, `choice_rt`, `go_nogo` + summaries | Reaction time in ms |
| `cognition.memory` | `digit_span_trial`, `digit_span` | Working memory capacity |
| `cognition.time` | `production`, `estimation` | Time perception accuracy |
| `cognition.typing` | `speed_test` | Words per minute, accuracy |

**Derived:**
- `daily_baseline` — Median simple RT + 7-day trend
- `cognitive_load_index` — Weighted z-score: RT(0.3) + memory(0.3) + time(0.2) + typing(0.2)
- `impairment_flag` — Binary: CLI > 2 sigma above 14-day baseline
- `peak_cognition_hour` — Best-performance hour (14-day rolling)
- `subjective_objective_gap` — Self-reported focus vs measured RT performance

**Config:** Trial counts, digit span parameters, `impairment_zscore_threshold: 2.0`, `baseline_window_days: 14`.

---

### 7.10 Behavior Module

**Purpose:** Digital behavior patterns and physical movement analysis. The most complex module (1,154 lines).

| Source Type | Event Types | Data |
|-------------|------------|------|
| `behavior.app_switch` | `transition` | From-app, to-app, dwell time |
| `behavior.unlock` | `latency` | Time from screen-on to first interaction (ms) |
| `behavior.steps` | `hourly_count` | Steps per hour |
| `behavior.dream` | `quick_capture`, `structured_recall` | Dream narrative, emotions, symbols |

**Derived (10 metrics — most of any module):**

| Metric | What It Measures |
|--------|-----------------|
| `fragmentation_index` | 0–100 scale of attention fragmentation (app switches / hour, normalized) |
| `daily_total` (steps) | Sum of hourly step counts |
| `movement_entropy` | Shannon entropy of step distribution across hours |
| `sedentary_bouts` | Count of 2+ hour stretches with <50 steps |
| `hourly_summary` (unlock) | Aggregated unlock latency statistics by hour |
| `dream_frequency` | Dreams per week (7-day rolling) |
| `digital_restlessness` | Composite z-score: frag_rate + unlock_count + screen_time |
| `attention_span_estimate` | Median app dwell time (seconds) |
| `morning_inertia_score` | Minutes from waking to first unlock |
| `behavioral_consistency` | Cosine similarity of hourly app-switch profile vs 14-day baseline |

**Config:** `fragmentation_ceiling: 60`, `min/max_dwell_sec`, `min/max_latency_ms`, `restlessness_threshold: 2.0`.

---

### 7.11 Oracle Module

**Purpose:** Esoteric data sources for pattern exploration.

| Source Type | Event Types | Data |
|-------------|------------|------|
| `oracle.iching` | `casting`, `moving_line` | Hexagram number, method, lines |
| `oracle.rng` | `hardware_sample`, `raw_batch` | Random bytes from `os.urandom()` |
| `oracle.schumann` | `measurement`, `excursion` | Frequency (Hz), amplitude |
| `oracle.planetary_hours` | `day_ruler`, `current_hour` | Planet name, hour boundaries |

**Derived:**
- `hexagram_frequency` — Distribution over 90-day window
- `entropy_test` — Chi-squared uniformity test (are castings truly random?)
- `daily_deviation` — z-score of daily RNG mean vs expected 127.5
- `daily_summary` (Schumann) — Mean/min/max frequency + excursion count
- `activity_by_planet` — Mood and energy averages during each planetary hour

**Config:** `iching_default_method: "coin"`, `rng_batch_size: 100`, `schumann_enabled: true`, `planetary_hours_enabled: true`.

---

## 8. Database Layer

### 8.1 Schema

```sql
-- Primary data table (all modules write here)
events (
    event_id TEXT PRIMARY KEY,      -- Deterministic UUID from SHA-256
    timestamp_utc TEXT NOT NULL,
    timestamp_local TEXT NOT NULL,
    timezone_offset TEXT NOT NULL,
    source_module TEXT NOT NULL,     -- "device.battery", "mind.mood", etc.
    event_type TEXT NOT NULL,        -- "pulse", "check_in", etc.
    value_numeric REAL,             -- 72.0 (battery), 7.0 (mood)
    value_text TEXT,                -- "Feeling good", headline text
    value_json TEXT,                -- Complex structured data
    tags TEXT,                      -- Comma-separated: "morning,quick"
    location_lat REAL,
    location_lon REAL,
    media_ref TEXT,                 -- FK to media table
    confidence REAL DEFAULT 1.0,    -- 0.0–1.0
    raw_source_id TEXT UNIQUE,      -- Deduplication hash
    parser_version TEXT,
    created_at TEXT NOT NULL
)
```

### 8.2 Transaction Model

```
Phase 1: Validate (Python-only, no DB calls)
  │  event.validate() for each event
  │  Collect valid tuples, log rejections
  │  Track affected_dates
  │
Phase 2: Batch insert (single executemany call)
  │
  SAVEPOINT sp_device
  │  executemany(INSERT OR REPLACE, all_valid_tuples)  ← one call, N rows
  RELEASE SAVEPOINT sp_device  ← success: all writes visible
  │  (or ROLLBACK TO sp_device ← failure: all writes discarded)
  │
  SAVEPOINT sp_body
  │  executemany(INSERT OR REPLACE, all_valid_tuples)
  RELEASE SAVEPOINT sp_body
  │
  COMMIT
```

### 8.3 FTS5 Full-Text Search

```sql
-- Virtual table synced with events via triggers
events_fts (event_id UNINDEXED, tags, value_text)

-- Auto-populated on INSERT
TRIGGER events_fts_insert AFTER INSERT ON events ...

-- Auto-cleaned on DELETE (handles INSERT OR REPLACE)
TRIGGER events_fts_delete AFTER DELETE ON events ...
```

---

## 9. Configuration System

### 9.1 Resolution Chain

```
config.yaml (YAML)
    │
    ▼
.env (API keys loaded via python-dotenv)
    │
    ▼
os.environ (${ENV_VAR} patterns resolved)
    │
    ▼
Pydantic schema validation (config_schema.py)
    │
    ▼
Semantic checks (paths exist, timezone valid, allowlist matches modules/)
    │
    ▼
RootConfig object (typed, validated)
```

### 9.2 Validation Pipeline (6 steps)

1. **Structural** — Pydantic model_validate (types, required fields, range validators)
2. **Path existence** — db_path, raw_base, media_base, reports_dir, log_path directories writable
3. **API key resolution** — Warn if enabled modules have empty/unresolved keys
4. **Syncthing relay** — Must be `false` (hard error if true)
5. **Module allowlist** — Every allowlisted name must have a `modules/{name}/module.py`
6. **Timezone** — Must be valid IANA timezone (checked via `zoneinfo.ZoneInfo`)

All errors collected into a single `ConfigValidationError` with a bulleted list — fix everything in one pass.

---

## 10. Analysis Engine

### 10.1 Correlator (`analysis/correlator.py`)

Computes pairwise Pearson and Spearman correlations between any two metric streams.

- **Resolution:** Daily aggregation (AVG of value_numeric per date)
- **Alignment:** Only dates where both metrics have data are included
- **Minimum data:** 7 co-occurring observations required
- **Lag analysis:** Test if metric A predicts metric B with a 1-3 day delay
- **Confidence tiers:** <14 observations = "exploratory", 14-29 = "preliminary", >=30 = "reliable"
- **Effect size:** |r| < 0.1 negligible, < 0.3 weak, < 0.5 moderate, < 0.7 strong, >= 0.7 very strong

The `run_correlation_matrix()` method pre-fetches each metric's daily series once (N database queries), then computes all pairwise correlations from the cached data (276 pairs for 24 metrics). This avoids redundant database queries — without caching, each metric would be fetched once per pair it appears in.

### 10.2 Anomaly Detector (`analysis/anomaly.py`)

Two detection modes:

**Single-metric z-score:** For each numeric metric, compare today's value to its 14-day baseline. Flag if |z| > 2.0 (configurable).

**Multi-variable pattern detection (9 patterns):**

| Pattern | Metrics Combined | Threshold |
|---------|-----------------|-----------|
| Heavy phone usage | Low battery + high screen events | <20% AND >50 unlocks |
| Sleep deprivation + stress | Short sleep + high stress | <6h AND >6/10 |
| Late caffeine + poor sleep | Afternoon caffeine + sleep quality | >0mg after 14:00 AND <5/10 |
| Low mood + social isolation | Mood + social density | <4/10 AND density <10 |
| High screen + low movement | Screen time + steps | >180min AND <3000 steps |
| Cognitive impairment + sleep | CLI + sleep duration | CLI >2.0 AND <6h |
| Digital restlessness + mood | Restlessness z-score + mood | z>2.0 AND mood <4/10 |
| Schumann excursion + mood swing | Schumann mean + mood range | >0.3 Hz deviation AND range >4 |
| Fragmentation + caffeine | App frag index + caffeine | frag >50 AND >300mg |

### 10.3 Hypothesis Testing (`analysis/hypothesis.py`)

10 pre-defined research questions tested against accumulating data:

1. Geomagnetic storms reduce mood (negative)
2. Morning light improves energy (positive)
3. Afternoon caffeine disrupts sleep (negative)
4. Social interaction improves next-day mood (positive)
5. High notifications reduce focus (negative)
6. Negative news predicts lower mood (positive)
7. Caffeine improves reaction time (negative — lower RT = better)
8. Sleep deprivation impairs cognition (negative)
9. Stress impairs working memory (negative)
10. Morning cognition predicts productivity (negative — lower RT = higher focus)

Each test uses `Correlator.correlate()` with a 90-day window, reports whether the hypothesis is supported at p < 0.05.

---

## 11. Report Generation

`analysis/reports.py` generates daily, weekly, and monthly markdown reports.

### 11.1 Daily Reports (`--report`)

Generated with `--report`, saved to `reports/daily/report_YYYY-MM-DD.md`. Sections:

1. **Data Summary** — Event counts by source module
2. **Metrics** — Avg/min/max for all numeric metrics
3. **Device** — Battery range, screen events, charging events
4. **Environment** — Temperature range, location fixes
5. **Social & Apps** — Interaction counts by type
6. **Cognition** — Reaction time, memory span, CLI, impairment flag
7. **Behavior** — Fragmentation, steps, attention span, restlessness, dreams
8. **Oracle** — I Ching castings, RNG deviation, Schumann resonance
9. **Trends** — 7-day sparkline charts for mood, steps, screen time, reaction time
10. **Anomalies Detected** — Z-score flags with human-readable descriptions
11. **Pattern Alerts** — Multi-variable compound patterns
12. **Module Status** — Success/failure for each module's last run

### 11.2 Weekly Reports (`--weekly-report`)

Generated with `--weekly-report`, saved to `reports/weekly/report_YYYY-MM-DD.md`. Aggregates the last 7 days with summary statistics per trend metric (avg, min, max, sparkline), module event counts, anomaly count, and hypothesis test results.

### 11.3 Monthly Reports (`--monthly-report`)

Generated with `--monthly-report`, saved to `reports/monthly/report_YYYY-MM-DD.md`. Same structure as weekly but covering a 30-day window.

Flags combine naturally: `python run_etl.py --report --weekly-report --monthly-report` generates all three report types in one run.

---

## 12. API Fetcher Scripts

| Script | API | Cron | Output | Rate Limit |
|--------|-----|------|--------|------------|
| `fetch_news.py` | NewsAPI | `0 */4 * * *` | `raw/api/news/headlines_*.json` | 100 req/day (uses 20) |
| `fetch_markets.py` | CoinGecko + EIA | `0 18 * * 1-5` | `raw/api/markets/markets_*.json` | No key needed (CoinGecko) |
| `fetch_rss.py` | RSS feeds | `0 */4 * * *` | `raw/api/rss/rss_*.json` | N/A (direct feed) |
| `fetch_gdelt.py` | GDELT Doc API | `0 6 * * *` | `raw/api/gdelt/gdelt_*.json` | Has built-in retry/backoff |
| `fetch_schumann.py` | HeartMath GCMS | `0 */1 * * *` | `raw/api/schumann/schumann_*.json` | No key needed |
| `compute_planetary_hours.py` | Astral library | `0 5 * * *` | `raw/api/planetary_hours/*.json` | Local computation |
| `process_sensors.py` | Sensor Logger CSVs | Manual/cron | `raw/api/sensors/*.json` | Local processing |

All HTTP-based scripts use `scripts/_http.retry_get()` for exponential backoff on 429/500/502/503/504 responses.

---

## 13. Security Model

### 13.1 Threat Surface

| Threat | Mitigation |
|--------|-----------|
| Path traversal via malformed filenames | `_is_safe_path()` with `Path.resolve().is_relative_to()` |
| SQL injection via module migrations | `execute_migration()` only allows CREATE/ALTER |
| SQL injection via module queries | `execute()` only allows SELECT/WITH/EXPLAIN/PRAGMA |
| Arbitrary code execution via rogue module | Module allowlist in config (fail-closed) |
| API key leakage in logs | `sanitizer.py` redacts 32+ char tokens |
| PII leakage in logs | GPS truncated, phones/emails redacted |
| Log injection via CSV data | Newlines stripped from all log messages |
| Data interception via Syncthing relay | Relay must be disabled (validated at startup + runtime) |
| Database exposure | chmod 0o600 on db, backup, log files |
| Concurrent ETL corruption | flock-based exclusive lock |
| Corrupt data from mid-sync files | 60-second file stability window |
| Disallowed file types | Extension whitelist: .csv, .json only |

### 13.2 Permission Model

| File/Directory | Permission | Enforced By |
|---------------|-----------|-------------|
| `.env` | 0o600 | Startup check (warning) |
| `config.yaml` | 0o600 or 0o644 | Startup check (warning) |
| `~/LifeData/` | 0o700 | Startup check (warning) |
| `db/lifedata.db` | 0o600 | Database.__init__() |
| `db/backups/` | 0o700 | Database.backup() |
| `db/backups/*.bak` | 0o600 | Database.backup() |
| `logs/etl.log` | 0o600 | setup_logging() |

---

## 14. Observability & Debugging

### 14.1 CLI Interface

```bash
python run_etl.py                          # Full ETL
python run_etl.py --report                 # ETL + daily report
python run_etl.py --weekly-report          # ETL + weekly report (last 7 days)
python run_etl.py --monthly-report         # ETL + monthly report (last 30 days)
python run_etl.py --module device          # Single module only
python run_etl.py --dry-run                # Parse without writing
python run_etl.py --dry-run --module body  # Parse one module, no writes
python run_etl.py --status                 # Health summary (last 7 runs)
python run_etl.py --trace <raw_source_id>  # Trace a single event
```

### 14.2 `--status` Output

Prints a table of recent runs with: date, duration, events ingested, failed modules, DB size, disk free. Plus per-module breakdown for the latest run and warnings for: module failures, DB >5GB, disk <20GB, event count drops >50%.

### 14.3 `--trace` Output

Given a `raw_source_id` (or prefix), shows:
- Full event record (all 17 fields)
- Inferred raw source file (searches `raw/` for matching date in filename)
- Parser version and source module
- Related daily summaries for that date + module
- Related correlations referencing that source module

### 14.4 Log Files

| File | Format | Contains |
|------|--------|---------|
| `logs/etl.log` | JSON-lines | Every log message with timestamp, level, module, message |
| `logs/metrics.jsonl` | JSON-lines | One entry per ETL run with full telemetry |

---

## 15. Cron Scheduling

```crontab
# Nightly ETL + report (11:55 PM)
55 23 * * * cd ~/LifeData && venv/bin/python run_etl.py --report

# Weekly report (Sunday midnight)
0 0 * * 0 cd ~/LifeData && venv/bin/python run_etl.py --weekly-report

# Monthly report (1st of month 2 AM)
0 2 1 * * cd ~/LifeData && venv/bin/python run_etl.py --monthly-report

# News headlines (every 4 hours)
0 */4 * * * cd ~/LifeData && venv/bin/python scripts/fetch_news.py

# RSS feeds (every 4 hours)
0 */4 * * * cd ~/LifeData && venv/bin/python scripts/fetch_rss.py

# Market data (6 PM weekdays)
0 18 * * 1-5 cd ~/LifeData && venv/bin/python scripts/fetch_markets.py

# GDELT global events (6 AM daily)
0 6 * * * cd ~/LifeData && venv/bin/python scripts/fetch_gdelt.py

# Schumann resonance (hourly)
0 */1 * * * cd ~/LifeData && venv/bin/python scripts/fetch_schumann.py

# Planetary hours (5 AM daily)
0 5 * * * cd ~/LifeData && venv/bin/python scripts/compute_planetary_hours.py

# Sensor processing (before nightly ETL)
50 23 * * * cd ~/LifeData && venv/bin/python scripts/process_sensors.py
```

---

## 16. Extension Guide

### Adding a New Module

1. Create `modules/<name>/module.py` implementing `ModuleInterface`
2. Create `modules/<name>/parsers.py` with row-level parser functions using `safe_parse_rows()`
3. Create `modules/<name>/__init__.py` with `create_module(config)` factory
4. Add `<name>` to `security.module_allowlist` in `config.yaml`
5. Add `<name>:` section under `modules:` in `config.yaml` with `enabled: true`
6. Add config model to `core/config_schema.py` if the module has custom config
7. Module must emit `Event` objects — the only interface with core

### Adding a New API Fetcher

1. Create `scripts/fetch_<name>.py`
2. Use `from scripts._http import retry_get` for HTTP calls
3. Write JSON output to `raw/api/<name>/`
4. Add cron entry to the schedule
5. Ensure the relevant module's `discover_files()` looks in `raw/api/<name>/`

### Adding a New Hypothesis

Add to the `hypotheses` list in `config.yaml` under `lifedata.analysis`:

```yaml
- name: "Human-readable hypothesis statement"
  metric_a: metric_a.source_module
  metric_b: metric_b.source_module
  direction: positive  # positive, negative, or any
  threshold: 0.05
  lag_days: 0          # 0-7, test delayed effects
```

### Adding a Correlation Metric

Add the `source_module` string to `weekly_correlation_metrics` in `config.yaml`.

---

## 17. Glossary

| Term | Definition |
|------|-----------|
| **Event** | The universal data unit. Every observation, measurement, or state change is an Event. |
| **Source module** | Dot-notation identifier for the origin of data: `device.battery`, `mind.mood`. |
| **Event type** | Subtype within a source module: `pulse`, `check_in`, `transition`. |
| **Raw source ID** | SHA-256 hash ensuring deduplication across ETL re-runs. |
| **SAVEPOINT** | SQLite transaction checkpoint. Each module's writes are isolated. |
| **Derived metric** | Computed by `post_ingest()` from raw events. Source modules end in `.derived`. |
| **Affected dates** | Set of dates that had new events ingested this run. Limits recomputation. |
| **Quarantine** | A file flagged when >50% of its rows fail parsing. Logged as WARNING. |
| **Confidence** | 0.0–1.0 score. 1.0 = direct measurement. 0.7 = estimate. 0.1 = unreliable. |
| **Module sovereignty** | No module imports or depends on another module. Communication via events table only. |
| **Fail-closed** | When in doubt, deny. Empty allowlist = no modules loaded (not all). |
| **Provenance** | Debug string stamped on every event: file, line, parser, version. Not stored in DB. |
| **CLI** (Cognitive Load Index) | Weighted composite z-score across cognitive probes. Higher = more impaired. |
| **Fragmentation index** | 0–100 scale of digital attention fragmentation. Higher = more app-switching. |
| **Digital restlessness** | Composite z-score of app switching, unlock frequency, and screen time volatility. |

---

*This document covers the complete LifeData V4 system as of v4.3.0.*
*Updated 2026-03-26 by Claude Opus 4.6 (1M context).*
