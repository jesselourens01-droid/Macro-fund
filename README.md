# JL Global Macro Investment Platform

An institutional-grade research, risk and portfolio-management platform for an
Australian wholesale global macro hedge fund. Built for research, paper trading,
portfolio management, risk management and decision support.

**Live trading is disabled by default and requires explicit human approval and
broker-specific safeguards before any order can be transmitted.** See
`jlmacro.config.Settings.jlmacro_live_trading_enabled` and `src/jlmacro/execution/`.

## Status: Phase 1 + partial Phase 2 + Phase 3 (v1) + Phase 4 (v1) + Phase 5 (v1)

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

**Phase 3** (macro regime engine, v1 - transparent rule-based, per the spec's
"transparent models before complex models" principle; HMM/logistic/gradient-boosted
classifiers are explicitly future work):

- Point-in-time indicator scoring (`jlmacro.models.regime.scoring`): rolling z-scores
  and momentum computed only from data that was actually knowable as of a given date
- Category score aggregation + an 8-label regime classifier (`jlmacro.models.regime.engine`):
  Goldilocks / Reflation / Stagflation / Deflation / Recovery / Late Cycle / Risk-Off /
  Liquidity Crisis, plus a distance-from-boundary confidence heuristic
- Persisted `RegimeSnapshot` history per country, with duration/previous-regime/
  empirical-transition-probability queries
- `GET /regime`, `/regime/{country}`, `/regime/{country}/history` API endpoints
- A "Macro Regime" dashboard tab: the country x category matrix from the platform spec's
  Page 2, plus a per-country score history chart
- `scripts/compute_regime_snapshots.py` to (re)compute snapshots from current data

**Phase 4** (quantitative signal engine, v1 - real computations where the data
supports them, honestly-documented proxies elsewhere; see "Signal engine" below):

- Trend (`jlmacro.models.signals.trend`): real, first-principles multi-timeframe
  volatility-adjusted momentum + persistence, point-in-time correct
- Valuation (`...signals.valuation`): real FX real-rate differential and RATE real
  yield; documented proxies for EQUITY_INDEX (trend-deviation) and COMMODITY
  (US-real-rate sensitivity), since there's no real earnings/futures-curve data yet
- Positioning (`...signals.positioning`): an RSI-based crowding proxy, since there's
  no real CFTC/options data yet
