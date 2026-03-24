.PHONY: install install-dev test lint format etl etl-dry-run

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
PYRIGHT := $(VENV)/bin/pyright

# ── Install ──────────────────────────────────────────────────

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements-dev.txt

# ── Quality ──────────────────────────────────────────────────

test:
	$(PYTEST) tests/ -v

lint:
	$(RUFF) check .
	$(PYRIGHT)

format:
	$(RUFF) format .
	$(RUFF) check --fix .

# ── ETL ──────────────────────────────────────────────────────

etl:
	$(PYTHON) run_etl.py

etl-dry-run:
	$(PYTHON) run_etl.py --dry-run
