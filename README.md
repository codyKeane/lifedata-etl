# LifeData V4

LifeData V4 is a local-first ETL pipeline that collects behavioral and environmental data, normalizes it into unified events, and stores it in SQLite.

## Architecture

- **Core (`core/`)**: Execution engine (`orchestrator.py`), SQLite manager (`database.py`), universal event schema (`event.py`), and module interface abstractions.
- **Modules (`modules/`)**: Eight independent data ingestion modules (`device`, `body`, `mind`, `environment`, `social`, `world`, `media`, `meta`). Modules do not import from one another. Each module is transactionally isolated by a SQLite SAVEPOINT.
- **Analysis (`analysis/`)**: Scripted correlation (`correlator.py`), anomaly detection (`anomaly.py`), and daily report generation (`reports.py`).

## Data Flow

Data sources (Tasker logs via Syncthing, scheduled API scripts, offline sensors) write to the `raw/` directory. The orchestrator runs module parsers that convert raw updates into `Event` objects, which are inserted into the SQLite database. 

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Execution

```bash
# Run full pipeline
python run_etl.py

# Run specific module
python run_etl.py --module device

# Run without database writes (parsing test)
python run_etl.py --dry-run

# Run pipeline and generate daily report
python run_etl.py --report
```

## Data Principles

- The system relies on `config.yaml` for module structure and `.env` for API credentials.
- Ingestion scripts never alter source files in `raw/`.
- Pipeline executions are idempotent. Deduplication is handled via SHA-256 hashed event IDs.
