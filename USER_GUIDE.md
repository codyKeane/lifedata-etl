# LifeData V4 — User Guide

> **Your personal data observatory.** LifeData collects data from your phone, APIs, and sensors, transforms everything into universal events, and surfaces correlations, anomalies, and daily reports so you can understand your life through data. Every metric, every report section, and every analysis pattern is configurable — you control exactly what gets tracked, analyzed, and reported.

---

## Quick Start

```bash
cd ~/LifeData
source venv/bin/activate

# Run the full pipeline + generate daily report
python run_etl.py --report

# Check system health
python run_etl.py --status

# Trace a specific event
python run_etl.py --trace <raw_source_id>
```

---

## How It Works

```
  Phone (Tasker CSVs) ──Syncthing──> raw/LifeData/logs/
  API scripts (news, weather) ─────> raw/api/
  Sensor Logger app ──Syncthing────> raw/LifeData/logs/sensors/
                                         |
                                         v
                                  ETL Pipeline (nightly cron)
                                         |
              ┌──────────────────────────┼──────────────────────────┐
              v                          v                          v
    Parse → Filter by            Derived metrics            Schema migrations
    disabled_metrics           (only enabled ones)          (version-tracked)
              |                          |                          |
              v                          v                          v
       SQLite Database ─────> Analysis (correlations, anomalies) ──> Reports
                                                                       |
                                                  ┌────────────────────┼────────────┐
                                                  v                    v             v
                                           Daily Report       Weekly Report   Monthly Report
                                       (reports/daily/)    (reports/weekly/) (reports/monthly/)
```

**Four principles:**
1. **Local-first** — No cloud. No telemetry. Your data stays on your machine.
2. **Idempotent** — Re-running the ETL produces identical results. No duplicates ever.
3. **Module sovereignty** — Each data domain is independent. One module crashing cannot affect another.
4. **Configurable** — You choose which metrics to track, which analyses to run, and which reports to generate. Defaults are sensible; overrides are easy.

---

## Installation

### Prerequisites

- Python 3.11+
- Android phone with Tasker (for data collection)
- Syncthing (for phone-to-desktop file sync)

### Setup

```bash
# Clone and enter the project
cd ~/LifeData

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# For development (tests, linting, type checking)
pip install -r requirements-dev.txt

# Create your API key file
cp .env.example .env   # Then edit with your keys
chmod 600 .env
```

### API Keys (.env)

Create `~/LifeData/.env`:

```
WEATHER_API_KEY=your_openweathermap_key
AIRNOW_API_KEY=your_airnow_key
AMBEE_API_KEY=your_ambee_key
NEWS_API_KEY=your_newsapi_key
EIA_API_KEY=your_eia_gov_key
SYNCTHING_API_KEY=your_syncthing_key
PII_HMAC_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
HOME_LAT=32.78
HOME_LON=-96.80
```

**`PII_HMAC_KEY` is mandatory** — the social module will not load without it. Generate a unique key per installation; never reuse across machines.

Not all other keys are required — modules gracefully skip if their key is missing.

---

## Running the ETL

### Commands

| Command | What It Does |
|---------|-------------|
| `python run_etl.py` | Full ETL (all enabled modules) |
| `python run_etl.py --report` | ETL + generate daily report |
| `python run_etl.py --weekly-report` | ETL + generate weekly report (last 7 days) |
| `python run_etl.py --monthly-report` | ETL + generate monthly report (last 30 days) |
| `python run_etl.py --module device` | Run only one module |
| `python run_etl.py --dry-run` | Parse without writing to DB |
| `python run_etl.py --status` | Health summary (last 7 runs) |
| `python run_etl.py --trace <id>` | Trace a single event's full history |
| `python run_etl.py --config /path/to/config.yaml` | Use alternate config file |

Flags combine naturally: `python run_etl.py --report --weekly-report --monthly-report` generates all three report types in one run.

### Using the Makefile

