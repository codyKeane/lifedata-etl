"""
LifeData V4 — Config Validation Schema
core/config_schema.py

Pydantic models that mirror config.yaml structure. Called by the orchestrator
at startup to fail fast on missing fields, unresolved env vars, bad paths,
or invalid thresholds.
"""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class ConfigValidationError(Exception):
    """Raised when config.yaml fails validation.

    Collects all errors into a single message so the user can fix
    everything in one pass rather than fixing one error at a time.
    """

    def __init__(self, errors: list[str]):
        self.errors = errors
        bullet_list = "\n  • ".join(errors)
        super().__init__(
            f"Config validation failed ({len(errors)} error(s)):\n  • {bullet_list}"
        )


# ── Security ────────────────────────────────────────────────────


class SecurityConfig(BaseModel):
    syncthing_relay_enabled: bool = False
    syncthing_api_key: str = ""
    syncthing_device_fingerprint_desktop: str = ""
    syncthing_device_fingerprint_phone: str = ""
    module_allowlist: list[str]

    @field_validator("module_allowlist")
    @classmethod
    def allowlist_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("module_allowlist must contain at least one module")
        return v


# ── Per-module configs ──────────────────────────────────────────


class DeviceModuleConfig(BaseModel):
    enabled: bool = True


class EnvironmentModuleConfig(BaseModel):
    enabled: bool = True
    weather_api_key: str = ""
    airnow_api_key: str = ""
    ambee_api_key: str = ""
    home_lat: str = ""
    home_lon: str = ""
    seismic_radius_km: int = 500
    emf_sample_interval_sec: int = 30
    sound_sample_interval_min: int = 10
    lux_sample_interval_min: int = 5

    @field_validator("seismic_radius_km")
    @classmethod
    def seismic_radius_range(cls, v: int) -> int:
        if v < 1 or v > 20000:
            raise ValueError(f"seismic_radius_km={v} — must be 1–20000")
        return v


class BodyModuleConfig(BaseModel):
    enabled: bool = True
    sensor_logger_dir: str = "logs/sensors"
    sensor_window_minutes: int = 5
    caffeine_half_life_hours: float = 5.0
    sleep_target_hours: float = 7.5
    step_goal: int = 8000
    samsung_health_export_dir: str = ""
    health_connect_enabled: bool = False

    @field_validator("caffeine_half_life_hours")
    @classmethod
    def caffeine_range(cls, v: float) -> float:
        if v < 1.0 or v > 12.0:
            raise ValueError(f"caffeine_half_life_hours={v} — must be 1.0–12.0")
        return v

    @field_validator("sleep_target_hours")
    @classmethod
    def sleep_range(cls, v: float) -> float:
        if v < 3.0 or v > 14.0:
            raise ValueError(f"sleep_target_hours={v} — must be 3.0–14.0")
        return v

    @field_validator("step_goal")
    @classmethod
    def step_goal_range(cls, v: int) -> int:
        if v < 100 or v > 100_000:
            raise ValueError(f"step_goal={v} — must be 100–100000")
        return v


class MindModuleConfig(BaseModel):
    enabled: bool = True


class RSSFeed(BaseModel):
    name: str
    url: str
    category: str


class WorldModuleConfig(BaseModel):
    enabled: bool = True
    newsapi_key: str = ""
    eia_api_key: str = ""
    rss_feeds: list[RSSFeed] = []


class SocialModuleConfig(BaseModel):
    enabled: bool = True
    anonymize_contacts: bool = True
    app_overrides: dict[str, Any] = {}


class MediaModuleConfig(BaseModel):
    enabled: bool = True
    whisper_model: str = "base"
    auto_transcribe: bool = True
    photo_extract_exif: bool = True
    video_extract_thumbnail: bool = True
    sync_video_on_wifi_only: bool = True
    max_voice_duration_sec: int = 300
    photo_categories: list[str] = []

    @field_validator("max_voice_duration_sec")
    @classmethod
    def voice_duration_range(cls, v: int) -> int:
        if v < 1 or v > 3600:
            raise ValueError(f"max_voice_duration_sec={v} — must be 1–3600")
        return v


class MetaModuleConfig(BaseModel):
    enabled: bool = True


class CognitionModuleConfig(BaseModel):
    enabled: bool = True
    simple_rt_trials: int = 3
    choice_rt_trials: int = 5
    gonogo_trials: int = 10
    digit_span_start: int = 3
    digit_span_max_trials: int = 8
    time_production_targets: list[int] = [5, 10, 15, 30]
    typing_prompt_pool_size: int = 10
    passive_typing_enabled: bool = False
    impairment_zscore_threshold: float = 2.0
    baseline_window_days: int = 14
    # meta-style flags that live inside cognition config
    completeness_check: bool = True
    quality_check: bool = True
    storage_check: bool = True
    sync_lag_check: bool = True
    syncthing_relay_check: bool = True
    db_backup_check: bool = True
    audio_spool_check: bool = True
    retention_enforce: bool = True
    alert_on_critical: bool = True
    kde_connect_alerts: bool = False
    archive_threshold_gb: int = 10

    @field_validator("impairment_zscore_threshold")
    @classmethod
    def zscore_range(cls, v: float) -> float:
        if v < 0.5 or v > 5.0:
            raise ValueError(f"impairment_zscore_threshold={v} — must be 0.5–5.0")
        return v

    @field_validator("baseline_window_days")
    @classmethod
    def baseline_range(cls, v: int) -> int:
        if v < 3 or v > 365:
            raise ValueError(f"baseline_window_days={v} — must be 3–365")
        return v


