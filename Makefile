.PHONY: help venv install up down build logs migrate seed ingest-fred ingest-rba ingest-abs regime test lint format typecheck api dashboard shell psql clean

help:
	@echo "Common targets: install up down build migrate seed ingest-fred ingest-rba ingest-abs regime test lint format typecheck api dashboard clean"

venv:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip

install:
	pip install -e ".[dev]"

up:
	docker compose up --build

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

migrate:
	alembic upgrade head

seed:
	python scripts/generate_synthetic_data.py

ingest-fred:
	python scripts/ingest_real_macro_data.py --source fred --countries US

ingest-rba:
	python scripts/ingest_real_macro_data.py --source rba --countries AU

ingest-abs:
	python scripts/ingest_real_macro_data.py --source abs --countries AU

regime:
	python scripts/compute_regime_snapshots.py

test:
	pytest -v

lint:
	ruff check src tests

format:
	black src tests scripts dashboards
	ruff check --fix src tests

typecheck:
	mypy src

api:
	uvicorn jlmacro.api.main:app --reload --host 0.0.0.0 --port 8000

dashboard:
	streamlit run dashboards/app.py

psql:
	docker compose exec db psql -U jlmacro -d jlmacro

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache
