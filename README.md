# LifeData V4

A local-first personal data observatory. Collects behavioral, environmental, and physiological data from an Android phone (Tasker + Syncthing), external APIs, and sensors. Normalizes everything into universal Event objects in SQLite. Surfaces correlations, anomalies, and daily reports.

## Architecture

- **Core (`core/`)** — ETL engine: orchestrator, SQLite manager (WAL + SAVEPOINT isolation), universal Event schema, Pydantic config validation.
- **Modules (`modules/`)** — 11 sovereign data modules: `device`, `body`, `mind`, `environment`, `social`, `world`, `media`, `meta`, `cognition`, `behavior`, `oracle`. No module imports another.
- **Analysis (`analysis/`)** — Pearson/Spearman correlation, z-score anomaly detection, multi-variable pattern alerts, hypothesis testing, daily markdown reports.
- **Scripts (`scripts/`)** — API fetchers with retry/backoff: news, markets, RSS, GDELT, Schumann resonance, planetary hours, sensor processing.

## Quick Start

```bash
source venv/bin/activate
pip install -r requirements.txt
python run_etl.py --report       # Full ETL + daily report
python run_etl.py --status       # Health summary
python run_etl.py --dry-run      # Parse without writing
python run_etl.py --module device # Single module
make test                         # Run 605 tests
```

## Principles

- **Raw data is sacred** — files in `raw/` are never modified.
- **Idempotent ingestion** — deterministic SHA-256 event IDs; re-running produces identical results.
- **Module sovereignty** — each module owns its parsing, schema, and failure modes. One crash cannot affect another.
- **Local-first** — no cloud dependencies. Syncthing device-to-device only (relays disabled).

## Documentation

| Document | Purpose |
|----------|---------|
| [`USER_GUIDE.md`](USER_GUIDE.md) | How to install, configure, and operate LifeData |
| [`docs/MASTER_WALKTHROUGH.md`](docs/MASTER_WALKTHROUGH.md) | Complete system bible — every moving part documented |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Security model, attack vectors, mitigations |
| [`docs/EXAMINATION_REPORT.md`](docs/EXAMINATION_REPORT.md) | Codebase audit findings and implementation status |
| [`docs/PERFORMANCE_BASELINE.md`](docs/PERFORMANCE_BASELINE.md) | Benchmark numbers for regression detection |
| [`docs/tasker/`](docs/tasker/) | Tasker task definitions (XML + manual creation guides) |

## Configuration

- `config.yaml` — Module settings, API params, analysis thresholds, cron schedules.
- `.env` — API keys (`chmod 600`, gitignored). Uses `${ENV_VAR}` placeholders resolved at runtime.

## License

Personal project. Not licensed for redistribution.
