# LifeData V4 — User Guide

> **Your personal data observatory.** LifeData collects data from your phone, APIs, and sensors, transforms everything into universal events, and surfaces correlations, anomalies, and daily reports so you can understand your life through data.

---

## Quick Start

```bash
cd ~/LifeData
source venv/bin/activate

# Run the full pipeline
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
                                         v
                                  SQLite Database (events table)
                                         |
                                         v
                            Analysis (correlations, anomalies)
                                         |
                                         v
                              Daily Report (reports/daily/*.md)
```

**Three principles:**
1. **Local-first** — No cloud. No telemetry. Your data stays on your machine.
2. **Idempotent** — Re-running the ETL produces identical results. No duplicates ever.
3. **Module sovereignty** — Each data domain is independent. One module crashing cannot affect another.

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
HOME_LAT=32.78
HOME_LON=-96.80
```

Not all keys are required — modules gracefully skip if their key is missing.

---

## Running the ETL

### Commands

| Command | What It Does |
|---------|-------------|
| `python run_etl.py` | Full ETL (all modules) |
| `python run_etl.py --report` | ETL + generate daily report |
| `python run_etl.py --module device` | Run only one module |
| `python run_etl.py --dry-run` | Parse without writing to DB |
| `python run_etl.py --status` | Health summary (last 7 runs) |
| `python run_etl.py --trace <id>` | Trace a single event's full history |

### Using the Makefile

```bash
make etl          # Run ETL + report
make etl-dry      # Dry run
make test          # Run all tests
make test-cov      # Tests with coverage
make lint          # Run ruff linter
make typecheck     # Run mypy strict
make clean         # Remove __pycache__
```

### What Happens During a Run

1. Config loaded and validated (all errors reported at once)
2. Database backed up (safe SQLite `conn.backup()` API)
3. SQLite tuned (WAL, 40MB cache, memory-mapped I/O, NORMAL sync)
4. Modules discovered from allowlist
5. For each module: discover files, validate paths, parse, batch insert with `executemany()` under SAVEPOINT isolation
6. Derived metrics computed (only for dates with new data — `affected_dates` optimization)
7. Report generated (if `--report`)
8. Metrics written to `logs/metrics.jsonl`

---

## The 11 Modules

### Device

Phone hardware: battery levels, screen on/off, charging state, bluetooth.

**What Tasker logs:** Battery pulse every 15 min, screen state changes, charging events.
**Derived metrics:** Unlock count, screen time estimate, charging duration, battery drain rate.

### Body

Biometrics: steps, heart rate, sleep, caffeine, meals, exercise, supplements.

**Data sources:** Samsung Health exports, Tasker QuickLog entries, Sensor Logger.
**Derived metrics:** Daily step total, caffeine pharmacokinetic level (decaying model), sleep duration.
**Key config:** `caffeine_half_life_hours: 5.0`, `step_goal: 8000`, `sleep_target_hours: 7.5`.

### Mind

Subjective state: mood, energy, stress, productivity, sleep quality (1-10 scales).

**What Tasker logs:** Morning check-in (wake-up prompt), evening check-in (bedtime prompt).
**Derived metrics:** Subjective day score (weighted composite), mood 7-day trend, energy stability.

### Environment

Physical surroundings: weather, air quality, location, light, barometric pressure.

**Data sources:** OpenWeatherMap API, AirNow API, Tasker geofencing, Sensor Logger.
**Derived metrics:** Daily weather composite, location diversity, astronomical summary.

### Social

Human interaction: calls, SMS, notifications, app usage, WiFi.

**Privacy:** Contact names are SHA-256 hashed by default (`anonymize_contacts: true`).
**Derived metrics:** Social density score (weighted interactions), digital hygiene (productive vs distraction %), notification load (per hour).

### World

Global information: news headlines, market prices, RSS feeds, GDELT events.

**Data sources:** NewsAPI, CoinGecko, EIA, RSS feeds, GDELT Doc API.
**Derived metrics:** News sentiment index (daily VADER average), information entropy (topic diversity).

### Media

Rich media: voice memos, photos, video clips.

**Features:** EXIF extraction from photos, optional Whisper transcription for voice.
**Derived metrics:** Daily media count by type.

### Meta

System health monitor (no external files — generates synthetic events).

**Checks:** Data completeness, quality issues, storage usage, Syncthing sync lag, backup freshness, relay status.

### Cognition

Objective cognitive probes: reaction time, working memory, time perception, typing speed.

**Derived metrics:** Daily RT baseline, cognitive load index (weighted z-score), impairment flag (>2 sigma), peak cognition hour, subjective-objective gap.
**Key config:** `impairment_zscore_threshold: 2.0`, `baseline_window_days: 14`.

### Behavior

Digital behavior patterns: app switching, unlock latency, step distribution, dream journaling.

**Derived metrics (10 total):** Fragmentation index, movement entropy, sedentary bouts, dream frequency, digital restlessness, attention span, morning inertia, behavioral consistency.
**Key config:** `fragmentation_ceiling: 60`, `restlessness_threshold: 2.0`.

### Oracle

Esoteric data sources: I Ching castings, hardware RNG sampling, Schumann resonance, planetary hours.

**Derived metrics:** Hexagram frequency distribution, RNG deviation z-score, Schumann daily summary, mood/energy by planetary hour.

---

## Analysis & Reports

### Daily Reports

Generated with `--report`, saved to `reports/daily/report_YYYY-MM-DD.md`. Includes:

- Event counts by module
- Numeric metric summaries (avg/min/max)
- Device, environment, social, cognition, behavior, oracle breakdowns
- 7-day sparkline trends
- Z-score anomaly flags
- Multi-variable pattern alerts (e.g., "sleep deprivation + high stress = burnout risk")
- Module status table

### Anomaly Detection

Automatically flags when any metric deviates >2 sigma from its 14-day baseline. Also detects 9 compound patterns like:
- Heavy phone usage (low battery + high unlocks)
- Caffeine-sleep disruption (afternoon caffeine + poor sleep)
- Cognitive impairment + sleep deprivation

### Correlation Discovery

Computes Pearson and Spearman correlations between 24 configured metrics over a 30-day window. Confidence tiers: <14 days = exploratory, 14-29 = preliminary, 30+ = reliable.

### Hypothesis Testing

10 pre-defined research questions (e.g., "Does caffeine after 2 PM disrupt sleep?") tested automatically against accumulating data.

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

### Syncthing Setup

```
Phone: /Documents/LifeData/logs/  ──sync──>  Desktop: ~/LifeData/raw/LifeData/logs/
```

**Security requirements:**
- Disable relaying in Syncthing settings (device-to-device only)
- Record device fingerprints in `config.yaml`
- Meta module verifies relay status every ETL run

### API Fetcher Scripts

```bash
python scripts/fetch_news.py        # NewsAPI headlines
python scripts/fetch_markets.py     # Bitcoin + gas prices
python scripts/fetch_rss.py         # RSS feeds
python scripts/fetch_gdelt.py       # Global events
python scripts/fetch_schumann.py    # Schumann resonance
```

All scripts use automatic retry with exponential backoff on failures.

### Sensor Logger

For high-frequency phone sensor data (accelerometer, barometer, light, magnetometer):

```bash
# Process raw sensor CSVs into 5-minute summaries
python scripts/process_sensors.py

