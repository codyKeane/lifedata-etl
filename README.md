# LifeData V4

A local-first personal data observatory. Collects behavioral, environmental, and physiological data from an Android phone (Tasker + Syncthing), external APIs, and sensors. Normalizes everything into universal Event objects in SQLite. Surfaces correlations, anomalies, and configurable daily/weekly/monthly reports. Every metric, analysis pattern, and report section is user-configurable.

## Architecture

- **Core (`core/`)** — ETL engine: orchestrator, SQLite manager (WAL + SAVEPOINT isolation), universal Event schema, Pydantic config validation, schema migration framework.
- **Modules (`modules/`)** — 11 sovereign data modules: `device`, `body`, `mind`, `environment`, `social`, `world`, `media`, `meta`, `cognition`, `behavior`, `oracle`. No module imports another. Each supports per-metric enable/disable via `disabled_metrics` config.
- **Analysis (`analysis/`)** — Pearson/Spearman correlation, z-score anomaly detection, config-driven compound pattern alerts (9 patterns), config-driven hypothesis testing (10 hypotheses), metrics registry, daily/weekly/monthly markdown reports.
- **Scripts (`scripts/`)** — API fetchers with retry/backoff: news, markets, RSS, GDELT, Schumann resonance, planetary hours, sensor processing.

## Quick Start

```bash
source venv/bin/activate
pip install -r requirements.txt
python run_etl.py --report           # Full ETL + daily report
python run_etl.py --weekly-report    # Generate weekly report
python run_etl.py --monthly-report   # Generate monthly report
python run_etl.py --status           # Health summary
python run_etl.py --dry-run          # Parse without writing
python run_etl.py --module device    # Single module
make test                            # Run 1291 tests
```

## Principles

- **Raw data is sacred** — files in `raw/` are never modified.
- **Idempotent ingestion** — deterministic SHA-256 event IDs; re-running produces identical results.
- **Module sovereignty** — each module owns its parsing, schema, and failure modes. One crash cannot affect another.
- **Local-first** — no cloud dependencies. Syncthing device-to-device only (relays disabled).
- **Configurable** — disable individual metrics, customize composite weights, define your own anomaly patterns and hypotheses, control which report sections appear.

## Documentation

| Document | Purpose |
|----------|---------|
| [`USER_GUIDE.md`](USER_GUIDE.md) | How to install, configure, and operate LifeData |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history and release notes |
| [`CONDENSED_GOALS.md`](CONDENSED_GOALS.md) | Project status: completed, deferred, and remaining objectives |
| [`docs/MASTER_WALKTHROUGH.md`](docs/MASTER_WALKTHROUGH.md) | Complete system bible — every moving part documented |
| [`docs/OPERATIONAL_RUNBOOK.md`](docs/OPERATIONAL_RUNBOOK.md) | Operations, maintenance, backup/recovery procedures |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Security model, attack vectors, mitigations |
| [`docs/EXAMINATION_REPORT.md`](docs/EXAMINATION_REPORT.md) | Codebase audit findings and implementation status |
| [`docs/PERFORMANCE_BASELINE.md`](docs/PERFORMANCE_BASELINE.md) | Benchmark numbers for regression detection |
| [`docs/tasker/`](docs/tasker/) | Tasker task definitions (XML + manual creation guides) |

## Configuration

- `config.yaml` — Module settings, per-metric disable lists, composite weights, analysis patterns/hypotheses/thresholds, report sections, cron schedules, data retention.
- `.env` — API keys and `PII_HMAC_KEY` (`chmod 600`, gitignored). Uses `${ENV_VAR}` placeholders resolved at runtime.

## License

Personal project. Not licensed for redistribution.
