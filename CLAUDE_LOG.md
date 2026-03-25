# CLAUDE_LOG.md — Session Log

## 2026-03-24 — Reliability Mechanisms: Lockfile, File Stability, Parser Degradation

**Task:** Implement three reliability mechanisms in the ETL pipeline and test them.

**Changes made:**

### 1. Lockfile with 5-second timeout (`run_etl.py`)
- Changed `_acquire_lock()` from non-blocking immediate fail to a retry loop with configurable `LOCK_TIMEOUT_SECONDS = 5`
- Retries every 0.25s until the timeout, then prints "ETL already running (lockfile held). Exiting." and `sys.exit(1)`
- Still uses `fcntl.flock` (crash-safe — lock released when fd closed), not PID files
- Exit code changed from 3 to 1

### 2. Configurable file stability check (`config_schema.py`, `config.yaml`, `orchestrator.py`)
- Added `EtlConfig` pydantic model with `file_stability_seconds: int = 60` (range 0–600)
- Added `etl` field to `LifeDataConfig` (defaults to 60s if section missing from YAML)
- Added `etl:` section to `config.yaml` with documentation
- Orchestrator now reads `self.config.lifedata.etl.file_stability_seconds` instead of hardcoded `FILE_STABILITY_SECONDS = 60`
- Setting to 0 effectively disables the check

### 3. Graceful parser degradation (`core/parser_utils.py`, `modules/device/parsers.py`, `orchestrator.py`)
- **New file `core/parser_utils.py`**: `safe_parse_rows(filepath, parse_fn, module_id) → ParseResult`
  - Iterates CSV rows, calls `parse_fn(fields, line_num)` per row
  - Catches exceptions per-row, logs filename/line_num/raw content (truncated 200 chars)/exception
  - Tracks skip count; quarantines file if >50% rows skipped
  - Returns `ParseResult(events, skipped, total_rows, quarantined, filepath)`
- **Refactored `modules/device/parsers.py`**: All 4 parsers (battery, screen, charging, bluetooth) now use `safe_parse_rows`
  - Row-level logic extracted to `_parse_*_row(fields, line_num) → Event | None`
  - Both `parse_*()` (returns `list[Event]`) and `parse_*_safe()` (returns `ParseResult`) APIs available
  - `SAFE_PARSER_REGISTRY` added alongside existing `PARSER_REGISTRY`
- **Device module** (`modules/device/module.py`): Uses `SAFE_PARSER_REGISTRY`, tracks `_quarantined_files`, exposes `quarantined_files` property
- **Orchestrator**: Collects quarantined files from modules into `all_quarantined` list, included in run summary as `quarantined_files`

### Tests (`tests/test_reliability.py` — 29 tests)

| Class | Tests | Coverage |
|---|---|---|
| `TestLockfileTimeout` | 4 | Successful acquisition, exit(1) on held lock, crash-safe fd close, exit message content |
| `TestFileStabilityConfig` | 7 | EtlConfig defaults/custom/zero/negative/over-600, LifeDataConfig integration, orchestrator uses config value |
| `TestSafeParseRows` | 11 | Happy path, None skip, exception skip, quarantine >50%, not quarantined at 50%, empty file, blank lines, list return, nonexistent file, filepath in result |
| `TestDeviceParsersSafeRefactor` | 7 | Battery/screen/charging/bluetooth v4, battery v3 unresolved vars, corrupt file, quarantine with crashing rows |
| `TestQuarantineInOrchestrator` | 1 | quarantined_files key present in summary |

**Updated:** `tests/test_etl_integration.py` — lockfile test updated for exit code 1 (was 3), timeout patched for fast tests.

**Test results:** 538/538 passed in 1.81s (29 new + 509 existing).

---

## 2026-03-24 — ETL Integration Tests

**Task:** Create `tests/test_etl_integration.py` — end-to-end tests that run the actual Orchestrator against synthetic data in temporary directories.

**Analysis:** No integration tests existed. The codebase had unit tests for parsers, events, and database, but nothing that exercised the full ETL pipeline end-to-end. The `Orchestrator.run()` method, module discovery, SAVEPOINT isolation, file stability checks, and lockfile concurrency guard were all untested at the integration level.

**Changes made:**
- Created `tests/test_etl_integration.py` with 8 tests across 6 test classes:

| Test Class | Test | What it verifies |
|---|---|---|
| `TestFullETLCycle` | `test_full_etl_cycle` | Creates tmp dir structure with device/environment/mind CSVs, runs Orchestrator, verifies event count, source_modules in DB, no duplicate raw_source_ids, modules table updated with last_run_utc and success status |
| `TestETLIdempotency` | `test_etl_idempotency` | Runs ETL twice on same data, verifies event count identical, event_ids identical (deterministic INSERT OR REPLACE) |
| `TestETLModuleIsolation` | `test_etl_module_isolation` | Patches environment module's discover_files to crash, verifies device events ingested successfully, environment marked failed in modules table, no environment events in DB |
| `TestETLRespectsAllowlist` | `test_etl_respects_allowlist` | Config has allowlist=["device"] only, places CSVs for device+environment+mind, verifies only device events in DB, environment never loaded |
| `TestETLSkipsUnstableFiles` | `test_etl_skips_unstable_files` | Sets screen CSV mtime to 5 seconds ago (within 60s stability window), verifies it was skipped while stable battery CSV was ingested |
| `TestETLLockfile` | `test_lockfile_prevents_concurrent_run` | Acquires flock, verifies second acquisition raises OSError |
| `TestETLLockfile` | `test_lockfile_released_after_completion` | Releases lock, verifies second acquisition succeeds |
| `TestETLLockfile` | `test_run_etl_lock_mechanism` | Tests actual `run_etl._acquire_lock()` function, verifies SystemExit(3) on concurrent attempt |

**Key implementation details:**
- Helper functions build a complete tmp LifeData directory (config.yaml, .env, raw/ tree with realistic CSVs)
- `_make_orchestrator()` patches `load_config` to use the test .env path
- Device post_ingest creates derived events (unlock_count, screen_time, battery_drain) — tests account for this
- Module isolation uses `unittest.mock.patch` at the class level since `Orchestrator.run()` re-discovers modules

**Test results:** 8/8 passed. Full suite: 509/509 passed in 0.53s.

---

## 2026-03-24 — Parser Tests for All Implemented Modules

**Task:** Create parser tests for every module with `parsers.py`, covering happy paths, malformed input, and timezone_offset verification.

**Analysis:** Found 4 existing test files (device, mind, social, environment) and 6 missing (body, world, media, behavior, cognition, oracle). Existing files also had gaps vs directives.

**Changes made:**
- Created 6 new test files: `tests/modules/{body,world,media,behavior,cognition,oracle}/test_parsers.py` with `__init__.py` files
- Updated `tests/modules/device/test_parsers.py`: added 5 tests (10-row happy path, truncated file, zero-byte file, missing columns, bad timestamp)
- Updated `tests/modules/environment/test_parsers.py`: added 3 sensor summary test classes (barometer, light, magnetometer) with timezone_offset verification
- Fixed `.gitignore`: changed `media/` to `/media/` so `tests/modules/media/` is not ignored

**Test coverage by module (new):**
- body: 10 parser functions → quicklog, samsung_health, sleep, reaction, movement/activity/pedometer summaries (39 tests)
- world: 4 parsers → news, markets, RSS, GDELT JSON (26 tests)
- media: 3 parsers → voice_meta, photo_meta, video_meta + media ID safety (23 tests)
- behavior: 5 parsers → app_transitions, unlock_latency, hourly_steps, dream_quicklog, dream_structured (37 tests)
- cognition: 7 parsers → simple_rt, choice_rt, gonogo, digit_span, time_production, time_estimation, typing_speed (36 tests)
- oracle: 6 parsers → iching_casting, iching_auto, rng_samples, rng_raw, schumann, planetary_hours (31 tests)

**Result:** 501 total tests pass in 0.44s. Commit `183f881` on `dev`.

