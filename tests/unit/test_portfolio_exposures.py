from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.portfolio.exposures import (
    component_contribution_to_risk,
    compute_exposures,
    marginal_contribution_to_risk,
)


def _seed_instrument(
    db_session, symbol: str, asset_class: AssetClass, country: str | None, currency: str
) -> Instrument:
    instrument = Instrument(
        symbol=symbol, name=symbol, asset_class=asset_class, country=country, currency=currency
    )
    db_session.add(instrument)
    db_session.flush()
    return instrument


def test_compute_exposures_aggregates_gross_net_and_breakdowns(db_session):
    _seed_instrument(db_session, "EXPA", AssetClass.EQUITY_INDEX, "US", "USD")
    _seed_instrument(db_session, "EXPB", AssetClass.RATE, "US", "USD")
    _seed_instrument(db_session, "EXPC", AssetClass.FX, None, "AUD")
    db_session.flush()

    weights = pd.Series({"EXPA": 0.30, "EXPB": -0.20, "EXPC": 0.15})
    summary = compute_exposures(db_session, weights)

    assert summary.gross == pytest.approx(0.65)
    assert summary.net == pytest.approx(0.25)
    assert summary.by_asset_class["equity_index"] == pytest.approx(0.30)
    assert summary.by_asset_class["rate"] == pytest.approx(-0.20)
    assert summary.by_asset_class["fx"] == pytest.approx(0.15)
    assert summary.by_country == {"US": pytest.approx(0.10)}
    assert summary.by_currency["USD"] == pytest.approx(0.10)
    assert summary.by_currency["AUD"] == pytest.approx(0.15)


def test_compute_exposures_skips_unknown_symbols_in_breakdowns_but_counts_gross_net(db_session):
    _seed_instrument(db_session, "EXPD", AssetClass.EQUITY_INDEX, "US", "USD")
    db_session.flush()

    weights = pd.Series({"EXPD": 0.20, "UNKNOWN_SYMBOL": 0.10})
    summary = compute_exposures(db_session, weights)

    assert summary.gross == pytest.approx(0.30)
    assert summary.net == pytest.approx(0.30)
    assert summary.by_asset_class == {"equity_index": pytest.approx(0.20)}


def test_component_contribution_to_risk_sums_to_portfolio_volatility():
    symbols = ["A", "B", "C"]
    correlations = np.array(
        [
            [1.0, 0.3, -0.1],
            [0.3, 1.0, 0.2],
            [-0.1, 0.2, 1.0],
        ]
    )
    vols = np.array([0.12, 0.20, 0.30])
    cov = pd.DataFrame(np.outer(vols, vols) * correlations, index=symbols, columns=symbols)
    weights = pd.Series({"A": 0.5, "B": 0.3, "C": 0.2})

    ccr = component_contribution_to_risk(weights, cov)
    w = weights.to_numpy()
    portfolio_vol = float(np.sqrt(w @ cov.to_numpy() @ w))

    assert ccr.sum() == pytest.approx(portfolio_vol)


def test_marginal_contribution_to_risk_rejects_zero_variance():
    cov = pd.DataFrame([[0.0]], index=["A"], columns=["A"])
    weights = pd.Series({"A": 0.0})
    with pytest.raises(ValueError, match="positive"):
        marginal_contribution_to_risk(weights, cov)
