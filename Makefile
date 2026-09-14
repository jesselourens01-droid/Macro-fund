.PHONY: help venv install up down build logs migrate seed test lint format typecheck api dashboard shell psql clean

help:
	@echo "Common targets: install up down build migrate seed test lint format typecheck api dashboard clean"

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
