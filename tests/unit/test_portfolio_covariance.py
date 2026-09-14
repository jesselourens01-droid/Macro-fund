from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from jlmacro.models.enums import AssetClass, Frequency
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.portfolio.covariance import (
    annualised_volatility,
    ewma_covariance,
    ledoit_wolf_covariance,
    returns_matrix,
    sample_covariance,
)


def _seed_instrument(db_session, symbol: str) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=AssetClass.EQUITY_INDEX, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def _insert_bar(db_session, instrument: Instrument, day: dt.date, close: float) -> None:
    db_session.add(
        MarketDataPoint(
            instrument_id=instrument.id,
            timestamp=dt.datetime.combine(day, dt.time(21, 0), tzinfo=dt.UTC),
            frequency=Frequency.DAILY,
            close=close,
            source="TEST",
            effective_date=day,
            release_date=day,
            revision_date=day,
        )
    )


def _seed_prices(db_session, instrument: Instrument, start: dt.date, prices: list[float]) -> None:
    for i, price in enumerate(prices):
        _insert_bar(db_session, instrument, start + dt.timedelta(days=i), price)


def test_returns_matrix_aligns_on_common_dates_and_excludes_future_bars(db_session):
    a = _seed_instrument(db_session, "COVA")
    b = _seed_instrument(db_session, "COVB")
    start = dt.date(2024, 1, 1)
    # a has 10 days of prices; b is missing day index 5 entirely.
    _seed_prices(db_session, a, start, [100 + i for i in range(10)])
    for i in range(10):
        if i == 5:
            continue
        _insert_bar(db_session, b, start + dt.timedelta(days=i), 50 + i)
    db_session.flush()

    returns = returns_matrix(db_session, ["COVA", "COVB"], as_of=start + dt.timedelta(days=9))

    assert list(returns.columns) == ["COVA", "COVB"]
    # Day 5 (and the pct_change gap it creates) must be dropped from both columns -
    # an inner join, never forward-filled.
    assert (start + dt.timedelta(days=5)) not in returns.index
    assert not returns.isna().any().any()


def test_returns_matrix_respects_as_of_point_in_time(db_session):
    instrument = _seed_instrument(db_session, "COVPIT")
    start = dt.date(2024, 1, 1)
    _seed_prices(db_session, instrument, start, [100.0, 101.0, 102.0])
    # A bar dated after as_of must not leak into the returns series.
    _insert_bar(db_session, instrument, start + dt.timedelta(days=3), 999.0)
    db_session.flush()

    returns = returns_matrix(db_session, ["COVPIT"], as_of=start + dt.timedelta(days=2))

    assert len(returns) == 2
    assert returns["COVPIT"].abs().max() < 1.0  # no 999.0-sized jump present


def test_sample_covariance_matches_known_variance(db_session):
    a = _seed_instrument(db_session, "COVC")
    start = dt.date(2024, 1, 1)
    # Deterministic alternating returns so the sample variance is computable by hand.
    prices = [100.0]
    for i in range(40):
        prices.append(prices[-1] * (1.01 if i % 2 == 0 else 0.99))
    _seed_prices(db_session, a, start, prices)
    db_session.flush()

    returns = returns_matrix(db_session, ["COVC"], as_of=start + dt.timedelta(days=len(prices) - 1))
    cov = sample_covariance(returns)
    vol = annualised_volatility(returns)

    assert cov.shape == (1, 1)
    assert cov.loc["COVC", "COVC"] == pytest.approx(returns["COVC"].var() * 252)
    assert vol["COVC"] == pytest.approx(returns["COVC"].std() * np.sqrt(252))


def test_ewma_and_ledoit_wolf_covariance_are_symmetric_positive_definite(db_session):
    a = _seed_instrument(db_session, "COVD")
    b = _seed_instrument(db_session, "COVE")
    start = dt.date(2024, 1, 1)
    rng = np.random.default_rng(42)
    a_prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, 120))
    b_prices = 50 * np.cumprod(1 + rng.normal(0, 0.015, 120))
    _seed_prices(db_session, a, start, list(a_prices))
    _seed_prices(db_session, b, start, list(b_prices))
    db_session.flush()

    returns = returns_matrix(db_session, ["COVD", "COVE"], as_of=start + dt.timedelta(days=119))

    for cov in (ewma_covariance(returns), ledoit_wolf_covariance(returns)):
        np.testing.assert_allclose(cov.to_numpy(), cov.to_numpy().T, rtol=1e-10)
        eigenvalues = np.linalg.eigvalsh(cov.to_numpy())
        assert (eigenvalues > 0).all()
