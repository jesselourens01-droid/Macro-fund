"""Portfolio-level exposure aggregation and risk decomposition.

Takes a set of *signed* weights (positive = long, negative = short, magnitude =
fraction of NAV - i.e. the output of jlmacro.portfolio.construction after applying
each position's direction) and answers two separate questions:
- "What do we own?" - gross/net exposure, broken down by asset class / country /
  currency (jlmacro.models.instrument.Instrument's own fields, not a parallel
  taxonomy).
- "Where does our risk actually come from?" - each position's marginal and component
  contribution to total portfolio volatility, which is not the same thing as its
  weight: a small, highly-correlated-with-everything-else position can contribute
  disproportionately more risk than its weight alone would suggest.

This module does not enforce config/risk_limits.yaml's concentration_limits - it
produces the numbers the risk engine (Phase 6) checks those limits against.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.models.instrument import Instrument


@dataclass
class ExposureSummary:
    gross: float  # sum of |w_i|
    net: float  # sum of w_i
    by_asset_class: dict[str, float] = field(default_factory=dict)
    by_country: dict[str, float] = field(default_factory=dict)
    by_currency: dict[str, float] = field(default_factory=dict)


def _instrument_lookup(session: Session, symbols: list[str]) -> dict[str, Instrument]:
    rows = session.execute(select(Instrument).where(Instrument.symbol.in_(symbols))).scalars()
    return {row.symbol: row for row in rows}


def compute_exposures(session: Session, weights: pd.Series) -> ExposureSummary:
    """`weights` is symbol -> signed weight (fraction of NAV). Any symbol not found in
    the instrument table is dropped from the by_* breakdowns (but still counts towards
    gross/net) rather than silently mis-bucketed - a missing instrument is a data
    problem worth surfacing, not papering over.
    """
    symbols = list(weights.index)
    instruments = _instrument_lookup(session, symbols)

    by_asset_class: dict[str, float] = {}
    by_country: dict[str, float] = {}
    by_currency: dict[str, float] = {}

    for symbol, weight in weights.items():
        instrument = instruments.get(str(symbol))
        if instrument is None:
            continue
        asset_class = instrument.asset_class.value
        by_asset_class[asset_class] = by_asset_class.get(asset_class, 0.0) + weight
        if instrument.country:
            by_country[instrument.country] = by_country.get(instrument.country, 0.0) + weight
        by_currency[instrument.currency] = by_currency.get(instrument.currency, 0.0) + weight

    return ExposureSummary(
        gross=float(weights.abs().sum()),
        net=float(weights.sum()),
        by_asset_class=by_asset_class,
        by_country=by_country,
        by_currency=by_currency,
    )


def marginal_contribution_to_risk(weights: pd.Series, covariance: pd.DataFrame) -> pd.Series:
    """MCR_i = (Sigma w)_i / portfolio_vol - how much portfolio volatility increases
    for a marginal increase in position i's weight, holding every other weight fixed.
    """
    aligned = weights.reindex(covariance.columns).fillna(0.0)
    w = aligned.to_numpy()
    sigma = covariance.to_numpy()
    portfolio_variance = float(w @ sigma @ w)
    if portfolio_variance <= 0:
        raise ValueError("portfolio variance must be positive")
    portfolio_vol = np.sqrt(portfolio_variance)
    marginal = (sigma @ w) / portfolio_vol
    return pd.Series(marginal, index=covariance.columns)


def component_contribution_to_risk(weights: pd.Series, covariance: pd.DataFrame) -> pd.Series:
    """CCR_i = w_i * MCR_i. Sums exactly to total portfolio volatility (Euler's
    theorem for the homogeneous-of-degree-1 volatility function), so CCR is the
    correct way to answer "how much of our total risk comes from this position" -
    weight alone is not, once correlation matters.
    """
    mcr = marginal_contribution_to_risk(weights, covariance)
    aligned = weights.reindex(covariance.columns).fillna(0.0)
    return aligned * mcr