---

## 2026-03-24 — Audit: Core Unit Tests vs Task Directives

**Task:** Re-analyze task directives for core unit tests against current repository state.

**Result:** No changes needed. All 27 directive-specified tests are implemented across `tests/core/test_event.py`, `tests/core/test_database.py`, and `tests/core/test_utils.py`. The implementation exceeds the spec with 124 total tests covering additional edge cases. All pass in 0.11s. Commit `ac8003d` ("test(core): comprehensive unit tests for event model, database, and utilities") already exists on `dev`.

---

## 2026-03-24 — Gap Analysis & Missing Unit Tests for Core Engine

**Task:** Compare requested unit test directives against existing test suite; add missing tests.

**Analysis:** Mapped all requested tests to existing code. Found 9 missing tests across 3 files:
- `test_event.py`: Missing `test_different_value_text_different_id` (value_text field change in dedup hash)
- `test_database.py`: Missing `test_insert_and_retrieve_event` (full round-trip), `test_replace_preserves_event_id`, `test_fts_search`, `test_concurrent_insert_no_deadlock`, `test_backup_creates_file`, `test_backup_prunes_old`
- `test_utils.py`: Missing `test_parse_timestamp_dst_spring_forward`, `test_parse_timestamp_dst_fall_back`

**Changes made:**
- Added 1 test to `tests/core/test_event.py` (TestEventDeduplication class)
- Added 6 tests to `tests/core/test_database.py` (new TestFTSSearch, TestConcurrentInsertSafety, TestBackup classes + 2 tests in TestInsertEvents)
- Added 2 tests to `tests/core/test_utils.py` (DST transition tests in TestParseTimestamp class)

**Result:** All 124 tests pass in 0.15s. All tests are fast (<1s) and isolated (no shared state).

---

## 2026-03-24 — Comprehensive Test Fixtures (conftest.py)

**Task:** Extend `tests/conftest.py` with comprehensive fixtures for the full test suite.

### Changes Made

1. **`tests/conftest.py`** — Added 5 new fixtures while preserving all existing ones:
   - **`sample_config`** — Returns a valid `LifeDataConfig` object pointing to `tmp_path` directories (db, raw, media, reports, logs). Includes a realistic `SecurityConfig` with module allowlist.
   - **`tmp_database`** — Creates a fresh SQLite database with full schema (events, modules, media, daily_summaries, correlations, events_fts). Asserts all tables exist. Tears down after use.
   - **`sample_events`** — Returns 20 realistic `Event` objects spanning multiple modules: 5 device.screen (on/off alternating, varying battery), 3 device.battery pulses (15 min apart with value_json), 3 environment.weather snapshots, 2 environment.geomagnetic (Kp=2 and Kp=5), 3 mind.mood check_ins (values 4, 7, 8), 2 social.notification, 1 body.caffeine intake, 1 mind.synchronicity with value_text. All timestamps within past week, America/Chicago timezone, `-0500` offset.
   - **`sample_csv_dir`** — Creates `raw/LifeData/LifeData/logs/` with: well-formed screen CSV (10 rows), well-formed battery CSV (5 rows), malformed/truncated CSV, future-timestamp CSV, empty-row CSV, non-UTF8 CSV, zero-byte file.
   - **`populated_database`** — Combines `tmp_database` + `sample_events`, inserts all 20 events, asserts insertion count, returns the Database.

2. Also added `QUICKLOG_CAFFEINE_LINES` and `QUICKLOG_MEAL_LINES` sample constants for body module parser tests.

### Test Results

- **262 tests pass** — no regressions from existing test suite
- All 20 sample events validated (`is_valid == True`)
- Timestamps verified: base `2026-03-20T13:00:00+00:00` UTC / `2026-03-20T08:00:00-05:00` local

---

## 2026-03-24 — Typed Config Validation with Pydantic

**Task:** Create `core/config.py` with `load_config()`, add syncthing relay hard error, update orchestrator to use typed config, add config tests.

### Changes Made

1. **`core/config.py`** (new) — Unified config loader with `load_config(path, env_path) -> RootConfig`. Consolidates .env loading, YAML parsing, `${ENV_VAR}` resolution, and pydantic validation into a single entry point. Moved `_resolve_env_vars()` from orchestrator to this module.

2. **`core/config_schema.py`** — Added Step 4: syncthing_relay_enabled=True raises hard error ("must never route through third-party relay servers"). Changed Step 3 (API key checks) from hard errors to warnings per directive ("warn, don't fail, since not all modules need all keys").

3. **`core/orchestrator.py`** — Replaced `yaml.safe_load` + manual validation with `load_config()`. Removed `_load_config()`, `_resolve_env_vars()`, `_resolve_env_var_match()` static methods and `_ENV_VAR_RE`. All config access now uses typed attributes (`self.config.lifedata.db_path`) instead of dict access (`self.config["lifedata"]["db_path"]`). Module configs converted to dicts via `.model_dump()` for backward compat with `create_module()` factories.

4. **`tests/core/test_config.py`** (new) — 8 tests covering: valid config loads, typed access works, missing required field raises, invalid timezone raises, syncthing relay=True raises, unresolved env var warns but doesn't crash, invalid path raises, nonexistent module in allowlist raises.

5. **`tests/core/test_orchestrator.py`** — Updated env var resolution tests to import from `core.config` instead of `Orchestrator`.

### Verification

- ✅ 262/262 tests pass (including 8 new config tests)
- ✅ ETL dry-run works end-to-end with typed config (`python run_etl.py --dry-run --module device` — 204 events parsed)
- ✅ API key warnings now non-blocking (was hard error, now logs warning)

---

## 2026-03-24 — Dependency Pinning, Makefile & Tool Config

**Task:** Audit all Python imports, update requirements files, add Makefile targets, create pyproject.toml.

### Import Audit Summary

Scanned 60 Python files across `core/`, `modules/`, `analysis/`, `scripts/`, and `run_etl.py`. Found 11 third-party packages (10 production + 1 optional):
- **Core:** pydantic, PyYAML, python-dotenv
- **API clients:** requests (+ certifi, charset-normalizer, idna, urllib3)
- **Data processing:** feedparser, sgmllib3k, Pillow, astral
- **Analysis:** numpy, scipy
- **NLP:** vaderSentiment
- **Optional:** openai-whisper (lazy-loaded)

### Changes Made

1. **`requirements.txt`** — Regrouped with standard comment headers: `# Core`, `# API clients`, `# Data processing`, `# Analysis`, `# NLP / Transcription`. All versions remain pinned with `==`.

2. **`requirements-dev.txt`** — Added missing tools: `pytest-cov==7.1.0`, `pytest-timeout==2.4.0`, `mypy==1.19.1`, `types-PyYAML==6.0.12.20250915`, `types-requests==2.32.4.20260324`. Retained existing tools (ruff, pyright, Pygments, pytest_tmp_files).

3. **`Makefile`** — Added missing targets: `test-cov`, `typecheck`, `etl` (with `--report`), `status`, `clean`. Updated `test` to include `--timeout=30`. Updated `lint`/`format` to scope to `core/ modules/ analysis/ scripts/`. Renamed `etl-dry-run` → `etl-dry`.

4. **`pyproject.toml`** — Created with ruff config (line-length=100, target-version=py311, select=E/F/W/I/UP/B/SIM), mypy config (strict for core/, warn_return_any=true), pytest config (testpaths=tests, timeout=30).

### Verification

- ✅ `pip install -r requirements.txt` — all deps already satisfied
- ✅ `pip install -r requirements-dev.txt` — all deps installed (new: pytest-cov, pytest-timeout, mypy, type stubs)
- ✅ All 11 Makefile targets expand correctly (`make -n`)
- ✅ `pyproject.toml` validates via `tomllib.load()`
- ✅ `ruff`, `mypy`, `pytest` all importable from venv

## 2026-03-24 — Git Repository Setup & Branch Structure

**Task:** Audit repo, create comprehensive `.gitignore`, set up branch structure, create CHANGELOG, commit on main, checkout dev.

