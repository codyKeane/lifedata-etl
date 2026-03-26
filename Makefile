.PHONY: install install-dev test test-perf test-integration test-cov lint format typecheck etl etl-dry status clean

VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy

DIRS := core/ modules/ analysis/ scripts/

# ── Install ──────────────────────────────────────────────────

install:
	$(PIP) install -r requirements.txt

install-dev:
	$(PIP) install -r requirements.txt -r requirements-dev.txt

# ── Quality ──────────────────────────────────────────────────

test:
	$(PYTEST) tests/ -v --timeout=30

test-perf:
	$(PYTEST) tests/ -v -m slow --timeout=600

test-integration:
	$(PYTEST) tests/ -v -m integration --timeout=60

test-cov:
	$(PYTEST) tests/ -v --cov=core --cov=modules --cov=analysis --cov=scripts --cov-report=term-missing

lint:
	$(RUFF) check $(DIRS)

format:
	$(RUFF) format $(DIRS)

typecheck:
	$(MYPY) core/ --strict

# ── ETL ──────────────────────────────────────────────────────

etl:
	cd $(CURDIR) && $(PYTHON) run_etl.py --report

etl-dry:
	cd $(CURDIR) && $(PYTHON) run_etl.py --dry-run

status:
	cd $(CURDIR) && $(PYTHON) run_etl.py --status

# ── Cleanup ──────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