class BehaviorModuleConfig(BaseModel):
    enabled: bool = True
    fragmentation_ceiling: int = 60
    min_dwell_sec: int = 1
    max_dwell_sec: int = 3600
    min_latency_ms: int = 200
    max_latency_ms: int = 30000
    step_goal: int = 8000
    sedentary_threshold: int = 50
    sedentary_min_bout_hours: int = 2
    baseline_window_days: int = 14
    restlessness_threshold: float = 2.0

    @field_validator("restlessness_threshold")
    @classmethod
    def restlessness_range(cls, v: float) -> float:
        if v < 0.5 or v > 5.0:
            raise ValueError(f"restlessness_threshold={v} — must be 0.5–5.0")
        return v

    @model_validator(mode="after")
    def dwell_order(self) -> "BehaviorModuleConfig":
        if self.min_dwell_sec >= self.max_dwell_sec:
            raise ValueError(
                f"min_dwell_sec ({self.min_dwell_sec}) must be < "
                f"max_dwell_sec ({self.max_dwell_sec})"
            )
        return self

    @model_validator(mode="after")
    def latency_order(self) -> "BehaviorModuleConfig":
        if self.min_latency_ms >= self.max_latency_ms:
            raise ValueError(
                f"min_latency_ms ({self.min_latency_ms}) must be < "
                f"max_latency_ms ({self.max_latency_ms})"
            )
        return self


class OracleModuleConfig(BaseModel):
    enabled: bool = True
    home_lat: str = ""
    home_lon: str = ""
    analysis_window_days: int = 90
    iching_default_method: str = "coin"
    auto_daily_casting: bool = True
    store_raw_question: bool = False
    rng_sample_interval_min: int = 30
    rng_batch_size: int = 100
    schumann_enabled: bool = True
    schumann_fetch_interval_hours: int = 1
    planetary_hours_enabled: bool = True
    planetary_hours_tag_events: bool = True

    @field_validator("analysis_window_days")
    @classmethod
    def analysis_window_range(cls, v: int) -> int:
        if v < 7 or v > 365:
            raise ValueError(f"analysis_window_days={v} — must be 7–365")
        return v


# ── Modules container ──────────────────────────────────────────


class ModulesConfig(BaseModel):
    device: DeviceModuleConfig = DeviceModuleConfig()
    environment: EnvironmentModuleConfig = EnvironmentModuleConfig()
    body: BodyModuleConfig = BodyModuleConfig()
    mind: MindModuleConfig = MindModuleConfig()
    world: WorldModuleConfig = WorldModuleConfig()
    social: SocialModuleConfig = SocialModuleConfig()
    media: MediaModuleConfig = MediaModuleConfig()
    meta: MetaModuleConfig = MetaModuleConfig()
    cognition: CognitionModuleConfig = CognitionModuleConfig()
    behavior: BehaviorModuleConfig = BehaviorModuleConfig()
    oracle: OracleModuleConfig = OracleModuleConfig()


# ── Analysis ────────────────────────────────────────────────────


class AnalysisConfig(BaseModel):
    correlation_window_days: int = 30
    anomaly_zscore_threshold: float = 2.0
    min_observations: int = 14
    min_confidence_for_correlation: float = 0.5
    weekly_correlation_metrics: list[str] = []

    @field_validator("anomaly_zscore_threshold")
    @classmethod
    def anomaly_zscore_range(cls, v: float) -> float:
        if v < 0.5 or v > 5.0:
            raise ValueError(f"anomaly_zscore_threshold={v} — must be 0.5–5.0")
        return v

    @field_validator("min_observations")
    @classmethod
    def min_obs_range(cls, v: int) -> int:
        if v < 2 or v > 365:
            raise ValueError(f"min_observations={v} — must be 2–365")
        return v

    @field_validator("min_confidence_for_correlation")
    @classmethod
    def min_confidence_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(
                f"min_confidence_for_correlation={v} — must be 0.0–1.0"
            )
        return v

    @field_validator("correlation_window_days")
    @classmethod
    def corr_window_range(cls, v: int) -> int:
        if v < 7 or v > 365:
            raise ValueError(f"correlation_window_days={v} — must be 7–365")
        return v


# ── Retention ───────────────────────────────────────────────────


