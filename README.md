# JL Global Macro Investment Platform

An institutional-grade research, risk and portfolio-management platform for an
Australian wholesale global macro hedge fund. Built for research, paper trading,
portfolio management, risk management and decision support.

**Live trading is disabled by default and requires explicit human approval and
broker-specific safeguards before any order can be transmitted.** See
`jlmacro.config.Settings.jlmacro_live_trading_enabled` and `src/jlmacro/execution/`.

## Status: Phase 1 + partial Phase 2

**Phase 1** (complete):

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

**Phase 2** (macro data adapters only so far - market-data providers and the
data-quality-driven ingestion pipeline into the regime engine are still to come):

- Real macro data adapters for **FRED** (US), **RBA** (AU) and **ABS** (AU) behind the
  same `BaseDataProvider` interface the synthetic providers use
- A data-quality validation module (missing observations, duplicates, stale values,
  impossible values, outliers, revision mismatches)
- Two macro ingestion paths in `jlmacro.data.loader`: one for providers that expose a
  genuine vintage history (FRED, via ALFRED), one for providers that only expose
  current values (RBA, ABS) with local diff-based revision detection
- `scripts/ingest_real_macro_data.py` to run real ingestion

See `docs/` and the phase list in the original platform specification for what comes
next. Do not build later phases until this one is reviewed.

## Architecture at a glance

```
config/          Fund business rules (risk limits, asset universe, macro indicators,
                 stress scenarios) as YAML - editable without touching code.
src/jlmacro/
  api/           FastAPI app (read-only in Phase 1).
  config/        pydantic-settings (.env) + YAML config loader.
  data/          Provider adapters (BaseDataProvider): synthetic (Phase 1) plus real
                 FRED/RBA/ABS macro adapters and a data-quality module (Phase 2).
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
`make ingest-fred`, `make ingest-rba`, `make ingest-abs`, `make api`, `make dashboard`,
`make test`, `make lint`, `make format`, `make typecheck`.

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

## Real data adapters (Phase 2)

Three real macro data adapters exist behind `BaseDataProvider`
(`src/jlmacro/data/base.py`), alongside the Phase 1 synthetic ones:

- **`FredProvider`** (`src/jlmacro/data/macro/fred.py`) - US Federal Reserve Economic
  Data. Requires a free API key: get one at
  https://fred.stlouisfed.org/docs/api/api_key.html and set `FRED_API_KEY` in `.env`.
  Uses FRED's ALFRED vintage history (`realtime_start`/`realtime_end`), so it returns
  genuine historical revisions, not just current values.
- **`RBAProvider`** (`src/jlmacro/data/macro/rba.py`) - Reserve Bank of Australia
  statistical-table CSVs. No API key required.
- **`ABSProvider`** (`src/jlmacro/data/macro/abs.py`) - Australian Bureau of Statistics
  Data API (SDMX-JSON). No API key required.

Run real ingestion with:

```bash
python scripts/ingest_real_macro_data.py --source fred --countries US
python scripts/ingest_real_macro_data.py --source rba  --countries AU
python scripts/ingest_real_macro_data.py --source abs  --countries AU
# or: make ingest-fred / make ingest-rba / make ingest-abs
```

Which (country, indicator_code) maps to which series is entirely config-driven -
`config/macro_indicators.yaml`'s `provider_series_ids` section, never hard-coded in the
adapters. This platform was built in a network-restricted sandbox that could not reach
`rba.gov.au`, `api.data.abs.gov.au`, or `api.stlouisfed.org` directly, so none of these
mappings have been end-to-end smoke-tested against live data yet - but their
verification status differs:

- **RBA's entries are marked "VERIFY"** - best-known table/series codes, not checked
  against any live source.
- **ABS's `CPI_HEADLINE` mapping (`ABS,CPI,2.0.0` / `1.10001.10.50.M`) was confirmed
  against ABS's own published Data API documentation** (reachable via search even
  though the API itself wasn't) - it's a worked example straight from ABS's docs, not a
  guess. ABS's `GDP` mapping was deliberately left **unmapped**: the dataflow ID
  (`ANA_AGG`) is confirmed, but no verified data key could be found without a live call
  to ABS's dataflow/datastructure endpoints - see the comment in
  `config/macro_indicators.yaml` for exactly what to call to add it.

Either way, do one live run before depending on any of them, and the adapters'
HTTP/parsing logic is unit-tested against fixtures modeled on each API's real
documented response shape (FRED's ALFRED JSON, RBA's CSV table layout, ABS's
SDMX-JSON), so that part is trustworthy independent of the exact codes.

**FRED vs. RBA/ABS point-in-time handling differs, deliberately:** FRED's ALFRED API
gives a true vintage history, so `FredProvider` records already carry a real
`release_date`/`revision_date` and get inserted via
`jlmacro.data.loader.ingest_macro_vintage_records` (shared with the synthetic
provider). RBA and ABS only expose *current* values with no public vintage feed, so
`RBAProvider`/`ABSProvider` deliberately leave `release_date`/`revision_date` as
`None`, and `jlmacro.data.loader.ingest_snapshot_macro_data` stamps them at the moment
of ingestion - creating a new revision row only when a value has actually changed since
the last time it was fetched. That is the only point-in-time-honest choice when a
source doesn't tell you when a value was first published: never claim to have known
something on a date before the ingestion that actually observed it.

Every ingestion path runs `jlmacro.data.quality.validate_macro_records` first and logs
any issues (missing observations, duplicate vintages, stale/impossible values,
outliers, revision mismatches); a batch containing an error-level issue is rejected
rather than inserted.

## Known limitations

- Market-data providers (a real price vendor) and ECB/BoE/BoJ/World Bank/IMF macro
  adapters are not yet built - only FRED/RBA/ABS macro adapters exist so far.
- None of the FRED/RBA/ABS mappings in `config/macro_indicators.yaml` have been tested
  against live data end to end (see "Real data adapters" above for which are
  documentation-verified vs. best-guess) - do a live run before relying on them.
  ABS's GDP indicator has no mapping at all yet (data key not confirmed).
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
  be smoke-tested once you run this locally. Likewise, the FRED/RBA/ABS adapters were
  validated against realistic fixtures, not live calls (this environment's network
  policy blocked all three hosts) - do one real run of each once you have internet
  access, before depending on them.

## Recommended Phase 2 (remaining) / Phase 3

Remaining Phase 2 work: a real market-data provider (price vendor) behind
`BaseMarketDataProvider`, and optionally ECB/BoE/BoJ/World Bank/IMF macro adapters
following the same pattern as FRED/RBA/ABS. Then Phase 3: the macro regime engine
(growth/inflation/policy/financial-conditions scores) consuming this data.
