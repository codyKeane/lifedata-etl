# EXECUTION STRATEGY: Production Readiness Implementation Plan
**Date:** 2026-03-25
**Target:** LifeData V4 — Close all gaps identified in ULTIMATE_REVIEW.md (R2)
**Scope:** 5 gaps, ~45-55 hours estimated work, 5-6 week timeline
**Runtime:** Python 3.14.3, SQLite WAL, pytest 9.0.2

---

## Table of Contents

1. [Design Decisions](#1-design-decisions)
2. [Dependency Graph](#2-dependency-graph)
3. [Gap 3: HMAC Key Fix](#3-gap-3-hmac-key-fix) *(executed first — 25 minutes)*
4. [Gap 1: Complete Test Coverage](#4-gap-1-complete-test-coverage) *(largest effort — 30+ hours)*
5. [Gap 2: Metrics Registry Pattern](#5-gap-2-metrics-registry-pattern) *(architectural — 15-20 hours)*
6. [Gap 4: GitHub Actions CI/CD](#6-gap-4-github-actions-cicd) *(infrastructure — 2 hours)*
7. [Gap 5: Script Tests](#7-gap-5-script-tests) *(mock + integration — 10-12 hours)*
8. [Execution Timeline](#8-execution-timeline)
9. [Verification Protocol](#9-verification-protocol)

---

## 1. Design Decisions

These decisions were made during the planning Q&A and are binding for all implementation work.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Test database convention | Real SQLite fixtures (in-memory) | Matches existing conftest.py patterns; tests actual query behavior; faster than mocking |
| API test strategy | Hybrid: mock for CI + live `@pytest.mark.integration` | Mock tests are deterministic for CI; live tests validate real API schema changes |
| process_sensors.py coverage | Full parity, no shortcuts | Largest untested file (412 stmts); core sensor preprocessing pipeline |
| Metrics Registry location | New method on `ModuleInterface` ABC | Preserves module sovereignty — each module self-declares its analytical endpoints |
| Anomaly pattern configurability | Full structure in config.yaml | Users can define which metrics to combine, operators, thresholds, descriptions — all config-driven |
| Hypothesis configurability | Full definition in config.yaml | Users can add/remove/modify hypotheses without touching code |
| Report configurability | Metric selection in config.yaml | Users select which metrics appear in trends, which modules get report sections |
| CI coverage floor | 50% (ratchet up as tests land) | Current measured baseline; CI fails if coverage drops below floor |
| CI provider | GitHub Actions | Remote is GitHub |
| Planetary hours testing | Real astral computation with known date/location | astral is a local computation library, not an API — deterministic for given inputs |

---

## 2. Dependency Graph

Work items have dependencies. This graph determines execution order.

```
Gap 3 (HMAC fix)                    ─── no dependencies, execute first
  │
  ├── Gap 1A (Quick fixes)          ─── hypothesis parens, schumann regex,
  │     │                                cognition assertion, hypothesis naming
  │     │
  │     └── Gap 1B (Timestamp        ─── standardize derived metric timestamps
  │           │     standardization)      across all modules (PREREQUISITE for
  │           │                           post_ingest tests — non-deterministic
  │           │                           timestamps make assertions unreliable)
  │           │
  │           ├── Gap 1C (Analysis    ─── correlator, hypothesis, anomaly,
  │           │    layer tests)           reports tests
  │           │
  │           ├── Gap 1D (Post-ingest ─── behavior, cognition, body, social,
  │           │    tests)                 oracle, world, meta, device, media,
  │           │                           mind module.py tests
  │           │
  │           └── Gap 5 (Script       ─── _http, fetch_*, process_sensors,
  │                tests)                 compute_planetary_hours tests
  │
  ├── Gap 2 (Metrics Registry)       ─── depends on Gap 1B (timestamps fixed)
  │     │                                 and Gap 1C (analysis tests exist to
  │     │                                 verify refactor doesn't break anything)
  │     │
  │     └── Gap 2B (Threshold         ─── externalize all anomaly/hypothesis/
  │          externalization)              report config to YAML
  │
  └── Gap 4 (CI/CD)                  ─── depends on Gap 1C/1D (tests exist
                                          to run in CI)
```

**Critical path:** Gap 3 → Gap 1B → Gap 1C + Gap 1D (parallel) → Gap 2 → Gap 4

---

## 3. Gap 3: HMAC Key Fix

**Ref:** ULTIMATE_REVIEW U-07
**Effort:** 25 minutes
**Files modified:** `modules/social/parsers.py`, `.env.example` (new)

### 3.1 Fix: Remove hostname fallback

**File:** `modules/social/parsers.py:29-35`

**Current code:**
```python
_PII_HMAC_KEY: bytes = os.environ.get(
    "PII_HMAC_KEY",
    f"lifedata-pii-{os.uname().nodename}",
).encode("utf-8")
```

**Target code:**
```python
_PII_HMAC_KEY_RAW = os.environ.get("PII_HMAC_KEY")
if not _PII_HMAC_KEY_RAW:
    raise RuntimeError(
        "PII_HMAC_KEY environment variable is required but not set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and add it to your .env file."
    )
_PII_HMAC_KEY: bytes = _PII_HMAC_KEY_RAW.encode("utf-8")
```

### 3.2 Create .env.example

**File:** `.env.example` (new file in project root)

```bash
# LifeData V4 — Environment Variables
# Copy this file to .env and fill in values: cp .env.example .env
# Permissions: chmod 600 .env

# === REQUIRED ===

# PII hashing key (protects contact names in database)
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
PII_HMAC_KEY=

# === API KEYS (required for respective modules) ===

# OpenWeatherMap (environment module)
WEATHER_API_KEY=

# AirNow (air quality)
AIRNOW_API_KEY=

# Ambee (pollen, fire risk)
AMBEE_API_KEY=

# NewsAPI.org (world module — free tier: 100 req/day)
NEWS_API_KEY=

# US EIA (gas prices — free, requires registration)
EIA_API_KEY=

# === LOCATION (required for environment, oracle modules) ===

HOME_LAT=
HOME_LON=

# === SYNCTHING (required for meta sync checks) ===

SYNCTHING_API_KEY=
```

### 3.3 Update existing test

Update `tests/test_security.py` to verify the `RuntimeError` is raised when `PII_HMAC_KEY` is not set. Add a test that verifies hashing works when the key IS set.

### 3.4 Acceptance Criteria

- [ ] `_PII_HMAC_KEY` is never derived from hostname
- [ ] Module raises `RuntimeError` at import if `PII_HMAC_KEY` env var missing
- [ ] `.env.example` exists with all required keys and generation instructions
- [ ] `make test` passes (existing tests must set `PII_HMAC_KEY` in env)
- [ ] Error message includes the exact command to generate a key

---

## 4. Gap 1: Complete Test Coverage

**Ref:** ULTIMATE_REVIEW U-02, U-06, U-08, U-09, U-10, U-17, U-18, U-24
**Effort:** 30+ hours
**Target:** Overall coverage from 50% → 75%+

### 4.1 Quick Fixes (30 minutes)

These are direct code fixes, not test additions. Execute first because subsequent tests should validate the fixed behavior.

#### 4.1.1 Hypothesis parentheses (U-06)
**File:** `analysis/hypothesis.py:61`

**Target code:**
```python
if (
    (self.direction == "negative" and r < 0 and p < self.threshold)
    or (self.direction == "positive" and r > 0 and p < self.threshold)
    or (self.direction == "any" and p < self.threshold)
):
    supported = True
```

#### 4.1.2 Cognition parser assertion (U-17)
**File:** `modules/cognition/module.py` — in `_get_parsers()` method, after lazy load

Add: `assert self._parser_registry is not None`

#### 4.1.3 Schumann regex (U-24)
**File:** `scripts/fetch_schumann.py`

Change: `r"(\d+\.\d+)\s*(?:Hz|hz)"` → `r"(\d+(?:\.\d+)?)\s*(?:Hz|hz)"`

#### 4.1.4 Hypothesis naming (U-18)
**File:** `analysis/hypothesis.py:116-120`

Add comment above the "Negative news" hypothesis:
```python
# direction="positive" because higher sentiment score (more positive news)
# correlates with higher mood — the hypothesis NAME describes the inverse
# relationship but the DIRECTION describes the correlation sign.
```

#### 4.1.5 SQL aggregate pattern (U-10)
**File:** `analysis/anomaly.py:51-56`

**Target code:**
```python
_AGG_SQL = {"AVG": "AVG", "SUM": "SUM", "MIN": "MIN", "MAX": "MAX", "COUNT": "COUNT"}

def _get_daily_metric(self, source_module, date_str, event_type=None, aggregate="AVG"):
    agg_fn = _AGG_SQL.get(aggregate.upper(), "AVG")
    query = f"""
        SELECT {agg_fn}(value_numeric)
        FROM events
        WHERE source_module = ?
    ...
```

### 4.2 Timestamp Standardization (U-09) — 2 hours

**Prerequisite for all post_ingest tests.** Non-deterministic timestamps make test assertions unreliable.

**Convention chosen:** `f"{date_str}T23:59:00+00:00"` for daily derived metrics (most modules already use this).

**Files requiring changes:**

| Module | Current Convention | Change Required |
|--------|-------------------|-----------------|
| body/module.py | `datetime.now(UTC).isoformat()` | Replace with `f"{date_str}T23:59:00+00:00"` |
| world/module.py | `datetime.now(UTC).isoformat()` | Replace with `f"{date_str}T23:59:00+00:00"` |
| media/module.py | `datetime.now(UTC).isoformat()` | Replace with `f"{date_str}T23:59:00+00:00"` |
| device/module.py | `f"{day}T12:00:00-05:00"` | Replace with `f"{date_str}T23:59:00+00:00"` |
| social/module.py | `f"{day}T12:00:00-05:00"` | Replace with `f"{date_str}T23:59:00+00:00"` |
| mind/module.py | `f"{day}T12:00:00-05:00"` | Replace with `f"{date_str}T23:59:00+00:00"` |
| cognition/module.py | `T23:59:00+00:00` | Already correct — no change |
| behavior/module.py | `T23:59:00+00:00` | Already correct — no change |
| oracle/module.py | `T23:59:00/01/02+00:00` | Keep microsecond offsets (intentional for rolling-window idempotency) |
| meta/module.py | `T00:00:00+00:00` | Keep midnight convention (meta runs at start-of-day conceptually) |

**Document the convention** in CLAUDE.md under Design Rules:
```
- **Derived metric timestamps** — All post_ingest() daily derived metrics use
  `f"{date_str}T23:59:00+00:00"` as their timestamp. This ensures deterministic
  hashing for INSERT OR REPLACE idempotency. Exceptions: meta uses T00:00:00
  (conceptually start-of-day), oracle uses T23:59:01/02 offsets for rolling-window
  metrics that would otherwise collide.
```

### 4.3 Analysis Layer Tests — 13 hours

#### 4.3.1 `tests/analysis/test_correlator.py` — 4 hours

**New file.** Test the Correlator class with known-input/known-output pairs.

```python
# Fixtures needed:
# - db with events spanning 30+ days for two metrics
# - known perfectly-correlated series
# - known uncorrelated series
# - known anti-correlated series
# - series with insufficient data (<3 days)

class TestGetDailySeries:
    """Test _get_daily_series returns correct daily averages."""
    def test_single_day_single_event(self, populated_db)
    def test_single_day_multiple_events_averaged(self, populated_db)
    def test_multiple_days(self, populated_db)
    def test_confidence_filter(self, populated_db)
    def test_window_days_cutoff(self, populated_db)
    def test_empty_series(self, populated_db)

class TestAlignSeries:
    """Test _align_series date matching and lag."""
    def test_perfect_overlap(self)
    def test_partial_overlap(self)
    def test_no_overlap(self)
    def test_lag_shift(self)
    def test_empty_input(self)

class TestCorrelate:
    """Test correlate() with known statistical inputs."""
    def test_perfect_positive_correlation(self, db_with_correlated_data)
        # Insert two metrics: A=[1,2,3,4,5], B=[10,20,30,40,50]
        # Assert: r ≈ 1.0, p < 0.05, significant=True, effect_size="very_strong"
    def test_perfect_negative_correlation(self, db_with_anti_correlated_data)
        # Insert: A=[1,2,3,4,5], B=[50,40,30,20,10]
        # Assert: r ≈ -1.0, p < 0.05
    def test_no_correlation(self, db_with_random_data)
        # Insert: A=[1,2,3,4,5], B=[3,1,4,1,5]
        # Assert: |r| < 0.3, p > 0.05 (likely)
    def test_insufficient_data_returns_error(self, db_with_few_events)
        # Insert <3 days. Assert: "error" in result
    def test_lag_correlation(self, db_with_lagged_data)
        # Insert: A on day N predicts B on day N+1
        # Assert: lag_days=1 correlation > lag_days=0
    def test_confidence_tier_exploratory(self)
        # n < 14 → "exploratory"
    def test_confidence_tier_preliminary(self)
        # 14 ≤ n < 30 → "preliminary"
    def test_confidence_tier_reliable(self)
        # n ≥ 30 → "reliable"

class TestCorrelationMatrix:
    """Test run_correlation_matrix for N metrics."""
    def test_three_metrics_returns_all_pairs(self, db_with_three_metrics)
    def test_strongest_sorted_by_r(self, db_with_three_metrics)
    def test_empty_metrics_list(self, db)

class TestLaggedAnalysis:
    """Test lagged_analysis at multiple lags."""
    def test_returns_results_for_each_lag(self, db_with_lagged_data)
    def test_max_lag_respected(self, db_with_lagged_data)

class TestInterpretR:
    """Test static _interpret_r thresholds."""
    def test_negligible(self)   # |r| < 0.1
    def test_weak(self)         # 0.1 ≤ |r| < 0.3
    def test_moderate(self)     # 0.3 ≤ |r| < 0.5
    def test_strong(self)       # 0.5 ≤ |r| < 0.7
    def test_very_strong(self)  # |r| ≥ 0.7
```

**Fixtures to add to `tests/analysis/conftest.py` (new file):**

```python
@pytest.fixture
def db_with_correlated_data(tmp_database):
    """Insert 30 days of perfectly correlated metrics A and B."""
    events = []
    for i in range(30):
        date = (datetime(2026, 2, 1, tzinfo=UTC) + timedelta(days=i))
        ts = date.isoformat()
        events.append(Event(
            timestamp_utc=ts, timestamp_local=ts,
            source_module="test.metric_a", event_type="value",
            value_numeric=float(i + 1), confidence=1.0,
        ))
        events.append(Event(
            timestamp_utc=ts, timestamp_local=ts,
            source_module="test.metric_b", event_type="value",
            value_numeric=float((i + 1) * 10), confidence=1.0,
        ))
    tmp_database.insert_events(events)
    return tmp_database
```

#### 4.3.2 `tests/analysis/test_hypothesis.py` — 2 hours

**New file.** Test HypothesisTest and HYPOTHESES list.

```python
class TestHypothesisTest:
    """Test individual hypothesis evaluation logic."""
    def test_negative_direction_negative_r_significant(self, db_with_anti_correlated_data)
        # direction="negative", r < 0, p < 0.05 → supported=True
    def test_negative_direction_positive_r_not_supported(self, db_with_correlated_data)
        # direction="negative", r > 0, p < 0.05 → supported=False
    def test_positive_direction_positive_r_significant(self, db_with_correlated_data)
        # direction="positive", r > 0, p < 0.05 → supported=True
    def test_any_direction_significant(self, db_with_correlated_data)
        # direction="any", p < 0.05 → supported=True
    def test_insufficient_data_returns_status(self, db)
        # No data → status="insufficient_data"
    def test_needs_more_data_flag(self, db_with_few_events)
        # n < 30 → needs_more_data=True
    def test_custom_threshold(self, db_with_correlated_data)
        # threshold=0.001 with p=0.03 → not_supported

class TestHypothesesList:
    """Validate the HYPOTHESES constant."""
    def test_all_hypotheses_have_valid_direction(self)
        # direction ∈ {"positive", "negative", "any"}
    def test_all_hypotheses_have_two_metrics(self)
    def test_no_duplicate_hypotheses(self)

class TestRunAllHypotheses:
    """Test run_all_hypotheses integration."""
    def test_returns_sorted_by_significance(self, populated_database)
    def test_handles_empty_database(self, tmp_database)
```

#### 4.3.3 `tests/analysis/test_reports.py` — 4 hours

**New file.** Test report generation with fixture database.

```python
@pytest.fixture
def report_db(tmp_database, sample_events):
    """DB with enough data to generate a non-trivial report."""
    tmp_database.insert_events(sample_events)
    return tmp_database

class TestGenerateDailyReport:
    """Test report generation end-to-end."""
    def test_generates_file(self, report_db, tmp_path)
        # Assert: returns a path, file exists, file is non-empty
    def test_contains_header_with_date(self, report_db, tmp_path)
    def test_contains_data_summary_section(self, report_db, tmp_path)
    def test_contains_metrics_section(self, report_db, tmp_path)
    def test_empty_database_produces_minimal_report(self, tmp_database, tmp_path)
    def test_missing_module_data_handled_gracefully(self, report_db, tmp_path)
        # Insert data for only 2 modules. Assert: report still generates,
        # missing sections are skipped or show "no data"
    def test_invalid_json_in_oracle_does_not_crash(self, report_db, tmp_path)
        # Insert event with malformed value_json. Assert: report generates,
        # oracle section is skipped
    def test_report_path_follows_convention(self, report_db, tmp_path)
        # Assert: path matches {reports_dir}/daily/report_{date}.md

class TestSparkline:
    """Test _sparkline helper."""
    def test_ascending_values(self)
    def test_single_value_returns_empty(self)
    def test_constant_values(self)
    def test_empty_list(self)
    def test_negative_values(self)
```

#### 4.3.4 `tests/analysis/test_anomaly.py` — Expand existing — 3 hours

**Existing file has some coverage (83%).** Add tests for compound patterns and edge cases.

```python
class TestCheckPatternAnomalies:
    """Test all 9 compound pattern detectors."""
    def test_heavy_phone_usage_pattern(self, db_with_device_data)
        # battery < 20 AND screen_count > 50 → pattern detected
    def test_heavy_phone_usage_not_triggered(self, db_with_device_data)
        # battery > 20 OR screen_count < 50 → no pattern
    def test_sleep_deprivation_high_stress(self, db_with_body_mind_data)
    def test_caffeine_late_poor_sleep(self, db_with_caffeine_sleep_data)
    def test_low_mood_social_isolation(self, db_with_mood_social_data)
    def test_high_screen_low_movement(self, db_with_screen_steps_data)
    def test_cognitive_impairment_sleep_deprivation(self, db_with_cog_sleep_data)
    def test_digital_restlessness_low_mood(self, db_with_behavior_mood_data)
    def test_schumann_excursion_mood_swing(self, db_with_schumann_mood_data)
    def test_fragmentation_caffeine_spike(self, db_with_frag_caffeine_data)
    def test_no_patterns_when_data_missing(self, tmp_database)
    def test_partial_data_skips_incomplete_patterns(self, db_with_partial_data)

class TestGetLateCaffeine:
    def test_afternoon_caffeine_summed(self, db_with_caffeine_data)
    def test_morning_caffeine_excluded(self, db_with_caffeine_data)
    def test_no_caffeine_returns_none(self, tmp_database)

class TestGetMoodRange:
    def test_wide_mood_range(self, db_with_mood_data)
    def test_single_mood_returns_zero(self, db_with_mood_data)
    def test_no_mood_returns_none(self, tmp_database)
```

### 4.4 Post-Ingest Tests — 15 hours

One test file per module. Each tests the `post_ingest()` method with known inputs and asserts correct derived metric output.

**Convention for all post_ingest test files:**

```python
# Pattern: Insert known raw events → call post_ingest() → query derived events → assert values

@pytest.fixture
def module_instance(sample_config):
    """Create module with test config."""
    from modules.<name> import create_module
    return create_module(sample_config)

@pytest.fixture
def db_with_<name>_data(tmp_database):
    """Insert known raw events for <name> module."""
    events = [...]  # Known values
    tmp_database.insert_events(events)
    return tmp_database
```

#### 4.4.1 `tests/modules/behavior/test_post_ingest.py` — 4 hours

```python
class TestFragmentationIndex:
    def test_high_fragmentation(self, behavior_module, db_with_many_switches)
        # 100 app switches in 8 hours → frag_index > 50
    def test_zero_switches(self, behavior_module, db_with_no_switches)
        # No transitions → no fragmentation event emitted
    def test_single_app_all_day(self, behavior_module, db_with_one_app)
        # One app, no switches → frag_index ≈ 0

class TestMovementEntropy:
    def test_evenly_distributed_steps(self, behavior_module, db_with_even_steps)
        # 500 steps/hour × 16 hours → high entropy
    def test_all_steps_one_hour(self, behavior_module, db_with_burst_steps)
        # 8000 steps in hour 10, 0 elsewhere → low entropy
    def test_zero_steps(self, behavior_module, db_with_no_steps)
        # No steps → no entropy event

class TestDigitalRestlessness:
    def test_high_restlessness(self, behavior_module, db_with_restless_day)
        # High frag + high unlocks + high screen → z > 2.0
    def test_calm_day(self, behavior_module, db_with_calm_day)
        # Low frag + low unlocks + low screen → z < 0
    def test_insufficient_baseline(self, behavior_module, db_with_one_day)
        # < 7 days baseline → no restlessness event

class TestSedentaryBouts:
    def test_long_sedentary_detected(self, behavior_module, db_with_sedentary)
        # 4 consecutive hours <50 steps → 2 bouts detected
    def test_no_sedentary(self, behavior_module, db_with_active_day)

class TestMorningInertia:
    def test_quick_start(self, behavior_module, db_with_quick_morning)
        # Screen on at 7:00, productive app at 7:10 → 10 minutes
    def test_slow_start(self, behavior_module, db_with_slow_morning)
        # Screen on at 7:00, productive app at 9:00 → 120 minutes
    def test_no_productive_app(self, behavior_module, db_with_no_productive)
        # No productive app found → no inertia event

class TestBehavioralConsistency:
    def test_consistent_day(self, behavior_module, db_with_consistent_pattern)
    def test_anomalous_day(self, behavior_module, db_with_anomalous_pattern)
    def test_insufficient_baseline(self, behavior_module, db_with_one_day)

class TestAttentionSpan:
    def test_long_dwells(self, behavior_module, db_with_long_dwells)
    def test_short_dwells(self, behavior_module, db_with_short_dwells)
    def test_excluded_apps_filtered(self, behavior_module, db_with_dialer_events)

class TestDreamFrequency:
    def test_daily_dream_count(self, behavior_module, db_with_dreams)
    def test_no_dreams(self, behavior_module, db_with_no_dreams)
```

#### 4.4.2 `tests/modules/cognition/test_post_ingest.py` — 3 hours

```python
class TestCognitiveLoadIndex:
    def test_all_components_present(self, cognition_module, db_with_full_cog_data)
        # RT=250ms, digit_span=7, time_error=2s, typing=60wpm → CLI value
    def test_single_component(self, cognition_module, db_with_rt_only)
        # Only RT data → CLI still computed (1 component)
    def test_no_data(self, cognition_module, db_with_no_cog_data)
        # No cognitive events → no CLI event

class TestImpairmentFlag:
    def test_impaired(self, cognition_module, db_with_impaired_day)
        # CLI z-score > 2.0 → impairment_flag = 1
    def test_normal(self, cognition_module, db_with_normal_day)
        # CLI z-score < 2.0 → impairment_flag = 0
    def test_insufficient_baseline(self, cognition_module, db_with_two_days)
        # < 3 days → no impairment event

class TestSubjectiveObjectiveGap:
    def test_aligned(self, cognition_module, db_with_aligned_data)
        # Self-report energy=8, RT fast → small gap
    def test_misaligned(self, cognition_module, db_with_misaligned_data)
        # Self-report energy=8, RT slow → large gap
    def test_no_subjective_data(self, cognition_module, db_with_rt_only)

class TestPeakCognitionHour:
    def test_morning_peak(self, cognition_module, db_with_morning_rt)
    def test_insufficient_trials(self, cognition_module, db_with_few_trials)

class TestDailyBaseline:
    def test_baseline_computed(self, cognition_module, db_with_multi_day_rt)
    def test_trend_direction(self, cognition_module, db_with_improving_rt)
```

#### 4.4.3 `tests/modules/body/test_post_ingest.py` — 1.5 hours

```python
class TestCaffeineLevel:
    def test_single_intake_decay(self, body_module, db_with_morning_coffee)
        # 200mg at 8am, checked at 1pm (5hr) → ~100mg (half-life)
    def test_multiple_intakes(self, body_module, db_with_multiple_coffees)
    def test_no_caffeine(self, body_module, db_with_no_caffeine)
    def test_negligible_remaining(self, body_module, db_with_old_caffeine)
        # 50mg 24 hours ago → < 0.1mg → no event

class TestSleepDuration:
    def test_normal_sleep(self, body_module, db_with_sleep_pair)
        # sleep_start 23:00, sleep_end 07:00 → 8 hours
    def test_unpaired_start(self, body_module, db_with_unpaired_sleep)
    def test_sanity_check_rejects_long(self, body_module, db_with_25h_sleep)

class TestDailyStepTotal:
    def test_sum_correct(self, body_module, db_with_hourly_steps)
    def test_zero_steps(self, body_module, db_with_no_steps)
```

#### 4.4.4 `tests/modules/social/test_post_ingest.py` — 1.5 hours

```python
class TestDensityScore:
    def test_weighted_calculation(self, social_module, db_with_social_events)
        # 2 calls(×3) + 5 SMS(×2) + 20 notif(×0.1) = 6+10+2 = 18.0
    def test_zero_interactions(self, social_module, db_with_no_social)

class TestDigitalHygiene:
    def test_all_productive(self, social_module, db_with_productive_apps)
    def test_all_distraction(self, social_module, db_with_distraction_apps)
    def test_mixed(self, social_module, db_with_mixed_apps)
    def test_zero_apps(self, social_module, db_with_no_apps)

class TestNotificationLoad:
    def test_normal_load(self, social_module, db_with_notifications)
    def test_single_notification(self, social_module, db_with_one_notification)
    def test_zero_notifications(self, social_module, db_with_no_notifications)
```

#### 4.4.5 Remaining modules — 5 hours combined

**`tests/modules/oracle/test_post_ingest.py`** — 1.5 hours
- TestHexagramFrequency, TestEntropyTest, TestRNGDeviation, TestSchumannSummary, TestActivityByPlanet

**`tests/modules/world/test_post_ingest.py`** — 1 hour
- TestNewsSentimentIndex, TestInformationEntropy

**`tests/modules/meta/test_post_ingest.py`** — 1.5 hours
- TestCompletenessCheck, TestQualityCheck (future timestamps, numeric ranges, suspicious duplicates, time gaps), TestStorageReport, TestSyncLag, TestBackupAge, TestRelayCheck

**`tests/modules/device/test_post_ingest.py`** — 0.5 hours (device is already at 70%)
- TestScreenTimeMinutes (edge: <2 events), TestBatteryDrainRate (edge: charging segments)

**`tests/modules/media/test_post_ingest.py`** — 0.25 hours
- TestDailyMediaCount, TestTranscriptionSkippedWhenUnavailable

**`tests/modules/mind/test_post_ingest.py`** — 0.25 hours
- TestSubjectiveDayScore, TestMoodTrend7d, TestEnergyStability (edge: <2 values)

### 4.5 CSV Parser Documentation (U-08) — 15 minutes

**File:** `core/parser_utils.py:71`

Add comment above the split:
```python
# NOTE: Intentional use of str.split(",") instead of csv.reader.
# Tasker-generated CSVs do not use RFC 4180 quoting. Fields never
# contain commas. If this assumption changes, migrate to csv.reader.
# See CLAUDE.md → Design Rules for the no-quoted-fields contract.
```

**File:** `CLAUDE.md` — Add to Design Rules:
```
- **CSV fields are never quoted** — Tasker CSVs use bare comma separation.
  `parser_utils.py` uses `str.split(",")` for performance. If a data source
  introduces quoted fields, migrate to Python's `csv` module.
```

---

## 5. Gap 2: Metrics Registry Pattern

**Ref:** ULTIMATE_REVIEW U-01, U-03
**Effort:** 15-20 hours
**Prerequisite:** Gap 1B (timestamp standardization) and Gap 1C (analysis tests exist to verify refactor)

### 5.1 Architecture Overview

```
┌─────────────┐         ┌──────────────────┐         ┌─────────────────┐
│  Module A    │         │  config.yaml     │         │  Analysis Layer │
│  manifest()  │────────▶│  analysis:       │────────▶│  reads config   │
│  declares    │         │    patterns:     │         │  + manifests    │
│  own metrics │         │    hypotheses:   │         │  zero hardcoded │
└─────────────┘         │    report:       │         │  module refs    │
                        └──────────────────┘         └─────────────────┘
```

**Sovereignty preserved:** Each module only knows about its own metrics. Cross-module patterns, hypotheses, and report layout are defined in config.yaml. The analysis layer reads both manifests and config — it never hardcodes module names.

### 5.2 ModuleInterface Extension

**File:** `core/module_interface.py`

Add new optional method:

```python
def get_metrics_manifest(self) -> dict:
    """Declare this module's metrics for the analysis layer.

    Returns a dict with:
        metrics: list of metric declarations
        report_sections: list of report section configs (optional)

    Each metric declaration:
        name: str — source_module value (e.g., "device.battery")
        display_name: str — human-readable label
        unit: str — unit of measurement (e.g., "%", "ms", "mg", "count")
        aggregate: str — default SQL aggregate (AVG, SUM, COUNT, etc.)
        trend_eligible: bool — show in report trends section
        anomaly_eligible: bool — include in z-score anomaly detection
    """
    return {"metrics": [], "report_sections": []}
```

### 5.3 Module Manifest Implementations

Each module implements `get_metrics_manifest()`. Example for device:

```python
# modules/device/module.py
def get_metrics_manifest(self) -> dict:
    return {
        "metrics": [
            {
                "name": "device.battery",
                "display_name": "Battery Level",
                "unit": "%",
                "aggregate": "AVG",
                "trend_eligible": False,
                "anomaly_eligible": True,
            },
            {
                "name": "device.screen",
                "display_name": "Screen Events",
                "unit": "count",
                "aggregate": "COUNT",
                "trend_eligible": True,
                "anomaly_eligible": True,
            },
            {
                "name": "device.derived",
                "display_name": "Screen Time",
                "unit": "min",
                "aggregate": "AVG",
                "event_type_filter": "screen_time_minutes",
                "trend_eligible": True,
                "anomaly_eligible": True,
            },
        ],
    }
```

**All 11 modules** get manifest implementations declaring their metrics. This is the bulk of the work (~1 hour per module = 11 hours).

### 5.4 Config Schema: Patterns, Hypotheses, Report

**File:** `config.yaml` — New `analysis:` subsection

```yaml
analysis:
  # Existing keys preserved:
  correlation_window_days: 30
  anomaly_zscore_threshold: 2.0
  min_observations: 14

  # NEW: Compound anomaly patterns (replaces hardcoded patterns in anomaly.py)
  patterns:
    - name: heavy_phone_usage
      enabled: true
      description_template: >-
        Low battery ({battery_avg:.0f}%) with high screen unlocks
        ({screen_events}) — heavy phone usage day
      conditions:
        - metric: device.battery
          aggregate: AVG
          operator: "<"
          threshold: 20
        - metric: device.screen
          aggregate: COUNT
          operator: ">"
          threshold: 50

    - name: sleep_deprivation_high_stress
      enabled: true
      description_template: >-
        Short sleep ({sleep_hours:.1f}h) combined with
        high stress ({stress_level:.0f}/10) — burnout risk
      conditions:
        - metric: body.derived
          event_type: sleep_duration
          operator: "<"
          threshold: 6.0
        - metric: mind.stress
          operator: ">"
          threshold: 6

    - name: caffeine_late_poor_sleep
      enabled: true
      description_template: >-
        Caffeine intake after {hour_threshold}:00 ({late_caffeine_mg:.0f}mg)
        with poor sleep quality ({sleep_quality:.0f}/10)
      conditions:
        - metric: body.caffeine
          event_type: intake
          aggregate: SUM
          operator: ">"
          threshold: 0
          hour_filter: ">= 14"
        - metric: mind.sleep
          operator: "<"
          threshold: 5
      parameters:
        hour_threshold: 14

    # ... remaining 6 patterns follow same structure

  # NEW: Hypothesis definitions (replaces hardcoded HYPOTHESES list)
  hypotheses:
    - name: "Geomagnetic storms reduce mood"
      metric_a: environment.geomagnetic
      metric_b: mind.mood
      direction: negative
      threshold: 0.05
      enabled: true

    - name: "Morning light exposure improves energy"
      metric_a: environment.hourly
      metric_b: mind.energy
      direction: positive
      enabled: true

    - name: "Afternoon caffeine disrupts sleep"
      metric_a: body.caffeine
      metric_b: body.sleep_quality
      direction: negative
      enabled: true

    # ... remaining hypotheses follow same structure
    # Users can add custom hypotheses here without touching code

  # NEW: Report configuration
  report:
    # Which metrics show 7-day trend sparklines
    trend_metrics:
      - mind.mood
      - body.steps
      - device.derived:screen_time_minutes
      - cognition.reaction

    # Which modules get dedicated report sections
    # (order determines section order in report)
    sections:
      - module: device
        enabled: true
      - module: environment
        enabled: true
      - module: body
        enabled: true
      - module: mind
        enabled: true
      - module: social
        enabled: true
      - module: cognition
        enabled: true
      - module: behavior
        enabled: true
      - module: oracle
        enabled: true
      - module: world
        enabled: true
```

### 5.5 Analysis Layer Refactor

#### 5.5.1 Metrics Registry Loader

**New file:** `analysis/registry.py`

```python
"""Loads metrics manifests from modules and config."""

class MetricsRegistry:
    def __init__(self, modules: list, config: dict):
        self._manifests = {}
        self._config = config
        for m in modules:
            manifest = m.get_metrics_manifest()
            self._manifests[m.module_id] = manifest

    def get_metric(self, source_module: str) -> dict | None:
        """Look up a metric declaration by source_module name."""

    def get_all_anomaly_eligible(self) -> list[dict]:
        """Return all metrics flagged for anomaly detection."""

    def get_trend_metrics(self) -> list[str]:
        """Return configured trend metric names from config."""

    def get_patterns(self) -> list[dict]:
        """Return compound anomaly patterns from config."""

    def get_hypotheses(self) -> list[dict]:
        """Return hypothesis definitions from config."""

    def get_report_sections(self) -> list[dict]:
        """Return report section config from config."""
```

#### 5.5.2 Anomaly Refactor

**File:** `analysis/anomaly.py`

- Remove all 9 hardcoded pattern methods
- Replace with a generic `_evaluate_pattern(pattern_config, date_str)` that reads conditions from config
- `check_pattern_anomalies()` iterates `registry.get_patterns()` and evaluates each
- Operator mapping: `{"<": lt, ">": gt, "<=": le, ">=": ge, "==": eq}`
- Hour filter handled generically via SQL WHERE clause builder

#### 5.5.3 Hypothesis Refactor

**File:** `analysis/hypothesis.py`

- `HYPOTHESES` list becomes dynamically loaded from config
- `HypothesisTest.__init__` unchanged (still takes name, metrics, direction, threshold)
- New: `load_hypotheses(config) -> list[HypothesisTest]` reads config and constructs tests
- `run_all_hypotheses()` calls `load_hypotheses()` first

#### 5.5.4 Reports Refactor

**File:** `analysis/reports.py`

- Section generation reads `registry.get_report_sections()` instead of hardcoded module list
- Trend metrics read from `registry.get_trend_metrics()`
- Each module section queries based on manifest-declared metrics, not hardcoded source_module strings
- Anomaly section uses refactored `AnomalyDetector` (which uses registry)
- Add `log.warning()` when a configured metric returns no data

### 5.6 Pydantic Validation for New Config

**File:** `core/config_schema.py`

Add validation models for the new analysis config sections:

```python
class PatternCondition(BaseModel):
    metric: str
    operator: Literal["<", ">", "<=", ">=", "==", "!="]
    threshold: float
    aggregate: str = "AVG"
    event_type: str | None = None
    hour_filter: str | None = None

class AnomalyPattern(BaseModel):
    name: str
    enabled: bool = True
    description_template: str
    conditions: list[PatternCondition]
    parameters: dict[str, Any] = {}

class HypothesisConfig(BaseModel):
    name: str
    metric_a: str
    metric_b: str
    direction: Literal["positive", "negative", "any"]
    threshold: float = 0.05
    enabled: bool = True
    window_days: int = 90

class ReportSection(BaseModel):
    module: str
    enabled: bool = True

class ReportConfig(BaseModel):
    trend_metrics: list[str] = []
    sections: list[ReportSection] = []

class AnalysisConfig(BaseModel):
    correlation_window_days: int = 30
    anomaly_zscore_threshold: float = 2.0
    min_observations: int = 14
    patterns: list[AnomalyPattern] = []
    hypotheses: list[HypothesisConfig] = []
    report: ReportConfig = ReportConfig()
```

### 5.7 Acceptance Criteria

- [ ] Zero hardcoded `source_module` strings in `analysis/reports.py`, `analysis/anomaly.py`, `analysis/hypothesis.py`
- [ ] All 9 anomaly patterns defined in `config.yaml`, removable by setting `enabled: false`
- [ ] All 10 hypotheses defined in `config.yaml`, removable by setting `enabled: false`
- [ ] Users can add new hypotheses in config.yaml without code changes
- [ ] Users can add new anomaly patterns in config.yaml without code changes
- [ ] Report trend metrics and section order configurable in config.yaml
- [ ] WARNING-level log emitted when configured metric returns no data
- [ ] `make test` passes — all existing + new Gap 1C tests pass after refactor
- [ ] `make typecheck` passes
- [ ] `make lint` passes

---

## 6. Gap 4: GitHub Actions CI/CD

**Ref:** ULTIMATE_REVIEW U-13
**Effort:** 2 hours
**Prerequisite:** Gaps 1C + 1D (tests exist to run)

### 6.1 Workflow File

**New file:** `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.14"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-dev.txt

      - name: Set test environment
        run: |
          echo "PII_HMAC_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" >> $GITHUB_ENV

      - name: Lint
        run: |
          ruff check core/ modules/ analysis/ scripts/

      - name: Type check
        run: |
          mypy --strict core/

      - name: Test with coverage
        run: |
          pytest tests/ -v --timeout=30 \
            --cov=core --cov=modules --cov=analysis --cov=scripts \
            --cov-fail-under=50

      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: .coverage
```

### 6.2 Coverage Ratchet

The `--cov-fail-under=50` flag starts at the current baseline. Update this value as coverage improves:

| After Phase | Expected Coverage | New Floor |
|------------|-------------------|-----------|
| Gaps 3 + 1A | 50% | 50 |
| Gap 1B + 1C + 1D | ~70% | 65 |
| Gap 2 + Gap 5 | ~75% | 70 |

### 6.3 Acceptance Criteria

- [ ] `.github/workflows/ci.yml` exists and is valid YAML
- [ ] Push to main triggers: lint, typecheck, test with coverage
- [ ] PR to main triggers same pipeline
- [ ] Pipeline fails if coverage drops below floor
- [ ] `PII_HMAC_KEY` set in CI environment (generated per run)

---

## 7. Gap 5: Script Tests

**Ref:** ULTIMATE_REVIEW U-02 (scripts coverage), U-23, U-24
**Effort:** 10-12 hours
**Strategy:** Mock-based tests for CI + live `@pytest.mark.integration` tests for manual validation

### 7.1 Test Marker Setup

**File:** `pyproject.toml` — Add integration marker:

```toml
[tool.pytest.ini_options]
markers = [
    "slow: performance benchmarks",
    "integration: tests that call external APIs (deselected by default)",
]
addopts = "-m 'not slow and not integration'"
```

**File:** `Makefile` — Add integration target:

```makefile
test-integration:
    $(PYTEST) tests/ -v -m integration --timeout=60
```

### 7.2 `tests/scripts/test_http.py` — 1.5 hours

```python
from unittest.mock import patch, MagicMock

class TestRetryGet:
    def test_success_on_first_try(self)
        # Mock requests.get → 200. Assert: called once, returns response.
    def test_retries_on_429(self)
        # Mock: 429, 429, 200. Assert: called 3 times, returns 200.
    def test_retries_on_500(self)
        # Mock: 500, 200. Assert: called 2 times.
    def test_exhausts_retries(self)
        # Mock: 500, 500, 500, 500. Assert: returns last 500 response.
    def test_timeout_raises(self)
        # Mock: requests.exceptions.Timeout. Assert: retries, then raises.
    def test_connection_error(self)
        # Mock: ConnectionError. Assert: retries, then raises.
    def test_custom_retry_codes(self)
        # retry_on=(418,). Mock: 418, 200. Assert: retried on 418.
    def test_backoff_timing(self)
        # Verify sleep called with backoff_base^attempt
    def test_headers_passed(self)
        # Custom headers forwarded to requests.get
    def test_params_passed(self)
        # Query params forwarded to requests.get
```

### 7.3 `tests/scripts/test_fetch_news.py` — 1.5 hours

```python
class TestFetchNews:
    """Mock-based tests."""
    @patch("scripts.fetch_news.retry_get")
    def test_parses_newsapi_response(self, mock_get)
        # Mock: valid NewsAPI JSON. Assert: returns list of dicts with sentiment.
    @patch("scripts.fetch_news.retry_get")
    def test_sentiment_attached(self, mock_get)
        # Assert: each article has "sentiment" and "sentiment_detail" keys.
    @patch("scripts.fetch_news.retry_get")
    def test_description_truncated(self, mock_get)
        # Article with 500-char description → truncated to 300.
    @patch("scripts.fetch_news.retry_get")
    def test_missing_api_key_skips(self)
        # No NEWS_API_KEY → function returns early.
    @patch("scripts.fetch_news.retry_get")
    def test_api_error_handled(self, mock_get)
        # Mock: 401 Unauthorized. Assert: logged and returns empty.
    @patch("scripts.fetch_news.retry_get")
    def test_five_categories_fetched(self, mock_get)
        # Assert: retry_get called 5 times (one per category).

class TestFetchNewsIntegration:
    """Live API tests — run with: make test-integration"""
    @pytest.mark.integration
    def test_live_newsapi_response_schema(self)
        # Call real API. Assert: response has expected keys.
        # Skip if NEWS_API_KEY not set.
```

### 7.4 `tests/scripts/test_fetch_markets.py` — 1 hour

```python
class TestFetchBitcoin:
    @patch("scripts.fetch_markets.retry_get")
    def test_parses_coingecko_response(self, mock_get)
    @patch("scripts.fetch_markets.retry_get")
    def test_handles_missing_price(self, mock_get)

class TestFetchGasPrice:
    @patch("scripts.fetch_markets.retry_get")
    def test_parses_eia_response(self, mock_get)
    @patch("scripts.fetch_markets.retry_get")
    def test_missing_key_skips(self)

class TestFetchMarketsIntegration:
    @pytest.mark.integration
    def test_live_coingecko(self)
    @pytest.mark.integration
    def test_live_eia(self)
```

### 7.5 `tests/scripts/test_fetch_rss.py` — 1 hour

```python
class TestLoadRssFeeds:
    def test_loads_from_config(self, tmp_path)
    def test_empty_feeds_list(self, tmp_path)
    def test_missing_config_file(self)

class TestFetchRssFeeds:
    @patch("scripts.fetch_rss.feedparser.parse")
    def test_parses_feed_entries(self, mock_parse)
    @patch("scripts.fetch_rss.feedparser.parse")
    def test_sentiment_computed(self, mock_parse)
    @patch("scripts.fetch_rss.feedparser.parse")
    def test_malformed_feed_handled(self, mock_parse)
    @patch("scripts.fetch_rss.feedparser.parse")
    def test_max_items_per_feed(self, mock_parse)
```

### 7.6 `tests/scripts/test_fetch_gdelt.py` — 1 hour

```python
class TestFetchGdeltEvents:
    @patch("scripts.fetch_gdelt.requests.get")
    def test_parses_gdelt_response(self, mock_get)
    @patch("scripts.fetch_gdelt.requests.get")
    def test_deduplicates_by_url(self, mock_get)
    @patch("scripts.fetch_gdelt.requests.get")
    def test_tone_parsed_as_float(self, mock_get)
    @patch("scripts.fetch_gdelt.requests.get")
    def test_retries_on_429(self, mock_get)
    @patch("scripts.fetch_gdelt.requests.get")
    def test_three_query_profiles_used(self, mock_get)

class TestFetchGdeltIntegration:
    @pytest.mark.integration
    def test_live_gdelt_api(self)
```

### 7.7 `tests/scripts/test_fetch_schumann.py` — 0.5 hours

```python
class TestParseHeartmath:
    def test_extracts_decimal_frequency(self)
        # HTML containing "7.83 Hz" → 7.83
    def test_extracts_integer_frequency(self)
        # HTML containing "8 Hz" → 8.0  (tests U-24 fix)
    def test_no_frequency_returns_none(self)
    def test_out_of_range_rejected(self)
        # "100.5 Hz" is not Schumann → None

class TestFetchSchumann:
    @patch("scripts.fetch_schumann.retry_get")
    def test_returns_data_on_success(self, mock_get)
    @patch("scripts.fetch_schumann.retry_get")
    def test_returns_none_on_failure(self, mock_get)

class TestFetchSchumannIntegration:
    @pytest.mark.integration
    def test_live_heartmath(self)
```

### 7.8 `tests/scripts/test_compute_planetary_hours.py` — 1 hour

```python
class TestComputePlanetaryHours:
    """Uses real astral computation with known date/location."""
    def test_spring_equinox_chicago(self)
        # 2026-03-20, lat=41.88, lon=-87.63
        # Assert: 24 hours returned, first hour starts at sunrise
    def test_day_ruler_wednesday_is_mercury(self)
        # Wednesday → Mercury rules first hour
    def test_day_ruler_sunday_is_sun(self)
    def test_hour_durations_sum_to_24h(self)
        # Sum of all 24 hour durations ≈ 1440 minutes
    def test_night_hours_longer_in_winter(self)
        # December date → night hours > day hours
    def test_equator_equal_hours(self)
        # lat=0, lon=0 → day ≈ night ≈ 12 hours each
    def test_zero_coordinates_warns(self)
        # lat=0, lon=0 → warning logged

class TestComputePlanetaryHoursIntegration:
    @pytest.mark.integration
    def test_live_computation_today(self)
        # Compute for today's date, assert valid structure
```

### 7.9 `tests/scripts/test_process_sensors.py` — 3 hours

**Largest untested file (412 stmts).** Test with synthetic sensor data files.

```python
@pytest.fixture
def sensor_session(tmp_path):
    """Create a synthetic sensor session directory with CSV files."""
    session = tmp_path / "session_2026-03-20"
    session.mkdir()
    # Write Accelerometer.csv with known values
    # Write Barometer.csv, Light.csv, Magnetometer.csv, Pedometer.csv
    # Write Activity.csv, Metadata.csv
    return session

class TestNsToEpochSec:
    def test_nanosecond_conversion(self)
    def test_zero(self)

class TestNsToWindowKey:
    def test_5min_window(self)
    def test_boundary_value(self)

class TestClassifyActivity:
    def test_stationary(self)      # std < 0.3
    def test_walking(self)         # 0.3 ≤ std < 1.5
    def test_running(self)         # 1.5 ≤ std < 5.0
    def test_vehicle(self)         # std ≥ 5.0

class TestProcessAccelerometer:
    def test_windowed_aggregation(self, sensor_session)
        # Known accelerometer data → expected magnitude, std per window
    def test_empty_file(self, sensor_session)
    def test_malformed_rows_skipped(self, sensor_session)

class TestProcessBarometer:
    def test_pressure_aggregation(self, sensor_session)
    def test_altitude_computed(self, sensor_session)

class TestProcessLight:
    def test_lux_aggregation(self, sensor_session)

class TestProcessMagnetometer:
    def test_magnitude_computed(self, sensor_session)

class TestProcessPedometer:
    def test_step_delta_computed(self, sensor_session)
        # Cumulative counter: [100, 200, 350] → deltas: [100, 150]
    def test_counter_reset_handled(self, sensor_session)
        # [100, 200, 50] → delta of 50 is reset, treated as 50

class TestProcessActivity:
    def test_dominant_activity(self, sensor_session)

class TestWriteSummaries:
    def test_movement_summary_written(self, sensor_session)
    def test_all_six_summaries_created(self, sensor_session)

class TestProcessSession:
    def test_full_session_processing(self, sensor_session)
        # Process entire session. Assert: 6 summary files created.
    def test_skips_already_processed(self, sensor_session)
        # Create 4+ summary files. Assert: session skipped.
    def test_partial_data_handled(self, sensor_session)
        # Only Accelerometer.csv present → only movement_summary written.

class TestFindSessions:
    def test_finds_sessions(self, tmp_path)
    def test_empty_directory(self, tmp_path)

class TestProcessSensorsIntegration:
    @pytest.mark.integration
    def test_real_session_if_available(self)
        # Only runs if ~/LifeData/raw/LifeData/logs/sensors has sessions
```

### 7.10 Acceptance Criteria

- [ ] `scripts/_http.py` coverage ≥ 90%
- [ ] `scripts/fetch_news.py` coverage ≥ 70%
- [ ] `scripts/fetch_markets.py` coverage ≥ 70%
- [ ] `scripts/fetch_rss.py` coverage ≥ 70%
- [ ] `scripts/fetch_gdelt.py` coverage ≥ 70%
- [ ] `scripts/fetch_schumann.py` coverage ≥ 80%
- [ ] `scripts/compute_planetary_hours.py` coverage ≥ 80%
- [ ] `scripts/process_sensors.py` coverage ≥ 60%
- [ ] All mock tests pass without network access
- [ ] Integration tests pass with `make test-integration` when API keys available
- [ ] `make test` (default) does NOT run integration tests

---

## 8. Execution Timeline

```
Week 1: Foundation
├── Day 1: Gap 3 (HMAC fix + .env.example)              [25 min]
├── Day 1: Gap 1A (quick fixes: parens, regex, etc.)     [30 min]
├── Day 2-3: Gap 1B (timestamp standardization)          [2 hours]
├── Day 3-5: Gap 1C (analysis layer tests)               [13 hours]
│   ├── test_correlator.py                               [4 hours]
│   ├── test_hypothesis.py                               [2 hours]
│   ├── test_reports.py                                  [4 hours]
│   └── test_anomaly.py expansion                        [3 hours]
│
Week 2-3: Module Tests
├── Gap 1D (post_ingest tests)                           [15 hours]
│   ├── behavior/test_post_ingest.py                     [4 hours]
│   ├── cognition/test_post_ingest.py                    [3 hours]
│   ├── body/test_post_ingest.py                         [1.5 hours]
│   ├── social/test_post_ingest.py                       [1.5 hours]
│   ├── oracle/test_post_ingest.py                       [1.5 hours]
│   ├── world/test_post_ingest.py                        [1 hour]
│   ├── meta/test_post_ingest.py                         [1.5 hours]
│   └── device+media+mind/test_post_ingest.py            [1 hour]
│
├── Checkpoint: run pytest --cov, verify ~70% overall     [15 min]
│
Week 3-4: Metrics Registry
├── Gap 2 (Metrics Registry + config refactor)           [15-20 hours]
│   ├── ModuleInterface extension                        [1 hour]
│   ├── 11 module manifest implementations               [11 hours]
│   ├── MetricsRegistry class + config schema            [3 hours]
│   ├── Anomaly/hypothesis/reports refactor              [4 hours]
│   └── Verify all existing + new tests pass             [1 hour]
│
Week 5: Scripts + CI
├── Gap 5 (script tests)                                 [10-12 hours]
│   ├── test_http.py                                     [1.5 hours]
│   ├── test_fetch_news.py                               [1.5 hours]
│   ├── test_fetch_markets.py                            [1 hour]
│   ├── test_fetch_rss.py                                [1 hour]
│   ├── test_fetch_gdelt.py                              [1 hour]
│   ├── test_fetch_schumann.py                           [0.5 hours]
│   ├── test_compute_planetary_hours.py                  [1 hour]
│   └── test_process_sensors.py                          [3 hours]
│
├── Gap 4 (GitHub Actions CI)                            [2 hours]
│
Week 6: Verification
├── Full pytest --cov run, verify ≥75%                   [15 min]
├── make lint, make typecheck                            [5 min]
├── Run make test-integration                            [15 min]
├── Update ULTIMATE_REVIEW.md coverage floor             [15 min]
└── Update CI --cov-fail-under to 70                     [5 min]
```

**Total estimated effort: 45-55 hours across 5-6 weeks**

---

## 9. Verification Protocol

After all gaps are closed, run this verification sequence:

```bash
# 1. All tests pass
make test

# 2. Coverage meets target
pytest tests/ -v --timeout=30 \
  --cov=core --cov=modules --cov=analysis --cov=scripts \
  --cov-report=term-missing --cov-fail-under=70

# 3. Type checking passes
make typecheck

# 4. Linting passes
make lint

# 5. Integration tests pass (requires API keys)
make test-integration

# 6. ETL dry run succeeds
make etl-dry

# 7. Full ETL run succeeds
make etl

# 8. Verify no hardcoded source_module in analysis layer
grep -rn "source_module.*=.*['\"]" analysis/ | grep -v "test_\|#\|def \|param"
# Expected: zero results

# 9. Verify all patterns/hypotheses in config
grep -c "name:" config.yaml | head -5
# Expected: 9 patterns + 10 hypotheses = 19+ entries

# 10. Coverage report
pytest tests/ --cov=core --cov=modules --cov=analysis --cov=scripts \
  --cov-report=html
# Open htmlcov/index.html and verify:
#   - Overall ≥ 75%
#   - analysis/ ≥ 70%
#   - modules/*/module.py average ≥ 50%
#   - scripts/ ≥ 30%
```

**Production readiness checklist:**

- [ ] Overall coverage ≥ 75%
- [ ] Zero hardcoded source_module strings in analysis/
- [ ] All anomaly patterns configurable in config.yaml
- [ ] All hypotheses configurable in config.yaml
- [ ] Report sections and trends configurable in config.yaml
- [ ] PII HMAC key mandatory (no hostname fallback)
- [ ] .env.example exists with all required keys
- [ ] Derived metric timestamps deterministic (no datetime.now)
- [ ] CSV parser assumption documented
- [ ] GitHub Actions CI runs on every push
- [ ] CI fails if coverage drops below floor
- [ ] Integration tests available for manual API validation
- [ ] `make test`, `make lint`, `make typecheck` all pass

---

*Execution strategy generated 2026-03-25 from ULTIMATE_REVIEW.md (R2) findings and detailed codebase exploration.*
