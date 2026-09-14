# JL Global Macro Investment Platform

An institutional-grade research, risk and portfolio-management platform for an
Australian wholesale global macro hedge fund. Built for research, paper trading,
portfolio management, risk management and decision support.

**Live trading is disabled by default and requires explicit human approval and
broker-specific safeguards before any order can be transmitted.** See
`jlmacro.config.Settings.jlmacro_live_trading_enabled` and `src/jlmacro/execution/`.

## Status: Phase 1

This repository currently implements **Phase 1** of the platform build-out:

- Repository/project scaffolding for all future phases
- PostgreSQL/TimescaleDB database architecture with Alembic migrations
- Point-in-time (PIT) data models for market and macro observations, designed to
  prevent look-ahead bias
- A configurable asset universe and fund risk-limit configuration (YAML, no code
  changes needed to adjust)
- A synthetic data generator so the entire stack runs with **zero external API keys**
- A read-only FastAPI service over the seeded data
- A basic Streamlit research dashboard
- An append-only audit log
- A test suite (pytest) covering config, models, data seeding and the API

See `docs/` and the phase list in the original platform specification for what comes
next. Do not build later phases until this one is reviewed.

## Architecture at a glance

```
config/          Fund business rules (risk limits, asset universe, macro indicators,
                 stress scenarios) as YAML - editable without touching code.
src/jlmacro/
  api/           FastAPI app (read-only in Phase 1).
  config/        pydantic-settings (.env) + YAML config loader.
  data/          Provider adapters (BaseDataProvider). Phase 1 ships synthetic
                 providers only; real adapters (FRED, RBA, ABS, ...) land in Phase 2.
  database/      SQLAlchemy engine/session/declarative base.
  models/        ORM models: Instrument, MarketDataPoint, MacroDataPoint, AuditLogEntry,
                 Portfolio/Position/Trade. models/{macro,signals,ml,regime} hold future
                 *statistical* model definitions (Phase 3+), not ORM models.
  portfolio/, risk/, execution/, backtest/, attribution/, reporting/, compliance/
                 Package placeholders for Phase 5+ - deliberately near-empty for now.
  utils/         Structured logging, ID generation, audit logging.
dashboards/      Streamlit app (presentation layer only - no business logic).
scripts/         Operational scripts (synthetic data generator).
alembic/         Database migrations.
tests/           pytest suite, mirrors src/ layout.
notebooks/       Research/validation notebooks - never production logic.
```

## Prerequisites

- Docker and Docker Compose (recommended path), **or**
- Python 3.12+ and a local PostgreSQL 16 instance for running outside Docker

## Quick start (Docker - recommended)

```bash
cp .env.example .env
# Edit .env if you want non-default credentials/ports.

docker compose up --build
```