- Catalyst (`...signals.catalyst`): projected-cadence upcoming releases and
  self-referential surprise (reusing the regime engine's z-scoring), since there's no
  real consensus-calendar data yet
- Macro factor (`...signals.macro_factor`): maps a country's regime (Phase 3) onto an
  asset-class-specific score via a configurable table
- Composite score (`...signals.composite`): weighted combination per
  `config/risk_limits.yaml`'s existing `signal_weights`/`investment_score_thresholds`,
  renormalized over whichever components are actually available
- `GET /signals`, `/signals/{symbol}` API endpoints, and a "Signals" dashboard tab
  (the platform spec's Page 5 "highest-ranking opportunities" view)

**Phase 5** (portfolio construction, v1 - covariance, weighting and sizing; see
"Portfolio construction" below):

- Covariance (`jlmacro.portfolio.covariance`): point-in-time daily returns (reusing
  the same PIT primitive as the signal engine) plus sample / EWMA / Ledoit-Wolf
  shrinkage covariance estimation and annualised volatility
- Sizing (`...portfolio.sizing`): `risk_budget = NAV x allowed_risk_percentage`
  (`config/risk_limits.yaml`'s existing `position_risk`, keyed by the Phase 4
  composite score's risk-unit band) / ATR-based stop distance
- Construction (`...portfolio.construction`): inverse-volatility and
  equal-risk-contribution weighting (the latter via Spinu's convex log-barrier
  formulation, solved with `cvxpy`), scaled to the fund's target volatility
  (`config/risk_limits.yaml`'s `target_volatility`)
- Exposures (`...portfolio.exposures`): gross/net exposure and asset-class/country/
  currency breakdowns from `Instrument`'s own fields, plus marginal/component
  contribution to risk (CCR sums exactly to total portfolio volatility - the correct
  answer to "where does our risk come from," which raw weight is not once correlation
  matters)
- `GET /portfolio/covariance`, `/portfolio/weights`, `/portfolio/sizing/{symbol}` and
  `POST /portfolio/exposures` API endpoints, and a "Portfolio" dashboard tab
- None of this persists a position or enforces `config/risk_limits.yaml`'s
  concentration/drawdown limits - it produces the numbers Phase 6's risk engine will
  check those limits against, and Phase 8's trade lifecycle will eventually persist

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
                 Portfolio/Position/Trade, RegimeSnapshot. models/regime holds the
                 macro regime engine (Phase 3); models/signals holds the quantitative
                 signal engine - trend/valuation/positioning/catalyst/composite
                 (Phase 4); models/ml holds the future ML research layer.
  portfolio/     Covariance, position sizing, weighting and exposures (Phase 5).
  risk/, execution/, backtest/, attribution/, reporting/, compliance/
                 Package placeholders for Phase 6+ - deliberately near-empty for now.
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

# 6. Compute macro regime snapshots from that data
python scripts/compute_regime_snapshots.py

# 7. Run the API
uvicorn jlmacro.api.main:app --reload
# -> http://localhost:8000/docs

# 8. Run the dashboard (in another terminal)
streamlit run dashboards/app.py
# -> http://localhost:8501
```

A `Makefile` wraps the common commands: `make install`, `make migrate`, `make seed`,
`make ingest-fred`, `make ingest-rba`, `make ingest-abs`, `make regime`, `make api`,
`make dashboard`, `make test`, `make lint`, `make format`, `make typecheck`.

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
  the drawdown governor's schedule, and investment-score thresholds. Read since Phase 1;
  `target_volatility`/`position_risk` are now actually used (Phase 5's sizing/
  construction); `concentration_limits`/the drawdown governor are still read-only and
  will be enforced by Phase 6's risk engine.
- `config/macro_indicators.yaml` - which countries/indicators the macro regime engine
  will track (Phase 3+).
- `config/signals.yaml` - signal-engine parameters (lookback windows, weights, proxy
  tuning) - see "Signal engine" below (Phase 4+).
- `config/portfolio.yaml` - covariance window/half-life and construction-method
  tuning; deliberately separate from `risk_limits.yaml` since these are implementation
  details, not fund risk policy (Phase 5+).
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

## Macro regime engine (Phase 3)

For each of the 6 configured countries (`config/macro_indicators.yaml`'s `countries`
list), the engine produces four category scores - Growth, Inflation, Monetary Policy,
Financial Conditions - each as both a continuous composite z-score and a discrete
-2..+2 bucket, then classifies one of 8 regimes: Goldilocks, Reflation, Stagflation,
Deflation, Recovery, Late Cycle, Risk-Off, Liquidity Crisis.

```bash
python scripts/compute_regime_snapshots.py --countries US,AU --start 2023-01-01 --end 2026-09-01
# or: make regime
```

- **Point-in-time scoring** (`jlmacro.models.regime.scoring`): every z-score/momentum
  is computed only from the vintage of each observation that was actually knowable as
  of the `as_of` date - the same discipline as the rest of the platform, just applied
  to derived statistics instead of raw values. `tests/unit/test_regime_scoring.py`
  proves a later revision can't leak into an earlier `as_of`'s z-score.
- **Category aggregation** (`jlmacro.models.regime.engine.compute_category_score`):
  the mean of a category's indicator z-scores, each optionally sign-flipped per
  `config/macro_indicators.yaml`'s per-indicator `invert` flag (e.g. a wider credit
  spread means *tighter*, not looser, financial conditions - see that file's comment
  on the sign convention). An indicator with too little history yet, or not tracked
  for a given country, is excluded from the average rather than treated as zero.
- **Regime classification** (`classify_regime`): a transparent, fully-readable decision
  tree over the four buckets (plus growth momentum, for the Recovery/Late-Cycle
  turning-point cases) - not a fitted model. This is deliberate: the platform spec
  calls for "transparent models before complex models" in Phase 3, with HMM/logistic/
  gradient-boosted classifiers as explicit later work. Every numeric threshold the tree
  consults lives in `config/regime.yaml`, not hard-coded.
- **Confidence** is a distance-from-decision-boundary heuristic (also configured in
  `config/regime.yaml`), not a probability - it says how solidly inside its
  bucket/threshold the deciding score sits, nothing more.
- **Duration / previous regime / transition probability**: derived from the persisted
  `RegimeSnapshot` history (`jlmacro.models.regime.regime_status`,
  `estimate_transition_matrix`) - the transition probabilities are a genuine empirical
  Markov frequency count over that country's own regime history, not a guess, but they
  only mean something once there's a reasonable amount of history to count over.

## Signal engine (Phase 4)

Five factor scores per instrument, each 0-100 and framed consistently as
"attractiveness of a LONG position" (50 = neutral; shorts read as the mirror image,
100 minus the score), combined into one composite via `config/risk_limits.yaml`'s
existing `signal_weights`/`investment_score_thresholds`:

```bash
curl "http://localhost:8000/signals/SPX"           # one instrument
curl "http://localhost:8000/signals?asset_class=fx" # ranked list, filterable
```

- **Trend** (`jlmacro.models.signals.trend`) is a real computation: volatility-adjusted
  momentum across 20/60/120/200-trading-day lookbacks (deliberately not a single
  moving-average crossover, per the platform spec) plus a persistence measure,
  point-in-time correct like every other engine here.
- **Valuation** (`...signals.valuation`) is real for FX (real-rate differential between
  the pair's two economies) and RATE (real yield = nominal yield minus latest CPI -
  both already on a comparable percentage-point scale in this platform's data model).
  For EQUITY_INDEX and COMMODITY it is an honestly-documented **proxy** (trend-deviation
  mean-reversion; US-real-rate sensitivity respectively) - this platform has no real
  earnings or futures-curve/inventory data source yet.
- **Positioning** (`...signals.positioning`) is an RSI(14)-based crowding **proxy** -
  there is no real CFTC/open-interest/options data source yet. Framed contrarian: an
  overbought reading lowers the score (squeeze/reversal risk for adding to a long), an
  oversold reading raises it.
- **Catalyst** (`...signals.catalyst`) projects upcoming releases from each
  indicator's own historical cadence (not a scheduled calendar - it can't know about a
  postponement or a one-off event) and scores recent self-referential surprise (how far
  the latest value sits from the indicator's own history, reusing the regime engine's
  z-scoring) - there is no real consensus-estimate data source yet.
- **Macro** (`...signals.macro_factor`) maps a country's current regime (Phase 3) onto
  an asset-class-specific score via `config/signals.yaml`'s `macro_score_by_regime`
  table - qualitative fund-analyst priors for a transparent v1, not fitted/backtested.
- **Composite** (`...signals.composite.compute_investment_score`) is the weighted
  average of whichever of the five components are actually available, with weights
  **renormalized** over just those (a missing component is excluded, never treated as
  zero) - see `tests/unit/test_signals_composite.py` for exactly what that means.
  `suggested_risk_units` (0 / 0 / 0.5 / 1 / 1.5, from the composite's score band) is
  **advisory only**: per the platform spec, "the system must never allow score alone to
  override portfolio-risk limits." Phase 5's sizing/construction consumes it as an
  input, but the risk engine with actual override authority still doesn't exist yet
  (Phase 6).

## Portfolio construction (Phase 5)

```bash
curl "http://localhost:8000/portfolio/covariance?symbols=SPX,US10Y,XAU,EURUSD&as_of=2026-08-31"
curl "http://localhost:8000/portfolio/weights?symbols=SPX,US10Y,XAU,EURUSD&weighting_method=equal_risk_contribution"
curl "http://localhost:8000/portfolio/sizing/SPX?nav=10000000&risk_units=1.0&direction=1"
curl -X POST "http://localhost:8000/portfolio/exposures" \
  -H "Content-Type: application/json" \
  -d '{"weights": {"SPX": 0.3, "US10Y": -0.2}, "as_of": "2026-08-31"}'
```

- **Covariance** (`jlmacro.portfolio.covariance.returns_matrix`) computes daily
  returns point-in-time (never forward-filled - a missing overlap day is dropped from
  every symbol via an inner join, rather than fabricating a return), then
  `sample_covariance` / `ewma_covariance` (recency-weighted) / `ledoit_wolf_covariance`
  (shrinkage towards a scaled-identity target - the platform's default, since it's
  the standard choice once the asset count isn't tiny relative to the sample size).
- **Sizing** (`...portfolio.sizing.compute_position_size`) implements the platform
  spec's formula directly: `risk_budget = NAV x allowed_risk_percentage` (reusing
  `config/risk_limits.yaml`'s existing `position_risk.normal_min/normal_max/
  high_conviction_max`, keyed by the risk-unit band the Phase 4 composite score
  already produces - no second, competing set of numbers), `position_size =
  risk_budget / stop_distance_pct` where `stop_distance_pct` is the trend engine's own
  ATR expressed as a fraction of price. Zero risk units (no conviction) fails safe to
  zero risk budget, not a "very small" position.
- **Construction** (`...portfolio.construction`) turns a covariance matrix into
  weights two ways: `inverse_volatility_weights` (simple, ignores correlation, the
  fallback) and `equal_risk_contribution_weights` (each position contributes equally
  to portfolio variance, accounting for correlation - the spec's more sophisticated
  default), the latter solved via Spinu's convex log-barrier formulation with `cvxpy`
  rather than a heuristic iteration, so the result is a verifiable optimum.
  `scale_to_target_volatility` then levers the whole weight set up or down to hit
  `config/risk_limits.yaml`'s `target_volatility` without changing the relative sizing
  between positions.
- **Exposures** (`...portfolio.exposures`) reports gross/net exposure and breakdowns
  by `Instrument`'s own `asset_class`/`country`/`currency` fields (no parallel
  taxonomy), plus marginal contribution to risk (`MCR_i = (Sigma w)_i / portfolio_vol`)
  and component contribution to risk (`CCR_i = w_i * MCR_i`, which sums exactly to
  total portfolio volatility - the correct way to answer "where does our risk actually
  come from," since a small, highly-correlated position can contribute disproportionately
  more risk than its weight alone would suggest).
- None of this enforces `config/risk_limits.yaml`'s `concentration_limits`,
  `soft_volatility_limit`/`hard_volatility_limit`, or the `drawdown_governor` schedule -
  that enforcement is Phase 6's risk engine. A weight or size coming back from this
  layer is a proposal, not an approved or executed trade; there is still no persisted
  `Position`/`Trade` row driving any of it (Phase 8).

## Known limitations

- Market-data providers (a real price vendor) and ECB/BoE/BoJ/World Bank/IMF macro
  adapters are not yet built - only FRED/RBA/ABS macro adapters exist so far.
- None of the FRED/RBA/ABS mappings in `config/macro_indicators.yaml` have been tested
  against live data end to end (see "Real data adapters" above for which are
  documentation-verified vs. best-guess) - do a live run before relying on them.
  ABS's GDP indicator has no mapping at all yet (data key not confirmed).
- The API has portfolio-construction endpoints (Phase 5) but no risk-limit enforcement,
  execution endpoints, or persisted positions yet, and nothing here can place an
  order - those land from Phase 6 onward as their respective engines are built.
- The dashboard has price/macro/regime/signals/portfolio browsers + system status, not
  the full 8-page CIO dashboard described in the platform spec - that requires the
  risk/attribution layers built in later phases.
- `Portfolio`/`Position`/`Trade` tables exist (for schema/migration stability) but are
  not yet populated by any business logic - Phase 5's weights/sizes are computed
  on demand and returned, never persisted.
- `equal_risk_contribution_weights` is solved with `cvxpy`'s CLARABEL backend (the
  ECOS backend some cvxpy examples default to isn't installed here); if you add solver
  backends, re-verify the fallback-to-inverse-volatility path in
  `jlmacro.portfolio.construction` still triggers correctly on a genuine non-convergence.
- The regime engine's decision tree, bucket thresholds and confidence heuristic are a
  transparent v1 by design (see "Macro regime engine" above) - they have not been
  back-tested against real historical regimes, only sanity-checked against synthetic
  data. Treat regime labels/confidence as illustrative until validated against real
  macro history.
- The signal engine's Positioning and Catalyst components, and its Equity/Commodity
  Valuation components, are documented proxies pending real CFTC/options/consensus-
  calendar/earnings/futures-curve data (see "Signal engine" above) - treat their scores
  as illustrative, not as a substitute for the real data sources they stand in for.
  `macro_score_by_regime`'s regime->score table is likewise an unvalidated fund-analyst
  prior, not backtested.
- `docker compose up` was validated via `docker compose config` (syntax/wiring) and by
  running every component (migrations, seeding, API, dashboard, full test suite)
  against an equivalent local PostgreSQL 16 instance; a Docker daemon was not available
  in the environment this was built in, so the full containerised stack itself should
  be smoke-tested once you run this locally. Likewise, the FRED/RBA/ABS adapters were
  validated against realistic fixtures, not live calls (this environment's network
  policy blocked all three hosts) - do one real run of each once you have internet
  access, before depending on them.

## Recommended next work

Remaining Phase 2: a real market-data provider (price vendor) behind
`BaseMarketDataProvider`, and optionally ECB/BoE/BoJ/World Bank/IMF macro adapters
following the same pattern as FRED/RBA/ABS - the regime and signal engines would
immediately benefit from broader real (non-synthetic) coverage across the 6 countries,
and a real market-data vendor would very likely also carry real earnings/fundamentals
data that could replace the signal engine's equity valuation proxy.

Phase 6 next: the risk engine (historical/parametric/Monte Carlo VaR, Expected
Shortfall, hypothetical scenario stress testing via `config/scenarios.yaml`, and the
drawdown governor schedule already sitting unenforced in `config/risk_limits.yaml`) -
the layer with actual authority to cut Phase 5's proposed sizes down, which neither
the signal engine's `suggested_risk_units` nor Phase 5's weights/sizes are.