class RetentionConfig(BaseModel):
    raw_files_days: int = 365
    log_rotation_days: int = 30
    parquet_archive_after_days: int = 90
    db_backup_keep_days: int = 7

    @field_validator("raw_files_days")
    @classmethod
    def raw_days_range(cls, v: int) -> int:
        if v < 1 or v > 3650:
            raise ValueError(f"raw_files_days={v} — must be 1–3650")
        return v

    @field_validator("db_backup_keep_days")
    @classmethod
    def backup_days_range(cls, v: int) -> int:
        if v < 1 or v > 365:
            raise ValueError(f"db_backup_keep_days={v} — must be 1–365")
        return v


# ── Schedule ────────────────────────────────────────────────────


class ScheduleConfig(BaseModel):
    etl_cron: str = ""
    news_cron: str = ""
    astro_cron: str = ""
    analysis_cron: str = ""


# ── Top-level ───────────────────────────────────────────────────


class LifeDataConfig(BaseModel):
    version: str
    timezone: str
    db_path: str
    raw_base: str
    media_base: str
    reports_dir: str
    log_path: str
    security: SecurityConfig
    modules: ModulesConfig = ModulesConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    retention: RetentionConfig = RetentionConfig()
    schedule: ScheduleConfig = ScheduleConfig()


class RootConfig(BaseModel):
    lifedata: LifeDataConfig


# ── Validation entry point ──────────────────────────────────────


def validate_config(config: dict) -> RootConfig:
    """Validate a loaded (env-resolved) config dict against the schema.

    Performs structural validation via pydantic, then runs additional
    semantic checks that pydantic alone cannot express (path existence,
    env var resolution, allowlist vs. module dirs).

    Raises:
        ConfigValidationError: with all detected issues.
    """
    errors: list[str] = []

    # ── Step 1: Structural validation via pydantic ──────────────
    try:
        parsed = RootConfig.model_validate(config)
    except Exception as e:
        # Extract individual errors from pydantic
        from pydantic import ValidationError

        if isinstance(e, ValidationError):
            for err in e.errors():
                loc = " → ".join(str(x) for x in err["loc"])
                errors.append(f"[{loc}] {err['msg']}")
        else:
            errors.append(str(e))
        raise ConfigValidationError(errors) from e

    ld = parsed.lifedata

    # ── Step 2: File paths must be expandable and parent writable ──
    path_fields = {
        "db_path": ld.db_path,
        "raw_base": ld.raw_base,
        "media_base": ld.media_base,
        "reports_dir": ld.reports_dir,
        "log_path": ld.log_path,
    }
    for name, raw_path in path_fields.items():
        expanded = Path(os.path.expanduser(raw_path))
        # For file paths, check the parent dir; for dirs, check the dir itself
        check_dir = expanded.parent if "." in expanded.name else expanded
        if not check_dir.exists():
            errors.append(
                f"{name}: parent directory does not exist — {check_dir}"
            )
        elif not os.access(str(check_dir), os.W_OK):
            errors.append(f"{name}: directory is not writable — {check_dir}")

    # ── Step 3: API key env vars resolve to non-empty values ────
    # Warn (don't fail) if missing — not all modules need all keys
    import logging

    _log = logging.getLogger("lifedata.config")
    api_key_checks: list[tuple[str, str, bool]] = [
        ("environment.weather_api_key", ld.modules.environment.weather_api_key, ld.modules.environment.enabled),
        ("environment.airnow_api_key", ld.modules.environment.airnow_api_key, ld.modules.environment.enabled),
        ("environment.ambee_api_key", ld.modules.environment.ambee_api_key, ld.modules.environment.enabled),
        ("world.newsapi_key", ld.modules.world.newsapi_key, ld.modules.world.enabled),
        ("world.eia_api_key", ld.modules.world.eia_api_key, ld.modules.world.enabled),
    ]
    for field_name, value, enabled in api_key_checks:
        if enabled and (not value or value.startswith("${")):
            _log.warning(
                "%s: API key is empty or unresolved (got '%s') — check .env file",
                field_name,
                value or "",
            )

    # ── Step 4: Syncthing relay must be disabled ────────────────
    if ld.security.syncthing_relay_enabled:
        errors.append(
            "security.syncthing_relay_enabled: must be false — "
            "LifeData must never route through third-party relay servers"
        )

    # ── Step 5: Module allowlist vs actual module directories ───
    modules_dir = Path(__file__).parent.parent / "modules"
    if modules_dir.exists():
        actual_modules = {
            d.name
            for d in modules_dir.iterdir()
            if d.is_dir() and (d / "module.py").exists()
        }
        for name in ld.security.module_allowlist:
            if name not in actual_modules:
                errors.append(
                    f"module_allowlist: '{name}' has no matching "
                    f"modules/{name}/module.py directory"
                )

    # ── Step 6: Timezone is valid ───────────────────────────────
    import zoneinfo

    try:
        zoneinfo.ZoneInfo(ld.timezone)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        errors.append(f"timezone: '{ld.timezone}' is not a valid IANA timezone")

    if errors:
        raise ConfigValidationError(errors)

    return parsed