This starts, in order: a TimescaleDB-enabled Postgres (`db`), a one-shot migration
runner (`migrate`), the API (`api`, http://localhost:8000), and the dashboard
(`dashboard`, http://localhost:8501).

The database starts empty. Seed it with synthetic data once the containers are up:

```bash
docker compose exec api python scripts/generate_synthetic_data.py
```

Then refresh the dashboard - it reads directly from the database.

## Manual / local development setup (no Docker)

```bash
# 1. Create and activate a virtualenv (Python 3.12+)
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install the project with dev dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Point POSTGRES_HOST/PORT/DB/USER/PASSWORD at a Postgres instance you control,
# e.g. a local `postgresql` service or `docker compose up db` on its own.

# 4. Run database migrations
alembic upgrade head

# 5. Seed synthetic data (no external API keys required)
python scripts/generate_synthetic_data.py

# 6. Run the API
uvicorn jlmacro.api.main:app --reload
# -> http://localhost:8000/docs

# 7. Run the dashboard (in another terminal)
streamlit run dashboards/app.py
# -> http://localhost:8501
```

A `Makefile` wraps the common commands: `make install`, `make migrate`, `make seed`,
`make api`, `make dashboard`, `make test`, `make lint`, `make format`, `make typecheck`.

## Running tests

Tests run against a real PostgreSQL database (schema uses native Postgres ENUM/JSON
types), not SQLite, so they exercise the same engine used in production. Point the
`POSTGRES_*` environment variables at a disposable database before running:

```bash
export POSTGRES_DB=jlmacro_test
export POSTGRES_HOST=localhost
export POSTGRES_USER=jlmacro
export POSTGRES_PASSWORD=<your password>

pytest -v
```

`tests/conftest.py` creates all tables at the start of the session and wraps every
test in a rolled-back transaction, so tests never leave data behind and can run
repeatedly against the same database.

## Code quality

```bash
ruff check src tests scripts dashboards   # lint
black src tests scripts dashboards        # format
mypy src                                  # type-check
```

All three are clean as of this Phase 1 delivery.

## Configuration philosophy

Nothing about the fund's business rules is hard-coded:

- `config/assets.yaml` - the tradeable asset universe. Add/remove an instrument here;
  `scripts/generate_synthetic_data.py` (and later, real data ingestion) picks it up
  automatically.
- `config/risk_limits.yaml` - volatility targets, position/theme/country risk limits,
  the drawdown governor's schedule, and investment-score thresholds. Read (but not yet
  enforced) starting Phase 1; enforcement is wired in Phase 5/6.
- `config/macro_indicators.yaml` - which countries/indicators the macro regime engine
  will track (Phase 3+).
- `config/scenarios.yaml` - historical and hypothetical stress scenarios (Phase 6+).
- `config/settings.yaml` - general platform/fund settings.
- `.env` (never committed) - environment-specific secrets and connection details only.

## Point-in-time (PIT) data discipline

Every market and macro observation carries `effective_date`, `release_date`,
`revision_date` and `ingestion_timestamp` alongside the value (see
`src/jlmacro/models/mixins.py`). Revisions are **new rows**, never in-place updates.
Any query answering "what did we know as of date X" must filter on the *vintage* date
(`revision_date`, falling back to `release_date`) - **never** on `release_date` alone,
since that field stays constant across every revision of a given period and filtering
on it would let a future revision leak into a query for an earlier date. This is
exactly the look-ahead bias the platform is designed to prevent, and it is unit-tested
(`tests/unit/test_models.py::test_macro_data_point_revision_semantics`).

## Known limitations (Phase 1)

- All market/macro data is **synthetic** - realistic-looking but not connected to any
  real economy or market. Real provider adapters (FRED, RBA, ABS, ECB, BoE, BoJ, World
  Bank, IMF, a market data vendor) are Phase 2.
- The API is read-only. There are no portfolio, risk, signal, or execution endpoints
  yet - those land from Phase 4 onward as their respective engines are built.
- The dashboard is a minimal research view (price/macro browsers + system status), not
  the full 8-page CIO dashboard described in the platform spec - that requires the
  portfolio/risk/attribution layers built in later phases.
- `Portfolio`/`Position`/`Trade` tables exist (for schema/migration stability) but are
  not yet populated by any business logic.
- `docker compose up` was validated via `docker compose config` (syntax/wiring) and by
  running every component (migrations, seeding, API, dashboard, full test suite)
  against an equivalent local PostgreSQL 16 instance; a Docker daemon was not available
  in the environment this was built in, so the full containerised stack itself should
  be smoke-tested once you run this locally.

## Recommended Phase 2

Real data ingestion: implement `FredProvider`, `RBAProvider`, `ABSProvider`, and a
market-data provider behind the existing `BaseDataProvider` interface
(`src/jlmacro/data/base.py`), each mapping its provider-specific schema onto the same
`MarketDataPoint`/`MacroDataPoint` fields the synthetic providers already populate, plus
basic data-quality validation (missing observations, duplicates, stale prices, outliers,
revision mismatches) before Phase 3's regime engine consumes the data.