```bash
make etl              # Run ETL + daily report
make etl-dry          # Dry run (parse only, no writes)
make status           # Health summary
make test             # Run all 1024 tests
make test-cov         # Tests with coverage report
make test-perf        # Performance benchmarks (longer timeout)
make test-integration # Integration tests
make lint             # Run ruff linter
make typecheck        # Run mypy strict on core/
make format           # Auto-format with ruff
make clean            # Remove __pycache__
```

### What Happens During a Run

1. Config loaded and validated (all errors reported at once)
2. Log rotation enforced (deletes logs older than `retention.log_rotation_days`)
3. Database backed up (safe SQLite `conn.backup()` API)
4. Schema migrations applied (version-tracked, only new ones run)
5. Modules discovered from allowlist, disabled_metrics validated against manifests
6. For each module: discover files, validate paths, parse, **filter by disabled_metrics**, batch insert with `executemany()` under SAVEPOINT isolation
7. Derived metrics computed (only for dates with new data, only for enabled metrics)
8. Reports generated (if `--report`, `--weekly-report`, or `--monthly-report`)
9. Metrics written to `logs/metrics.jsonl`

---

## The 11 Modules

Each module is sovereign — it owns its parsing, derived metrics, and failure modes. All modules support:
- `enabled: true/false` to enable or disable the entire module
- `disabled_metrics: [...]` to selectively disable individual metrics (see [Per-Metric Configurability](#per-metric-configurability))

### Device

Phone hardware: battery levels, screen on/off, charging state, bluetooth.

**What Tasker logs:** Battery pulse every 15 min, screen state changes, charging events.
**Derived metrics:** `unlock_count`, `screen_time_minutes`, `charging_duration`, `battery_drain_rate`.

### Body

Biometrics: steps, heart rate, sleep, caffeine, meals, exercise, supplements.

**Data sources:** Samsung Health exports, Tasker QuickLog entries, Sensor Logger.
**Derived metrics:** `daily_step_total`, `caffeine_level` (pharmacokinetic decay model), `sleep_duration`.
**Key config:** `caffeine_half_life_hours: 5.0`, `step_goal: 8000`, `sleep_target_hours: 7.5`.

### Mind

Subjective state: mood, energy, stress, productivity, sleep quality (1-10 scales).

**What Tasker logs:** Morning check-in (wake-up prompt), evening check-in (bedtime prompt).
**Derived metrics:** `subjective_day_score` (weighted composite), `mood_trend_7d`, `energy_stability`.
**Configurable weights:** The subjective day score weights default to `mood: 0.3, energy: 0.2, productivity: 0.2, sleep: 0.15, stress: 0.15` but can be overridden in config:
```yaml
mind:
  subjective_day_score_weights:
    mood: 0.4
    energy: 0.2
    productivity: 0.1
    sleep: 0.2
    stress: 0.1
```

### Environment

Physical surroundings: weather, air quality, location, light, barometric pressure.

**Data sources:** OpenWeatherMap API, AirNow API, Tasker geofencing, Sensor Logger.
**Derived metrics:** `daily_weather_composite`, `location_diversity`, `astro_summary`.

### Social

Human interaction: calls, SMS, notifications, app usage, WiFi.

**Privacy:** Contact names are HMAC-SHA256 hashed (requires `PII_HMAC_KEY` in `.env`).
**Derived metrics:** `density_score` (weighted interactions), `digital_hygiene` (productive vs distraction %), `notification_load` (per active hour).
**Configurable weights:** The density score weights default to `call: 3.0, sms: 2.0, notification: 0.1` but can be overridden:
```yaml
social:
  density_score_weights:
    call: 5.0
    sms: 3.0
    notification: 0.05
```

### World

Global information: news headlines, market prices, RSS feeds, GDELT events.

**Data sources:** NewsAPI, CoinGecko, EIA, RSS feeds (configurable), GDELT Doc API.
**Derived metrics:** `news_sentiment_index` (daily VADER average), `information_entropy` (topic diversity).
**RSS feeds are config-driven:**
```yaml
world:
  rss_feeds:
    - name: "Ars Technica"
      url: "https://feeds.arstechnica.com/arstechnica/index"
      category: "technology"
```

### Media

Rich media: voice memos, photos, video clips.

**Features:** EXIF extraction from photos, optional Whisper transcription for voice.
**Derived metrics:** `daily_media_count` by type.
**Key config:** `auto_transcribe: true`, `whisper_model: "base"`.

### Meta

System health monitor (no external files — generates synthetic events by inspecting the database and filesystem).

**Checks:** Data completeness, quality issues, storage usage, Syncthing sync lag, backup freshness, relay status.
**Each check is individually toggleable** via config booleans: `completeness_check`, `quality_check`, `storage_check`, `sync_lag_check`, `db_backup_check`, `syncthing_relay_check`.

### Cognition

Objective cognitive probes: reaction time, working memory, time perception, typing speed.

**Derived metrics:** `daily_baseline` (median RT), `cognitive_load_index` (weighted z-score), `impairment_flag` (>2 sigma), `peak_cognition_hour`, `subjective_objective_gap`.
**Key config:** `impairment_zscore_threshold: 2.0`, `baseline_window_days: 14`.
**Configurable weights:** Cognitive load index weights default to `rt: 0.3, memory: 0.3, time: 0.2, typing: 0.2`:
```yaml
cognition:
  cognitive_load_weights:
    rt: 0.4
    memory: 0.4
    time: 0.1
    typing: 0.1
```

### Behavior

Digital behavior patterns: app switching, unlock latency, step distribution, dream journaling.

**Derived metrics:** `fragmentation_index`, `movement_entropy`, `sedentary_bouts`, `dream_frequency`, `digital_restlessness`, `attention_span_estimate`, `morning_inertia_score`, `behavioral_consistency`.
**Key config:** `fragmentation_ceiling: 60`, `restlessness_threshold: 2.0`, `sedentary_min_bout_hours: 2`.

### Oracle

Esoteric data sources: I Ching castings, hardware RNG sampling, Schumann resonance, planetary hours.

**Derived metrics:** `hexagram_frequency`, `entropy_test` (chi-squared uniformity), `daily_deviation` (RNG z-score), `daily_summary` (Schumann Hz stats), `activity_by_planet`.
**Key config:** `analysis_window_days: 90`, `schumann_enabled: true`, `planetary_hours_enabled: true`.

---

## Configurability

LifeData is designed so you control exactly what gets tracked, analyzed, and reported — all through `config.yaml`.

### Per-Metric Configurability

Every module supports a `disabled_metrics` list. When a metric is disabled, it is not parsed from raw files and its derived computations are skipped entirely.

```yaml
modules:
  device:
    enabled: true
    disabled_metrics:
      - "device.derived:battery_drain_rate"    # Skip battery drain computation
      - "device.derived:charging_duration"     # Skip charging duration computation

  body:
    enabled: true
    disabled_metrics:
      - "body.derived:caffeine_level"          # Don't compute caffeine pharmacokinetics

  behavior:
    enabled: true
    disabled_metrics:
      - "behavior.derived"                     # Disable ALL behavior derived metrics (prefix match)
```

**How it works:**
- Exact match: `"device.derived:screen_time_minutes"` disables only that metric.
- Prefix match: `"device.derived"` disables all `device.derived:*` metrics at once.
- Default `[]` means everything is enabled (backward compatible).
- At startup, metric names are validated against the module's manifest — typos produce a warning in the log.

To see which metrics a module declares, check its `get_metrics_manifest()` output. Every metric has a `name` field using the pattern `source_module` or `source_module:event_type`.

### Enabling/Disabling Modules

Two levels of control:

```yaml
# Level 1: Allowlist — modules not listed here are never loaded (fail-closed)
security:
  module_allowlist:
    - device
    - body
    - mind
    # Remove a module from this list to prevent loading entirely

# Level 2: Enable flag — temporarily disable without removing from allowlist
modules:
  oracle:
    enabled: false    # Skipped this run but stays in allowlist
```

### Composite Score Weights

Three composite scores have configurable weights:

| Score | Module | Default Weights | Config Key |
|-------|--------|----------------|------------|
| Subjective Day Score | mind | mood=0.3, energy=0.2, productivity=0.2, sleep=0.15, stress=0.15 | `subjective_day_score_weights` |
| Social Density Score | social | call=3.0, sms=2.0, notification=0.1 | `density_score_weights` |
| Cognitive Load Index | cognition | rt=0.3, memory=0.3, time=0.2, typing=0.2 | `cognitive_load_weights` |

Override by adding the weight dict to the module's config section. Mind and cognition weights should sum to 1.0; social weights are relative multipliers.

---

## Analysis & Reports

### Daily Reports

Generated with `--report`, saved to `reports/daily/report_YYYY-MM-DD.md`. Includes:

- Event counts by module
- Numeric metric summaries (avg/min/max)
- Module-contributed daily summaries (from `get_daily_summary()`)
- 7-day sparkline trends for configured metrics
- Z-score anomaly flags (>2 sigma from 14-day baseline)
- Compound pattern alerts (config-driven, see below)
- Module health status table

### Weekly Reports

Generated with `--weekly-report`, saved to `reports/weekly/report_YYYY-MM-DD.md`. Aggregates the last 7 days:

- Summary statistics per trend metric (avg, min, max, sparkline)
- Module event counts over the period
- Total anomaly count
- Hypothesis test results

### Monthly Reports

Generated with `--monthly-report`, saved to `reports/monthly/report_YYYY-MM-DD.md`. Same structure as weekly but over 30 days.

### Configuring Report Content

```yaml
analysis:
  report:
    # Which metrics get sparkline trend visualization
    trend_metrics:
      - mind.mood
      - body.steps
      - device.derived:screen_time_minutes
      - cognition.reaction

    # Which module summaries appear in the report
    sections:
      - module: device
        enabled: true
      - module: body
        enabled: true
      - module: mind
        enabled: true
      - module: oracle
        enabled: false    # Hide oracle from reports
```

### Anomaly Detection

Automatically flags when any metric deviates >2 sigma from its 14-day baseline (configurable: `anomaly_zscore_threshold`).

Also evaluates compound patterns — multi-variable conditions that fire when ALL conditions are met on a given day. **Patterns are fully config-driven:**

```yaml
analysis:
  patterns:
    - name: heavy_phone_usage
      enabled: true
      description_template: "Low battery ({battery_avg:.0f}%) with high unlocks ({screen_events})"
      conditions:
        - metric: device.battery
          aggregate: AVG
          operator: "<"
          threshold: 20
        - metric: device.screen
          aggregate: COUNT
          operator: ">"
          threshold: 50
```

**9 patterns are pre-configured:** heavy phone usage, sleep deprivation + high stress, caffeine-sleep disruption, low mood + social isolation, high screen + low movement, cognitive impairment + sleep deprivation, digital restlessness + low mood, Schumann excursion + mood swing, fragmentation + caffeine spike.

Disable any pattern by setting `enabled: false`. Add your own by appending to the list.

**Supported condition fields:**
- `metric`: source_module name (e.g., `device.battery`, `body.derived`)
- `event_type`: optional filter within the metric
- `aggregate`: `AVG`, `SUM`, `COUNT`, `MIN`, `MAX`
- `operator`: `<`, `>`, `<=`, `>=`, `==`, `!=`
- `threshold`: numeric value
- `hour_filter`: optional time-of-day constraint (e.g., `">= 14"` for afternoon only)

### Correlation Discovery

Computes Pearson and Spearman correlations between configured metrics over a rolling window. Configuration:

```yaml
analysis:
  correlation_window_days: 30
  min_observations: 14
  min_confidence_for_correlation: 0.5
  weekly_correlation_metrics:
    - mind.mood
    - mind.energy
    - body.steps
    - body.caffeine
    # ... add or remove metrics as desired
```

Confidence tiers: <14 days = exploratory, 14-29 = preliminary, 30+ = reliable.

### Hypothesis Testing

Research questions tested automatically against accumulating data. **Hypotheses are config-driven:**

```yaml
analysis:
  hypotheses:
    - name: "Afternoon caffeine disrupts sleep"
      metric_a: body.caffeine
      metric_b: body.sleep_quality
      direction: negative        # Expect inverse correlation
      threshold: 0.05            # p-value threshold
      enabled: true

    - name: "Social interaction improves next-day mood"
      metric_a: social.density_score
      metric_b: mind.mood
      direction: positive
      enabled: true
```

10 hypotheses are pre-configured. Disable any with `enabled: false`. Add your own by appending to the list. Supported directions: `positive`, `negative`, `any`.

---

## Data Collection

### Tasker Setup (Android)

Each Tasker task appends to a daily CSV:

| Task | Trigger | Module |
|------|---------|--------|
| Battery Pulse | Every 15 min | device |
| Screen On/Off | Display state | device |
| Charging Log | Power connect/disconnect | device |
| Morning Check-in | First screen-on after 5 AM | mind |
| Evening Check-in | 10 PM or manual | mind |
| QuickLog | Manual widget button | body |
| Notification Log | Notification received | social |
| Call Log | Call event | social |
| Geofence Log | Location enter/exit | environment |
| Voice Recorder | Manual trigger | media |

See `docs/tasker/` for detailed task definitions and XML exports.

### Syncthing Setup

```
Phone: /Documents/LifeData/logs/  ──sync──>  Desktop: ~/LifeData/raw/LifeData/logs/
```

**Security requirements:**
- Disable relaying in Syncthing settings (device-to-device only)
- Record device fingerprints in `config.yaml`
- Meta module verifies relay status every ETL run
- Files modified within `file_stability_seconds` (default 60s) are skipped to avoid parsing mid-sync data

### API Fetcher Scripts

```bash
python scripts/fetch_news.py            # NewsAPI headlines (with VADER sentiment)
python scripts/fetch_markets.py         # Bitcoin + gas prices
python scripts/fetch_rss.py             # RSS feeds (config-driven list)
python scripts/fetch_gdelt.py           # Global events (with deduplication)
python scripts/fetch_schumann.py        # Schumann resonance
python scripts/compute_planetary_hours.py  # Planetary hours (uses astral library)
```

All scripts use automatic retry with exponential backoff on failures via shared `retry_get()`.

### Sensor Logger

For high-frequency phone sensor data (accelerometer, barometer, light, magnetometer):

```bash
# Process raw sensor CSVs into 5-minute summaries
python scripts/process_sensors.py

# Process a specific session
python scripts/process_sensors.py --input raw/LifeData/logs/sensors/session_001

# Custom aggregation window
python scripts/process_sensors.py --window 10

# Then run ETL to ingest the summaries
python run_etl.py
```

---

## Cron Schedule (Recommended)

```cron
# Nightly ETL + all reports
55 23 * * * cd ~/LifeData && venv/bin/python scripts/process_sensors.py && venv/bin/python run_etl.py --report

# Weekly report (Monday 1 AM)
0 1 * * 1 cd ~/LifeData && venv/bin/python run_etl.py --weekly-report

# Monthly report (1st of month 2 AM)
0 2 1 * * cd ~/LifeData && venv/bin/python run_etl.py --monthly-report

# API fetchers (every 4 hours)
0 */4 * * * cd ~/LifeData && venv/bin/python scripts/fetch_news.py
5 */4 * * * cd ~/LifeData && venv/bin/python scripts/fetch_markets.py
10 */4 * * * cd ~/LifeData && venv/bin/python scripts/fetch_rss.py

# Schumann resonance (hourly)
0 */1 * * * cd ~/LifeData && venv/bin/python scripts/fetch_schumann.py

# Planetary hours (daily at 5 AM)
0 5 * * * cd ~/LifeData && venv/bin/python scripts/compute_planetary_hours.py

# GDELT global events (daily at 6 AM)
0 6 * * * cd ~/LifeData && venv/bin/python scripts/fetch_gdelt.py
```

Schedule cron expressions are also documented in `config.yaml` under `schedule:` for reference.

---

## Data Retention

```yaml
retention:
  raw_files_days: 365          # Keep raw source files for 1 year
  log_rotation_days: 30        # Auto-delete logs older than 30 days
  parquet_archive_after_days: 90   # Archive threshold
  db_backup_keep_days: 7       # Keep 7 daily database backups
```

Log rotation is enforced automatically at every ETL startup — old `.log` and `.jsonl` files in the logs directory are deleted.

---

## Configuration Reference

Master config: `~/LifeData/config.yaml`

### Top-Level Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| `timezone` | `America/Chicago` | Local time for all timestamps |
| `db_path` | `~/LifeData/db/lifedata.db` | SQLite database location |
| `raw_base` | `~/LifeData/raw/LifeData` | Raw data root directory |
| `media_base` | `~/LifeData/media` | Media files directory |
| `reports_dir` | `~/LifeData/reports` | Generated reports directory |
| `log_path` | `~/LifeData/logs/etl.log` | ETL log file path |

### ETL Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| `file_stability_seconds` | `60` | Skip files modified within this window (mid-sync protection) |

### Analysis Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| `anomaly_zscore_threshold` | `2.0` | Sensitivity for z-score anomaly detection (0.5-5.0) |
| `correlation_window_days` | `30` | Lookback window for correlations (7-365) |
| `min_observations` | `14` | Minimum data points for reliable correlation (2-365) |
| `min_confidence_for_correlation` | `0.5` | Minimum event confidence to include (0.0-1.0) |
| `patterns` | 9 pre-defined | Compound anomaly pattern definitions (see [Anomaly Detection](#anomaly-detection)) |
| `hypotheses` | 10 pre-defined | Hypothesis test definitions (see [Hypothesis Testing](#hypothesis-testing)) |
| `report.trend_metrics` | 4 metrics | Metrics shown as sparkline trends in reports |
| `report.sections` | 9 modules | Which module summaries appear in reports |

---

## Querying the Database

```bash
sqlite3 ~/LifeData/db/lifedata.db
```

### Schema

Six tables:
- `events` — All data points (universal Event schema)
- `modules` — Module status and version tracking
- `media` — Media file metadata
- `daily_summaries` — Cached daily aggregates
- `correlations` — Correlation results
- `events_fts` — Full-text search index (FTS5)
- `schema_versions` — Migration version tracking per module

### Useful Queries

```sql
-- Event counts by module
SELECT source_module, COUNT(*) FROM events GROUP BY source_module ORDER BY 2 DESC;

-- Today's timeline
SELECT substr(timestamp_local, 12, 5) as time, source_module, event_type,
       COALESCE(CAST(value_numeric AS TEXT), substr(value_text, 1, 40)) as value
FROM events WHERE date(timestamp_local) = date('now', '-5 hours')
ORDER BY timestamp_utc;

-- Search across all text data (full-text search)
SELECT * FROM events_fts WHERE events_fts MATCH 'caffeine';

-- Module status
SELECT module_id, version, last_status, last_run_utc FROM modules;

-- Last 7 days of mood
SELECT date(timestamp_local), AVG(value_numeric) FROM events
WHERE source_module = 'mind.mood' GROUP BY 1 ORDER BY 1 DESC LIMIT 7;

-- Schema migration history
SELECT module_id, version, applied_at FROM schema_versions ORDER BY applied_at;

-- Derived metrics for a specific date
SELECT source_module, event_type, value_numeric, value_json
FROM events WHERE source_module LIKE '%.derived%'
  AND date(timestamp_local) = '2026-03-20';
```

---

## Adding a New Module

1. Create `modules/<name>/module.py` — implement `ModuleInterface` (required methods: `module_id`, `display_name`, `version`, `source_types`, `discover_files()`, `parse()`)
2. Create `modules/<name>/parsers.py` — use `safe_parse_rows()` for CSV parsing
3. Create `modules/<name>/__init__.py` — add `create_module(config)` factory
4. Implement `get_metrics_manifest()` — declare all metrics with `name`, `display_name`, `unit`, `aggregate`, `trend_eligible`, `anomaly_eligible`
5. Implement `post_ingest(db, affected_dates)` — compute derived metrics, guard each with `self.is_metric_enabled()`
6. Implement `get_daily_summary(db, date_str)` — return daily summary dict for reports
7. Add `<name>` to `security.module_allowlist` in `config.yaml`
8. Add `<name>:` config section with `enabled: true` and `disabled_metrics: []`
9. Add Pydantic config model to `core/config_schema.py` and wire into `ModulesConfig`
10. Module must emit `Event` objects — the only interface with the core system

If your module needs custom tables, implement `schema_migrations()` returning an ordered list of SQL DDL statements. The framework tracks versions automatically — append new migrations to the end, never reorder.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No modules loaded" | Check `module_allowlist` in config.yaml |
| "Module not in allowlist" | Add module name to the allowlist |
| ".env file not found" | Create `~/LifeData/.env` with API keys, `chmod 600` |
| "PII_HMAC_KEY not set" | Add `PII_HMAC_KEY=<hex>` to `.env` (required for social module) |
| No events parsed | Check Syncthing sync: `ls -lt ~/LifeData/raw/LifeData/logs/` |
| "disabled_metrics: 'X' not found" | Check spelling against the module's metrics manifest |
| Database locked | Don't run multiple ETL instances; check: `ps aux \| grep run_etl` |
| Sensor processing OOM | Use larger window: `--window 10` |
| Config validation error | All errors listed at once — fix them all in one pass |
| Report missing sections | Check `analysis.report.sections` — is the module `enabled: true`? |
| Weekly/monthly report empty | Reports aggregate daily data — ensure daily ETL has been running |

### Reading Logs

```bash
# Recent log entries (human-readable)
tail -20 ~/LifeData/logs/etl.log | python3 -c "
import sys, json
for line in sys.stdin:
    d = json.loads(line)
    print(f'{d[\"ts\"][:19]} [{d[\"level\"]:>7}] {d[\"module\"]}: {d[\"msg\"]}')
"

# Find errors only
grep '"ERROR"' ~/LifeData/logs/etl.log | python3 -m json.tool

# Check which metrics were filtered (disabled)
grep 'Filtered.*disabled metrics' ~/LifeData/logs/etl.log
```

---

## Security Checklist

- [ ] `.env` file is `chmod 600`
- [ ] `config.yaml` is `chmod 600`
- [ ] `~/LifeData/` directory is `chmod 700`
- [ ] `PII_HMAC_KEY` is set and unique to this installation
- [ ] Syncthing relaying is disabled
- [ ] Device fingerprints recorded in config
- [ ] Only trusted modules in `module_allowlist`
- [ ] Disk encryption enabled (LUKS recommended)

Startup security checks verify these automatically and log warnings for any failures.

---

## File Structure

```
~/LifeData/
├── run_etl.py           # CLI entry point (8 flags)
├── config.yaml          # Master configuration
├── .env                 # API keys (chmod 600)
├── .env.example         # Template for .env setup
├── core/                # ETL engine (orchestrator, database, event, config, logger, metrics)
├── modules/             # 11 sovereign data modules
├── analysis/            # Correlator, anomaly detector, hypothesis tester, reports, registry
├── scripts/             # 7 API fetchers + sensor processor
├── tests/               # 1024 tests (77% coverage)
├── db/                  # SQLite database + daily backups
├── raw/                 # Source data (never modified)
├── media/               # Photos, video, voice
├── logs/                # ETL logs + metrics (auto-rotated)
├── reports/
│   ├── daily/           # Daily reports (report_YYYY-MM-DD.md)
│   ├── weekly/          # Weekly reports
│   └── monthly/         # Monthly reports
├── docs/                # System walkthrough, threat model, audit report, baselines
└── legacy/              # V3 archive
```

---

*LifeData V4 — All data local. All insights yours. All metrics configurable.*