### Changes Made

1. **`.gitignore`** — Updated to comprehensive exclusions: `*.env*`, `db/*.db`, `db/backups/`, `raw/`, `media/`, `venv/`, `logs/`, `__pycache__/`, `*.pyc`, `*.pyo`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`, `*.egg-info/`, `reports/`, `.stfolder/`, IDE/OS files.
2. **`CHANGELOG.md`** — Created with `[4.0.0] — Unreleased` section documenting v3→v4 migration, modular architecture, and security hardening.
3. **Git commit** — All source code committed on `main` as `dee4c91`: "feat: LifeData v4.0 — modular architecture with security hardening" (74 files, 14210 insertions).
4. **Branch structure** — Created `dev` branch and checked it out for subsequent work.

### Verification

- ✅ `git status` confirmed no `.env`, `db/`, `raw/`, or `media/` files staged before commit.
- ✅ Commit succeeded on `main` with 74 files changed.
- ✅ `dev` branch created and checked out — working tree clean.

---

## 2026-03-24 — Metrics Export & Status CLI

**Task:** Add lightweight metrics export after each ETL run, and a `--status` CLI command for health summaries.

### Changes Made

1. **`core/orchestrator.py`** — Added per-module metrics tracking (`events` and `errors` counts) during the ETL loop. Added `_write_metrics()` method that appends a JSON line to `~/LifeData/logs/metrics.jsonl` with: run timestamp, duration, events/errors per module, DB size, disk free space. Called at end of every `run()`.

2. **`run_etl.py`** — Added `--status` flag that reads the last 7 entries from `metrics.jsonl` and prints a formatted health summary table (run history, per-module breakdown from latest run, DB size, disk free). Includes warnings for low disk space (<1 GB) and error counts. Exits immediately without running ETL.

### Test Results

- **Dry-run metrics export:** ✅ Ran `--dry-run --module device` — metrics.jsonl created with correct JSON structure (timestamp, duration, events_per_module, errors_per_module, db_size_bytes, disk_free_bytes).
- **Multi-entry status table:** ✅ Ran 3 dry-run ETLs (device, body, mind) — `--status` correctly shows all 3 rows with accurate counts.
- **Edge cases verified:** `logs/` already in `.gitignore`. `os.makedirs` ensures `logs/` dir exists.

---

## 2026-03-24 — Robustness Audit & Hardening

**Task:** Audit every module's parse() and the orchestrator's run loop for failure modes; add flock lockfile, file-stability checks, and fix unguarded post_ingest().

### Audit Findings

| Failure Mode | Prior Handling | Risk |
|---|---|---|
| Half-written CSV (Syncthing mid-sync) | None — parsers read whatever's there | Corrupt/truncated data silently ingested |
| DB locked by another process | 5s `busy_timeout`, then OperationalError | Module marked failed, acceptable |
| Overlapping cron runs | None | Two writers can corrupt DB or double-ingest |
| Disk full during write | SQLite raises OperationalError | Caught per-module, acceptable |
| `post_ingest()` crash | **No try-except** — crashes orchestrator | Previously-inserted events are safe (SAVEPOINT released), but remaining modules skipped |
| File-open errors in CSV parsers | Not caught at parser level | Caught by orchestrator's per-file try-except — acceptable |

### Changes Made

1. **`run_etl.py`** — Added `flock`-based lockfile (`~/.etl.lock`). Uses `fcntl.LOCK_EX | fcntl.LOCK_NB` for non-blocking exclusive lock. Writes PID for debugging. Exit code 3 if lock held by another process. Lock released in `finally` block. Lock file added to `.gitignore`.

2. **`core/orchestrator.py`** — Added file-stability check: files modified within the last 60 seconds (`FILE_STABILITY_SECONDS`) are skipped during the safe-files filtering loop. Uses `os.path.getmtime()` vs `time.time()`. Handles `OSError` (file disappeared between discover and stat). Log message reports count of deferred files.

3. **`core/orchestrator.py`** — Wrapped `module.post_ingest(self.db)` in try-except. A post_ingest hook crash now logs an error but does not prevent remaining modules from running or undo already-inserted events.

4. **`.gitignore`** — Added `.etl.lock`.

### Test Results
- **flock test:** Lock acquired, second acquisition correctly blocked with OSError, cleanup verified.
- **File stability test:** Fresh file correctly identified as unstable (age < 60s).
- **Import/source test:** Orchestrator imports clean; `post_ingest() failed` error path confirmed in source.
- **ETL dry-run:** Starts and acquires lock; fails at config validation (expected — no .env in test env); lock file cleaned up on exit.

---

## 2026-03-24 — Dependency Audit & Build Tooling

**Task:** Audit all Python imports, generate pinned requirements.txt and requirements-dev.txt, add Makefile.

### Import Audit Results
Third-party packages actually imported across the codebase:
- `python-dotenv`, `PyYAML` — core engine
- `requests`, `feedparser` — HTTP & feeds (scripts, modules)
- `scipy`, `numpy` — analysis engine
- `vaderSentiment` — NLP sentiment
- `Pillow` — EXIF extraction
- `astral` — sunrise/sunset, planetary hours
- `pytest`, `pytest_tmp_files` — tests only

### Files Created/Updated
- **`requirements.txt`** — Updated: added `astral==3.2` and all transitive deps (`certifi`, `charset-normalizer`, `idna`, `urllib3`, `sgmllib3k`) with pinned versions from venv.
- **`requirements-dev.txt`** — New: extends requirements.txt, adds `pytest==9.0.2`, `pytest_tmp_files==0.0.2`, `ruff==0.11.4`, `pyright==1.1.398`, `Pygments==2.19.2`.
- **`Makefile`** — New: targets `install`, `install-dev`, `test`, `lint`, `format`, `etl`, `etl-dry-run`.

### Formatting & Lint Fixes
- `make format` auto-fixed 60 ruff errors (unused imports, formatting).
- Manually fixed 4 remaining: removed unused `prev_ts_utc`/`prev_ts_local` variables in `modules/behavior/parsers.py`, renamed ambiguous `l` → `line` in `modules/environment/parsers.py` and `modules/social/parsers.py`.

### Test Results
- `make install-dev` — OK, all packages installed.
- `make test` — **254 passed** in 0.32s.
- `make format` / `ruff check` — **All checks passed** (0 errors).
- `make lint` (pyright) — 66 pre-existing type errors across analysis/ and tests/ (not introduced by this session).

---

## 2026-03-24 — Pytest Test Suite Creation

**Task:** Generate comprehensive pytest test suite covering Event model, module parsers, database SAVEPOINT rollback, dedup determinism, and completeness checker.

### Files Created/Modified

| File | Tests | Covers |
|------|-------|--------|
| `tests/core/test_database.py` | 20 | Schema, INSERT/dedup, SAVEPOINT rollback, migration DDL safety, queries, summaries, module status |
| `tests/core/test_utils.py` | 30 | `parse_timestamp` (epoch/ISO/local), `safe_float/int/json`, `glob_files` traversal, `format_offset` |
| `tests/core/test_orchestrator.py` | 14 | `_is_safe_path` traversal blocking, `_resolve_env_vars` substitution |
| `tests/modules/device/test_parsers.py` | 22 | Battery v3/v4, screen, charging, bluetooth; malformed CSV; dedup determinism |
| `tests/modules/mind/test_parsers.py` | 19 | Morning/evening check-in; manual vs auto; non-numeric scores; dedup |
| `tests/modules/environment/test_parsers.py` | 16 | Hourly (multi-line WiFi), geofence (GPS), astro (moon); dedup |
| `tests/modules/social/test_parsers.py` | 28 | Notifications, calls, SMS, app_usage, WiFi; PII hashing; dedup |
| `tests/modules/meta/test_completeness.py` | 9 | Empty/full/partial data completeness; required/optional source checks |
| `tests/analysis/test_anomaly.py` | 13 | Z-score detection, threshold tuning, pattern anomalies, severity labels |

### Test Run Result
```
254 passed in 0.24s
```

All 254 tests pass. Key coverage areas:
- **Event model**: 31 validation edge cases (empty fields, boundary confidence, oversized payloads, invalid JSON, dot-notation enforcement)
- **Deduplication**: Same input → same event_id across runs verified for every parser
- **SAVEPOINT rollback**: Module B crash doesn't affect module A's committed data
- **Parser malformed input**: Empty files, too-few fields, non-epoch headers, unresolved Tasker variables (%TEMP, %MFREE, %CDUR)
- **Security**: Path traversal blocked, symlink escape blocked, DDL-only migrations (DROP/DELETE/INSERT rejected), SQL injection in ORDER BY falls back safely
- **PII**: Contact/phone hashing deterministic, normalization tested, Tasker variables return "unknown"

## 2026-03-24 — Codebase Audit & Action Plan

**Task:** Full codebase examination and CLAUDE_GO.md creation.

**Actions taken:**
1. Explored all core files (orchestrator, database, event, module_interface, logger, utils) — all fully implemented
2. Explored all 8 modules (device, body, mind, environment, social, world, media, meta) — all fully implemented with working parsers
3. Explored analysis layer (correlator, anomaly, hypothesis, reports) — all functional
4. Explored all 5 data collection scripts — all functional
5. Queried live database: 4,783 events across 47 source_module types, 2 days of data
6. Read all 3 unimplemented module specs: NU (Cognition), XI (Oracle), OMICRON (Behavior)
7. Inventoried raw data directory: 69 files across Tasker CSVs, Sensor Logger sessions, and API JSON
8. Created `CLAUDE_GO.md` — 20-agent framework across 5 phases
9. Added `CLAUDE_GO.md` to `.gitignore`

**Result:** Action plan complete. All existing code is production-ready. Three new modules specified but unimplemented. Four existing modules have stub `post_ingest()` methods. Plan covers 20 subagent tasks across 5 phases.

---

## 2026-03-24 01:01–01:07 — Phase 0: Hardening & Polish

**Task:** Implement all 4 Phase 0 agents — fill in `post_ingest()` stubs and add compound anomaly patterns.

### Agent 0A: Device `post_ingest()` — `modules/device/module.py`

**Implemented:** 4 derived metrics per day, computed across all dates with device data.

| Metric | Type | Method |
|--------|------|--------|
| `unlock_count` | COUNT of screen_on events | Direct query |
| `screen_time_minutes` | Estimated active screen time | Inter-unlock gap, 10-min cap per session |
| `charging_duration` | Total minutes on charger | Paired charge_start/charge_stop events |
| `battery_drain_rate` | Avg %/hour drain | Battery pulse diffs, excluding charging intervals |

**Test:** `python run_etl.py --module device`
- Result: 8 derived events inserted (4 metrics × 2 days: 2026-03-22, 2026-03-23)
- 2026-03-22: 42 unlocks, 264.5 min screen, 15.4 min charging (+25%), 5.78%/hr drain
- 2026-03-23: 21 unlocks, 141.8 min screen, 31.7 min charging (+58%), 5.74%/hr drain
- Idempotency verified: re-run produces identical results via INSERT OR REPLACE

### Agent 0B: Mind `post_ingest()` — `modules/mind/module.py`

**Implemented:** 3 derived metrics per day (when data permits).

| Metric | Type | Method |
|--------|------|--------|
| `subjective_day_score` | Weighted composite (0-10) | mood×0.3 + energy×0.2 + productivity×0.2 + sleep×0.15 + stress(inv)×0.15 |
| `mood_trend_7d` | 7-day rolling average | Daily mood AVG over trailing 7 days |
| `energy_stability` | Coefficient of variation % | stdev/mean of daily energy over 7 days (needs ≥2 days) |

**Test:** `python run_etl.py --module mind`
- Result: 2 derived events (day_score=6.31, mood_trend=6.0) for 2026-03-23
- energy_stability correctly skipped (only 1 day of energy data, needs ≥2)
- Idempotency verified

### Agent 0C: Social `post_ingest()` — `modules/social/module.py`

**Implemented:** 3 derived metrics per day.

| Metric | Type | Method |
|--------|------|--------|
| `density_score` | Weighted interaction score | calls×3 + sms×2 + notifications×0.1 |
| `digital_hygiene` | Productive app % | Keyword classification of app foreground events |
| `notification_load` | Notifications/hour | Total notifications ÷ active hours (first-to-last span) |

**Test:** `python run_etl.py --module social`
- Result: 6 derived events (3 metrics × 2 days)
- 2026-03-22: density=154.2, hygiene=30.8%, load=84.0/hr
- 2026-03-23: density=101.2, hygiene=25.9%, load=129.9/hr
- Idempotency verified

### Agent 0D: Compound Anomaly Patterns — `analysis/anomaly.py`

**Implemented:** 4 new compound patterns in `check_pattern_anomalies()`, plus enhanced `_get_daily_metric()` with `event_type` and `aggregate` params, plus new `_get_late_caffeine()` helper.

| Pattern | Trigger Condition | Risk |
|---------|-------------------|------|
| `sleep_deprivation_high_stress` | sleep < 6h AND stress > 6/10 | Burnout |
| `caffeine_late_poor_sleep` | caffeine after 14:00 AND sleep quality < 5/10 | Sleep disruption |
| `low_mood_social_isolation` | mood < 4/10 AND density < 10 | Mental health |
| `high_screen_low_movement` | screen > 180 min AND steps < 3000 | Sedentary |

**Test:** Ran anomaly detector against both dates.
- 2026-03-22: `high_screen_low_movement` triggered (264 min screen, 2600 steps)
- 2026-03-23: No patterns triggered (thresholds not met)
- All 4 patterns handle missing data gracefully (None checks)

### Full ETL Verification

**Test:** `python run_etl.py --report`
- All 8 modules loaded and ran successfully
- 5,607 total events ingested, 0 skipped, 0 failed modules
- All derived metrics computed: 8 device + 2 mind + 6 social = 16 new derived events
- Daily report generated: `reports/daily/report_2026-03-24.md`
- **Phase 0 complete.** All 4 agents implemented and tested.

---

## 2026-03-24 — Tasker Task Workflow Documentation

**Task:** Create all remaining Tasker task definitions for 3 unimplemented modules (Cognition/NU, Behavior/OMICRON, Oracle/XI).

**Actions taken:**
1. Read all 3 module specs: `LD_MODULE_NU_V4.md` (695 lines), `LD_MODULE_OMICRON_V4.md` (717 lines), `LD_MODULE_XI_V4.md` (796 lines)
2. Read USER_GUIDE.md Section 8.1 to inventory existing Tasker tasks (11 already implemented)
3. Identified 15 new tasks across 3 modules
4. Categorized tasks: 10 XML-expressible (no custom scenes) + 5 requiring manual scene creation
5. Created `TASKER_XML_LIST.md` — importable Tasker XML for 10 tasks + 5 profiles + spool directory setup task
6. Created `TASKER_WRITTEN_LIST.md` — step-by-step manual instructions for 5 scene-dependent tasks + deployment checklist

**Note:** `TASKER_CREATION_WORKFLOW.md` (referenced by user) does not exist in the project.

### Documents Created

| File | Contents | Tasks Covered |
|------|----------|---------------|
| `TASKER_XML_LIST.md` | Importable XML code blocks | 310, 330, 340, 350, 351, 352, 360, 370, 380, 381 + 5 profiles + setup task |
| `TASKER_WRITTEN_LIST.md` | Manual scene + task creation steps | 300, 301, 302, 320, 321 + scene reference + deployment checklist |

### Task Inventory (15 total)

**Cognition (NU) — 8 tasks:**
- 300: Simple_RT (written — needs FullscreenColor scene)
- 301: Choice_RT (written — needs ChoiceRT scene)
- 302: Go_NoGo (written — needs GoNoGoScene)
- 310: Digit_Span (XML)
- 320: Time_Production (written — needs TimerScene)
- 321: Time_Estimation (written — needs TimedDisplay scene)
- 330: Typing_Speed_Test (XML)
- 340: Cognitive_Battery (XML — chains 300+310+320+330)

**Behavior (OMICRON) — 4 tasks:**
- 360: Log_Unlock_Latency (XML + manual profile: LD_UnlockLatency)
- 370: Log_Steps_Hourly (XML + manual profile: LD_Steps)
- 380: Dream_Quick_Log (XML + optional profile: LD_DreamPrompt)
- 381: Dream_Structured_Recall (XML)

**Oracle (XI) — 3 tasks:**
- 350: IChing_Cast (XML)
- 351: RNG_Sample (XML + manual profile: LD_RNG)
- 352: IChing_Auto (XML + manual profile: LD_IChing_Daily)

**Excluded:** Tasks 311, 312, 322, 331 (marked "future" in specs — not primary deployment tasks)

**Result:** Both documents created successfully. No code to test (documentation only).

---

## 2026-03-24 — Tasker XML Files (Corrected Format)

**Task:** Create individual `.tsk.xml` files matching the exact Tasker v6.7.0-beta export format found in `CORRECT_XML/`.

**Actions taken:**
1. Read 13 reference XML files from `CORRECT_XML/` to extract exact format patterns
2. Identified critical format differences from initial attempt: action codes, arg signatures, Bundle structures, single-line JS, priority, naming convention
3. Deleted all incorrectly formatted files
4. Rewrote all 11 XML files from scratch in correct format

### Files Created (`xml-attempts/`)

| File | Task ID | Module | Pattern |
|------|---------|--------|---------|
| `Digit_Span.tsk.xml` | 310 | Cognition | JS staircase + Input Dialog loop + Goto |
| `Typing_Speed.tsk.xml` | 330 | Cognition | JS timing + Input Dialog + Write |
| `Cognitive_Battery.tsk.xml` | 340 | Cognition | Perform Task chaining (4 sub-tasks) |
| `IChing_Cast.tsk.xml` | 350 | Oracle | 2 Input Dialogs + King Wen JS + If/EndIf |
| `RNG_Sample.tsk.xml` | 351 | Oracle | SecureRandom Java interop + 2 Write Files |
| `IChing_Auto.tsk.xml` | 352 | Oracle | Silent coin sim JS + Write |
| `Log_Unlock_Latency.tsk.xml` | 360 | Behavior | Variable Set + Wait + JS latency calc + If/Stop |
| `Log_Steps_Hourly.tsk.xml` | 370 | Behavior | Sensor JS (TYPE_STEP_COUNTER) + delta calc |
| `Dream_Quick_Log.tsk.xml` | 380 | Behavior | 3 Input Dialogs + theme detection JS |
| `Dream_Structured_Recall.tsk.xml` | 381 | Behavior | 5 Input Dialogs + Variable Set + Write |
| `LD_Init_Spool.tsk.xml` | 999 | Setup | 3 Write File (.keep) for spool dirs |

### Format Corrections Applied
- Header: `dvi="1" tv="6.7.0-beta"` (was missing `dvi`)
- Naming: `TaskName.tsk.xml` (was `Task_ID_Name.xml`)
- Priority: `<pri>6</pri>` (was `100`)
- Input Dialog: code 360 with Bundle/RELEVANT_VARIABLES (was code 545)
- Variable Set: code 547, args 0-6 with empty `<Int sr="arg5"/>` (was incomplete)
- Flash: code 548, full args 0-15 (was args 0-1 only)
- Wait: code 30, 5 args with empty `<Int sr="argN"/>` (was incomplete)
- JavaScriptlet: single-line compact JS, self-closing `<Str sr="arg1" ve="3"/>` (was multi-line)
- No XML comments (reference files have none)

**Result:** All 11 files validated against reference format. Ready for Tasker import.

---

## 2026-03-24 01:55–01:58 — Phase 1: Cognition Module (NU)

**Task:** Implement the full Cognition module per `LD_MODULE_NU_V4.md` — scaffold, parsers, derived metrics, and hypotheses.

### Agent 1A: Module Scaffold

**Created:**
- `modules/cognition/__init__.py` — factory function
- `modules/cognition/module.py` — `CognitionModule` implementing `ModuleInterface`
- `modules/cognition/parsers.py` — 7 parsers + `PARSER_REGISTRY`
- Updated `config.yaml` — added `cognition` to allowlist + module config section

**Test:** `python run_etl.py --module cognition --dry-run`
- Result: Module loaded successfully, 0 events (no data files yet)

### Agent 1B: Cognition Parsers — 7 CSV Parsers

| Parser | CSV Prefix | source_module | event_type | Events/File |
|--------|-----------|---------------|------------|-------------|
| `parse_simple_rt` | `simple_rt_` | cognition.reaction | simple_rt + simple_rt_summary | 3 trials + 1 summary |
| `parse_choice_rt` | `choice_rt_` | cognition.reaction | choice_rt + choice_rt_summary | 5 trials + 1 summary |
| `parse_gonogo` | `gonogo_` | cognition.reaction | go_nogo + gonogo_summary | 10 trials + 1 summary |
| `parse_digit_span` | `digit_span_` | cognition.memory | digit_span_trial + digit_span | N trials + 1 max span |
| `parse_time_production` | `time_prod_` | cognition.time | production | 1 per trial |
| `parse_time_estimation` | `time_est_` | cognition.time | estimation | 1 per trial |
| `parse_typing_speed` | `typing_` | cognition.typing | speed_test | 1 per session |

**Test:** Created 8 fixture CSVs in `raw/LifeData/spool/cognition/`
- `python run_etl.py --module cognition --dry-run` → 47 events parsed from 8 files
- `python run_etl.py --module cognition` → 47 events ingested + 3 derived metrics
- Idempotency verified: re-run produces 48 total (no duplicates)

### Agent 1C: Post-Ingest Derived Metrics

| Metric | source_module | event_type | Trigger Condition |
|--------|---------------|------------|-------------------|
| Daily RT baseline | cognition.reaction.derived | daily_baseline | Any simple_rt data for day |
| Cognitive load index | cognition.derived | cognitive_load_index | ≥1 probe type + 3+ days baseline |
| Impairment flag | cognition.derived | impairment_flag | CLI + 3+ days CLI history |
| Peak cognition hour | cognition.derived | peak_cognition_hour | 3+ RTs per hour band in 14-day window |
| Subjective-objective gap | cognition.derived | subjective_objective_gap | Mind + cognition data same day |

**Test:** Added 3 more days of simple_rt fixtures (5 days total across 2024-03-25 to 2024-03-29)
- 10 derived events produced: 5 daily_baseline + 4 cognitive_load_index + 1 peak_cognition_hour
- Day 5 (impaired data: ~350ms RT): CLI=3.887 — correctly flags high impairment
- Impairment flag, peak_hour, and gap correctly require more baseline data before triggering
- 78 total cognition events in DB

### Agent 1D: Cognition Hypotheses

Added 4 hypotheses to `analysis/hypothesis.py` (10 total):

| Hypothesis | Metric A | Metric B | Direction |
|-----------|----------|----------|-----------|
| Caffeine improves reaction time within 2 hours | body.caffeine | cognition.reaction | negative |
| Sleep deprivation impairs cognitive load index | body.sleep | cognition.derived | negative |
| High stress correlates with impaired working memory | mind.stress | cognition.memory | negative |
| Morning cognition scores predict self-reported productivity | cognition.reaction | mind.focus | negative |

**Test:** All 10 hypotheses load correctly. Full ETL with `--report`:
- All 9 modules loaded successfully (body, cognition, device, environment, media, meta, mind, social, world)
- 5,678 total events ingested, 0 skipped, 0 failed modules
- Report generated: `reports/daily/report_2026-03-24.md`
- **Phase 1 complete.**

---

## 2026-03-24 02:06–02:07 — Phase 2: Behavior Module (OMICRON)

**Task:** Implement the full Behavior module per `LD_MODULE_OMICRON_V4.md` — scaffold, parsers, derived metrics.

### Agent 2A: Module Scaffold + Config

**Created:**
- `modules/behavior/__init__.py` — factory function
- `modules/behavior/module.py` — `BehaviorModule` implementing `ModuleInterface`
- `modules/behavior/parsers.py` — 5 parsers + `SPOOL_PARSER_REGISTRY`
- Updated `config.yaml` — added `behavior` to allowlist + module config section

**Test:** `python run_etl.py --module behavior --dry-run`
- Result: Module loaded, found 2 app_usage files, 391 transition events parsed

### Agent 2B: App Transition Parser

**Implemented:** `parse_app_transitions()` — reprocesses existing `logs/apps/app_usage_*.csv` to extract app-to-app transitions with dwell times.

| Filter | Value | Rationale |
|--------|-------|-----------|
| Min dwell | 1 sec | Sub-second = screen flicker |
| Max dwell | 3600 sec | >1hr = phone was idle/locked |
| Same-app skip | Yes | Self-transitions aren't context switches |
| Syncthing conflicts | Skipped | `.sync-conflict-*` files excluded |

**Test:** 363 + 28 = 391 transitions parsed from 2 existing app_usage CSVs (zero phone-side changes needed)

### Agent 2C: Unlock, Steps, Dream Parsers

**Implemented:** 4 additional parsers in `parsers.py`:

| Parser | CSV Prefix | source_module | event_type | Confidence |
|--------|-----------|---------------|------------|------------|
| `parse_unlock_latency` | `unlock_` | behavior.unlock | latency | 0.9 |
| `parse_hourly_steps` | `steps_` | behavior.steps | hourly_count | 0.85 |
| `parse_dream_quicklog` | `dream_` | behavior.dream | quick_capture | 1.0 |
| `parse_dream_structured` | `dream_detail_` | behavior.dream | structured_recall | 0.8 |

**Created 6 fixture CSVs** in `raw/LifeData/spool/behavior/`:
- 2 unlock files (10 + 7 readings across 2 days)
- 2 steps files (22 + 14 hourly readings across 2 days)
- 1 dream quick-log (vividness=7, "flying over ocean; old house on cliff")
- 1 dream structured recall (coastal cliff setting, mom + old man characters)

**Test:** `python run_etl.py --module behavior --dry-run` → 446 events from 8 files

### Agent 2D: Post-Ingest Derived Metrics

**Implemented:** 11 derived metric types in `post_ingest()`:

| Metric | source_module | event_type | Computation |
|--------|---------------|------------|-------------|
| Hourly rate | behavior.app_switch | hourly_rate | COUNT per hour band |
| Fragmentation index | behavior.app_switch.derived | fragmentation_index | rate×0.4 + inv_dwell×0.3 + entropy×0.3 |
| Daily total | behavior.steps | daily_total | SUM hourly steps + goal% |
| Movement entropy | behavior.steps.derived | movement_entropy | Shannon entropy of hourly distribution (0-1) |
| Sedentary bouts | behavior.steps.derived | sedentary_bouts | Consecutive hours < 50 steps during 6-23h |
| Unlock summary | behavior.unlock | hourly_summary | mean/std/fastest/slowest latency |
| Dream frequency | behavior.dream.derived | dream_frequency | Rolling 7-day dream count |
| Attention span | behavior.derived | attention_span_estimate | Median dwell excluding calls/media/launcher |
| Morning inertia | behavior.derived | morning_inertia_score | Minutes from first screen_on to first productive app |
| Digital restlessness | behavior.derived | digital_restlessness | Z-scored composite: frag×0.4 + unlocks×0.3 + screen×0.3 |
| Behavioral consistency | behavior.derived | behavioral_consistency | RMSE of today's hourly profile vs 14-day baseline |

**Bug fix:** SQL subquery in `_compute_behavioral_consistency` referenced outer column name — fixed by aliasing the subquery as `sub`.

**Test:** `python run_etl.py --module behavior`
- 446 raw events + 32 derived events = 478 total behavior events
- Key values (2026-03-22): fragmentation=54.8, steps=6490, entropy=0.83, 2 sedentary bouts, mean unlock=1628ms, attention=15s, inertia=0.4min
- Key values (2026-03-23): fragmentation=28.7, steps=4982, entropy=0.83, 1 sedentary bout, mean unlock=1566ms, attention=9s, inertia=237.3min
- Behavioral consistency=20.19 (day 2 vs day 1 baseline)
- Idempotency verified: re-run produces identical results

### Full ETL Verification

**Test:** `python run_etl.py --report`
- All 10 modules loaded and ran successfully (behavior, body, cognition, device, environment, media, meta, mind, social, world)
- 6,124 total events ingested, 0 skipped, 0 failed modules
- All derived metrics computed: 32 behavior + 8 device + 10 cognition + 2 mind + 6 social + 2 world = 60 derived events
- Daily report generated: `reports/daily/report_2026-03-24.md`
- **Phase 2 complete.**

---

## 2026-03-24 02:20–02:25 — Phase 3: Oracle Module (XI)

**Task:** Implement the full Oracle module per `LD_MODULE_XI_V4.md` — scaffold, parsers for all 4 source types, derived metrics, and data collection scripts.

### Agent 3A: Module Scaffold + Config

**Created:**
- `modules/oracle/__init__.py` — factory function
- `modules/oracle/module.py` — `OracleModule` implementing `ModuleInterface`
- `modules/oracle/parsers.py` — 6 parsers + `PARSER_REGISTRY`
- Updated `config.yaml` — added `oracle` to allowlist + module config section

**Test:** `python run_etl.py --module oracle --dry-run`
- Result: Module loaded successfully, 0 events (no data files yet)

### Agent 3B: I Ching Parsers

**Implemented:** 2 parsers for I Ching data.

| Parser | CSV Prefix | source_module | event_type | Confidence |
|--------|-----------|---------------|------------|------------|
| `parse_iching_casting` | `iching_` (not auto) | oracle.iching | casting + moving_line | 1.0 |
| `parse_iching_auto` | `iching_auto_` | oracle.iching | casting (tagged automated) | 1.0 |

**Features:**
- King Wen sequence lookup (64 hexagrams) with full name dictionary
- Three casting methods: coin, yarrow, rng
- Moving line detection: generates separate `moving_line` events for each changing line
- Question hashing (SHA-256) for privacy-preserving correlation
- Supports both pipe-delimited and comma-delimited line values

**Test fixtures:** 2 interactive castings + 2 auto castings across 2 days
- Hex 1 (Force) with 2 moving lines → 3 events (1 casting + 2 moving_line)
- Hex 29 (Gorge) with 1 moving line → 2 events
- Hex 51 (Shake) auto with 1 moving line → 1 event (auto casts skip moving_line detail)
- Hex 11 (Pervading) auto, no moving lines → 1 event

### Agent 3C: RNG, Schumann, Planetary Hours Parsers + Scripts

**Implemented:** 4 additional parsers.

| Parser | File Pattern | source_module | event_type | Confidence |
|--------|-------------|---------------|------------|------------|
| `parse_rng_samples` | `rng_*.csv` | oracle.rng | hardware_sample | 1.0 |
| `parse_rng_raw` | `rng_raw_*.csv` | oracle.rng | raw_batch | 1.0 |
| `parse_schumann` | `schumann_*.json` | oracle.schumann | measurement + excursion | 0.7 |
| `parse_planetary_hours` | `hours_*.json` | oracle.planetary_hours | current_hour + day_ruler | 1.0 |

**Scripts created:**
- `scripts/fetch_schumann.py` — Scrapes HeartMath GCMS for Schumann resonance data (hourly cron). Fails gracefully when sources unavailable.
- `scripts/compute_planetary_hours.py` — Deterministic planetary hour computation using `astral` library. Computes 24 unequal hours from sunrise/sunset. Daily cron at 4 AM.

**Test fixtures:** 16 RNG samples (8/day), 2 raw batches, 16 Schumann measurements (8/day), 2 planetary hour sets (24 hours each)

**Test:** `python run_etl.py --module oracle --dry-run` → 91 events from 12 files

### Agent 3D: Post-Ingest Derived Metrics

**Implemented:** 5 derived metric types in `post_ingest()`:

| Metric | source_module | event_type | Computation |
|--------|---------------|------------|-------------|
| Hexagram frequency | oracle.iching.derived | hexagram_frequency | Distribution over rolling window |
| Entropy test | oracle.iching.derived | entropy_test | Chi-squared uniformity test (needs ≥10 castings) |
| RNG daily deviation | oracle.rng.derived | daily_deviation | Z-score of daily mean vs expected 127.5 |
| Schumann daily summary | oracle.schumann.derived | daily_summary | Mean/min/max Hz + excursion count |
| Activity by planet | oracle.planetary_hours.derived | activity_by_planet | Cross-module event counts + mood/energy per planet |

**Key values:**
- RNG 2026-03-22: z=-0.77, p=0.44 (normal variation)
- RNG 2026-03-23: z=0.17, p=0.87 (normal variation)
- Schumann 2026-03-22: mean=7.96 Hz, 0 excursions
- Schumann 2026-03-23: mean=7.70 Hz, 0 excursions
- Hexagram frequency: 4 unique hexagrams in 4 castings (uniform so far)
- Entropy test: not triggered (needs ≥10 castings)
- Activity by planet: all 7 planets tracked, event counts ranging 0–617 per planet per day

**Bug fix:** `hexagram_frequency` and `entropy_test` initially used `datetime.now()` timestamps, breaking idempotency. Fixed to use deterministic timestamps from latest data date.

**Test:** `python run_etl.py --module oracle`
- 91 raw events + 8 derived events = 99 total (before today's planetary hours)
- Idempotency verified: re-run produces 99 → 99 (identical)

### Full ETL Verification

**Test:** `python run_etl.py --report`
- All 11 modules loaded and ran successfully (behavior, body, cognition, device, environment, media, meta, mind, oracle, social, world)
- 6,357 total events in database, 0 skipped, 0 failed modules
- Oracle events: 126 total (100 raw + 9 derived + 17 from today's planetary hours)
- All derived metrics computed: 32 behavior + 8 device + 10 cognition + 2 mind + 9 oracle + 6 social + 2 world = 75 total derived events
- Daily report generated: `reports/daily/report_2026-03-24.md`
- **Phase 3 complete.**

---

## 2026-03-24 03:00 — Phase 4: Cross-Cutting Enhancements

**Task:** Implement all 4 Phase 4 agents — correlation expansion, report enhancement, cross-module anomalies, environment post_ingest.

### Agent 4A: Correlation Metric Expansion — `config.yaml`

**Implemented:** Added 8 new metrics to `weekly_correlation_metrics` (16 → 24 total).

| Category | Metrics Added |
|----------|--------------|
| Cognition | `cognition.reaction`, `cognition.memory`, `cognition.derived` |
| Behavior | `behavior.app_switch`, `behavior.steps`, `behavior.derived` |
| Oracle | `oracle.rng`, `oracle.schumann` |

**Test:** Config loads correctly with 24 metrics. Correlator handles all pairs.

### Agent 4B: Report Enhancement — `analysis/reports.py`

**Implemented:** 4 new sections + sparkline helper.

| Section | Content | Data Source |
|---------|---------|-------------|
| Cognition | Avg RT, memory span, CLI, impairment flag | cognition.* |
| Behavior | Fragmentation, steps, attention, restlessness, dreams | behavior.* |
| Oracle | I Ching count, RNG deviation, Schumann Hz | oracle.* |
| Trends | 7-day Unicode sparklines for key metrics | cross-module |

**Sparkline function:** `_sparkline(values)` maps floats to Unicode blocks ` ▁▂▃▄▅▆▇█`.

**Test:** Report generated. Steps and screen time sparklines render correctly. New sections conditionally omitted for dates without data.

### Agent 4C: Cross-Module Anomaly Patterns — `analysis/anomaly.py`

**Implemented:** 4 new patterns + 2 helper methods.

| Pattern | Modules | Trigger |
|---------|---------|---------|
| `cognitive_impairment_sleep_deprivation` | cognition × body | CLI > 2.0 AND sleep < 6h |
| `digital_restlessness_low_mood` | behavior × mind | restlessness > 2σ AND mood < 4 |
| `schumann_excursion_mood_swing` | oracle × mind | |sch - 7.83| > 0.3 AND mood range > 4 |
| `fragmentation_caffeine_spike` | behavior × body | frag > 50 AND caffeine > 300mg |

**Test:** All 9 patterns (5 old + 4 new) execute without errors. New patterns handle missing data gracefully.

### Agent 4D: Environment `post_ingest()` — `modules/environment/module.py`

**Implemented:** 3 derived metrics per day.

| Metric | event_type | Computation |
|--------|-----------|-------------|
| Weather composite | `daily_weather_composite` | Temp range/avg from hourly JSON, humidity, pressure |
| Location diversity | `location_diversity` | Unique lat/lon at ~111m resolution |
| Astro summary | `astro_summary` | Moon phase + illumination % |

**Test:** 5 derived events across 2 days. Idempotency verified.

### Full ETL Verification

**Test:** `python run_etl.py --report`
- All 11 modules loaded and ran successfully
- 6,791 total events in database, 0 skipped, 0 failed modules
- All derived metrics: 32 behavior + 8 device + 10 cognition + 5 environment + 2 mind + 9 oracle + 6 social + 2 world + 2 media + 6 body = **84 total derived events**
- Report with Trends sparklines generated: `reports/daily/report_2026-03-24.md`
- Idempotency verified: re-run produces same derived event count
- **Phase 4 complete. All 20 agents across 5 phases implemented and tested.**

---

## 2026-03-24 — Cross-Module Anomaly Patterns Addition

**Task:** Add 4 new cross-module anomaly patterns to `analysis/anomaly.py` in `check_pattern_anomalies()`.

**Actions taken:**
1. Read existing `analysis/anomaly.py` — 5 patterns already present
2. Added 4 new patterns + 2 helper methods (`_get_schumann_mean`, `_get_mood_range`)

### New Patterns Added

| Pattern | Modules | Trigger Condition |
|---------|---------|-------------------|
| `cognitive_impairment_sleep_deprivation` | cognition × body | CLI > 2.0 AND sleep < 6.0h |
| `digital_restlessness_low_mood` | behavior × mind | restlessness > 2.0 AND mood < 4 |
| `schumann_excursion_mood_swing` | oracle × mind | abs(schumann - 7.83) > 0.3 AND mood range > 4 |
| `fragmentation_caffeine_spike` | behavior × body | fragmentation > 50 AND caffeine > 300mg |

### Helper Methods Added

| Method | Purpose |
|--------|---------|
| `_get_schumann_mean(date_str)` | AVG value_numeric from oracle.schumann for date |
| `_get_mood_range(date_str)` | MAX - MIN value_numeric from mind.mood for date |

**Test:** `python -c "..."` with dates 2026-03-22 and 2026-03-23
- 2026-03-22: 1 pattern triggered (high_screen_low_movement — existing pattern)
- 2026-03-23: 0 patterns triggered
- All 9 patterns (5 old + 4 new) execute without errors
- New patterns correctly return None when data is missing (no exceptions)

---

## 2026-03-24 02:58 — Environment `post_ingest()` Implementation

**Task:** Implement `post_ingest()` for the environment module (`modules/environment/module.py`).

**Actions taken:**
1. Added imports: `json`, `datetime/timedelta/timezone`, `safe_json` from `core.utils`
2. Implemented `post_ingest()` method + `_compute_day_metrics()` helper
3. Follows same pattern as device module: query dates, compute per day, bulk insert

### Derived Metrics (3 per day)

| Metric | event_type | source_module | Computation |
|--------|-----------|---------------|-------------|
| Weather composite | `daily_weather_composite` | environment.derived | temp range/avg from hourly, avg humidity, avg pressure |
| Location diversity | `location_diversity` | environment.derived | Unique lat/lon rounded to 3 decimals (~111m) |
| Astro summary | `astro_summary` | environment.derived | Moon phase name + illumination % |

**Test:** `python run_etl.py --module environment`
- Result: 5 derived events inserted across 2 days
- 2026-03-22: weather (avg=30.15F, range=24.0F, humidity=50.46%), 17 unique locations from 212 fixes, Waxing Crescent 17%
- 2026-03-23: weather (avg=33.4F, range=57.0F, humidity=46.2%), 4 unique locations from 92 fixes (no astro data)
- Idempotency verified: re-run produces identical 5 events

---

## 2026-03-24 02:59 — Enhanced Daily Report Generator

**Task:** Add Cognition, Behavior, Oracle, and Trends sections to `analysis/reports.py`.

**Actions taken:**
1. Added `import json` at top of file
2. Added `_sparkline()` helper function (module-level) for Unicode block sparklines
3. Added Cognition section: queries reaction RT avg, memory span max, cognitive_load_index, impairment_flag
4. Added Behavior section: queries fragmentation_index, steps total, attention_span_estimate, digital_restlessness, dream count
5. Added Oracle section: queries I Ching castings count, RNG daily_deviation (JSON parse), Schumann daily_summary (JSON parse)
6. Added Trends section: 7-day sparklines for mood, steps, screen time, reaction time
7. All new sections inserted before the Anomalies section
8. All sections skip entirely when no data is present

**Test:** `python run_etl.py --report`
- Result: Report generated successfully at `reports/daily/report_2026-03-24.md`
- 1,322 events for today (mostly world.rss + oracle.planetary_hours)
- Cognition, Behavior, Oracle sections correctly omitted (no data for 2026-03-24)
- Trends section shows 2 metrics with >=2 days data: Steps (7d) and Screen time (7d)
- Sparklines render correctly with Unicode blocks
- No errors, 0 failed modules

---

## 2026-03-24 — Full Security Audit

**Task:** Comprehensive security audit of entire codebase by subject matter expert review.

**Actions taken:**
1. Launched 4 parallel audit agents covering: codebase structure, core/, modules/, scripts+analysis+config
2. Each agent read every line of every Python file in their scope
3. Findings consolidated into `CLAUDE_HEALTH_CHECK.md`

**Results:**
- **60+ files audited** across core/, modules/ (11 modules), analysis/, scripts/, config files
- **0 Critical** findings
- **3 High** findings: fail-open allowlist bypass, unrestricted SQL execution, unsandboxed DB access
- **8 Medium** findings: DB permissions, path traversal in media parsers, PII in config, unpinned deps, unsalted PII hash, command injection risk, API key handling
- **9 Low** findings: truncated hash collision risk, missing env var silence, sensitive data in logs, JSON validation, size limits, retention policy scope, HTTP feed, glob patterns
- **12 Positive** findings confirming good practices (parameterized SQL, safe YAML, no eval/exec/pickle, etc.)
- **1 Design violation** (transcription writes to raw/ directory)

**Output:** `CLAUDE_HEALTH_CHECK.md` — full audit report with evidence, code snippets, and recommended fixes for all 21 findings.

---

## 2026-03-24 07:52 — Security Remediation (All 21 Findings)

**Task:** Implement all security fixes from the audit, test each one, and update CLAUDE_HEALTH_CHECK.md with original code + revert instructions.

### Files Modified (12 total)

| File | Fixes Applied | Test Result |
|------|--------------|-------------|
| `core/orchestrator.py` | H-1 (fail-closed allowlist), H-2 (DDL-only migrations), L-2 (env var warnings), L-4 (truncated errors) | PASS |
| `core/database.py` | H-2 (execute_migration), M-1 (DB permissions 600), M-2 (backup permissions 600), L-3 (sanitized logs) | PASS |
| `core/event.py` | L-1 (32-char hash), L-5 (JSON validation), L-6 (size limits) | PASS |
| `core/logger.py` | L-10 (log file chmod 600) | PASS |
| `core/utils.py` | L-9 (glob pattern traversal rejection) | PASS |
| `modules/media/parsers.py` | M-3 (subprocess `--` separator), M-4 (safe media IDs + path validation) | PASS |
| `modules/media/transcribe.py` | D-1 (transcripts → media/transcripts/ not raw/) | PASS |
| `modules/social/parsers.py` | M-8 (HMAC-SHA256 with per-installation key) | PASS |
| `modules/meta/storage.py` | L-7 (retention path depth + LifeData check) | PASS |
| `config.yaml` | M-5 (home coords → ${HOME_LAT}/${HOME_LON}), L-8 (http → https) | PASS |
| `requirements.txt` | M-6 (exact version pins from pip freeze) | PASS |
| `.env` | M-5 (HOME_LAT/HOME_LON), M-8 (PII_HMAC_KEY) | PASS |

### Test Summary

- **Full ETL dry run:** 11 modules, 6,285 events, 0 skipped, 0 failed
- **Full ETL with report:** All modules pass, report generated, idempotent
- **Empty allowlist test:** 0 modules loaded (fail-closed confirmed)
- **DDL validation:** DROP/DELETE rejected, CREATE/ALTER allowed
- **Event validation:** 32-char hash, invalid JSON caught, oversized text caught
- **Media parser:** Path traversal blocked, safe IDs validated
- **HMAC hashing:** 16-char output, consistent, keyed
- **Glob validation:** Traversal and absolute patterns rejected
- **Retention safety:** Root and non-LifeData paths refused
- **File permissions:** DB=600, backups=600, logs=600, dirs=700

### CLAUDE_HEALTH_CHECK.md Updated

Each of the 21 findings now includes:
- Original code block in `<details>` collapse
- What it was / what it does / why it was changed
- Exact revert instructions
- Test evidence confirming the fix

---

## 2026-03-24 — Config Validation Layer (pydantic)

**Task:** Create a typed config validation schema using pydantic that validates config.yaml at startup.

### What was done

1. **Created `core/config_schema.py`** — Pydantic v2 models mirroring the full `config.yaml` structure:
   - `RootConfig` → `LifeDataConfig` → `SecurityConfig`, `ModulesConfig` (11 per-module models), `AnalysisConfig`, `RetentionConfig`, `ScheduleConfig`
   - `validate_config()` entry point that runs pydantic structural validation + semantic checks
   - `ConfigValidationError` collects all errors into one message for fix-everything-at-once UX

2. **Validation checks implemented:**
   - All required fields exist (pydantic `Field required` errors)
   - API key env vars resolve to non-empty strings (only checked for enabled modules)
   - File paths are expandable and parent directories are writable
   - Module names in allowlist match actual `modules/*/module.py` directories
   - Numeric thresholds within sane ranges (z-scores 0.5–5.0, step goals 100–100k, sleep 3–14h, etc.)
   - Cross-field validation (min_dwell < max_dwell, min_latency < max_latency)
   - Timezone is valid IANA timezone

3. **Integrated into `core/orchestrator.py`** — `validate_config()` called in `__init__` after config load, before any DB or module setup. Fails fast on any violation.

4. **Added `pydantic==2.12.5`** to `requirements.txt`.

### Test results

- **API key detection:** Correctly catches 5 empty API keys when .env is incomplete ✅
- **Bad z-score threshold (99.0):** `anomaly_zscore_threshold=99.0 — must be 0.5–5.0` ✅
- **Bogus module in allowlist:** `'nonexistent_module' has no matching modules/nonexistent_module/module.py` ✅
- **Missing required field:** `[lifedata → version] Field required` ✅
- **Invalid timezone:** `'Mars/Olympus_Mons' is not a valid IANA timezone` ✅
- **min_dwell >= max_dwell:** `min_dwell_sec (5000) must be < max_dwell_sec (100)` ✅
- **pyright:** 0 errors, 0 warnings ✅