# Then run ETL to ingest the summaries
python run_etl.py
```

---

## Cron Schedule (Recommended)

```cron
# Nightly ETL + report
55 23 * * * cd ~/LifeData && venv/bin/python scripts/process_sensors.py && venv/bin/python run_etl.py --report

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

---

## Configuration

Master config: `~/LifeData/config.yaml`

### Key Settings

| Setting | Default | What It Does |
|---------|---------|-------------|
| `timezone` | `America/Chicago` | Local time for all timestamps |
| `file_stability_seconds` | `60` | Skip files modified within this window (mid-sync protection) |
| `anomaly_zscore_threshold` | `2.0` | Sensitivity for anomaly detection |
| `correlation_window_days` | `30` | Lookback window for correlations |
| `db_backup_keep_days` | `7` | Number of daily backups to retain |

### Enabling/Disabling Modules

```yaml
modules:
  device:
    enabled: true    # Set to false to skip this module

security:
  module_allowlist:
    - device         # Remove from list to prevent loading entirely
```

---

## Querying the Database

```bash
sqlite3 ~/LifeData/db/lifedata.db
```

### Useful Queries

```sql
-- Event counts by module
SELECT source_module, COUNT(*) FROM events GROUP BY source_module ORDER BY 2 DESC;

-- Today's timeline
SELECT substr(timestamp_local, 12, 5) as time, source_module, event_type,
       COALESCE(CAST(value_numeric AS TEXT), substr(value_text, 1, 40)) as value
FROM events WHERE date(timestamp_local) = date('now', '-5 hours')
ORDER BY timestamp_utc;

-- Search across all text data
SELECT * FROM events_fts WHERE events_fts MATCH 'caffeine';

-- Module status
SELECT module_id, version, last_status, last_run_utc FROM modules;

-- Last 7 days of mood
SELECT date(timestamp_local), AVG(value_numeric) FROM events
WHERE source_module = 'mind.mood' GROUP BY 1 ORDER BY 1 DESC LIMIT 7;
```

---

## Adding a New Module

1. Create `modules/<name>/module.py` — implement `ModuleInterface`
2. Create `modules/<name>/parsers.py` — use `safe_parse_rows()` for CSV parsing
3. Create `modules/<name>/__init__.py` — add `create_module(config)` factory
4. Add `<name>` to `security.module_allowlist` in `config.yaml`
5. Add `<name>:` config section with `enabled: true`
6. Module must emit `Event` objects — the only interface with the core system

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No modules loaded" | Check `module_allowlist` in config.yaml |
| "Module not in allowlist" | Add module name to the allowlist |
| ".env file not found" | Create `~/.LifeData/.env` with API keys, `chmod 600` |
| No events parsed | Check Syncthing sync: `ls -lt ~/LifeData/raw/LifeData/logs/` |
| Database locked | Don't run multiple ETL instances; check: `ps aux \| grep run_etl` |
| Sensor processing OOM | Use larger window: `--window 10` |
| Config validation error | All errors listed at once — fix them all in one pass |

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
```

---

## Security Checklist

- [ ] `.env` file is `chmod 600`
- [ ] `config.yaml` is `chmod 600`
- [ ] `~/LifeData/` directory is `chmod 700`
- [ ] Syncthing relaying is disabled
- [ ] Device fingerprints recorded in config
- [ ] Only trusted modules in `module_allowlist`
- [ ] Disk encryption enabled (LUKS recommended)

---

## File Structure

```
~/LifeData/
├── run_etl.py           # CLI entry point
├── config.yaml          # Master configuration
├── .env                 # API keys (chmod 600)
├── core/                # ETL engine
├── modules/             # 11 data modules
├── analysis/            # Correlation, anomaly, hypothesis, reports
├── scripts/             # API fetchers and sensor processor
├── tests/               # 605 tests
├── db/                  # SQLite database + backups
├── raw/                 # Source data (never modified)
├── media/               # Photos, video, voice
├── logs/                # ETL logs + metrics
└── reports/             # Generated daily reports
```

---

*LifeData V4 — All data local. All insights yours.*
