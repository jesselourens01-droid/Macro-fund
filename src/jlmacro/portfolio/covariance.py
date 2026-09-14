"""Point-in-time returns and covariance estimation.

Reuses jlmacro.models.signals.pit's point-in-time closes (the same discipline used by
the trend/valuation signal engines) so a covariance matrix computed as of a given date
never includes a price that wasn't yet knowable then.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.signals.pit import point_in_time_closes

_TRADING_DAYS_PER_YEAR = 252


def returns_matrix(
    session: Session, symbols: list[str], *, as_of: dt.date, window_days: int | None = None
) -> pd.DataFrame:
    """Daily simple returns for each symbol, point-in-time as of `as_of`, aligned on
    dates every symbol has a price for (an inner join - deliberately never
    forward-filled, since a fabricated fill would misstate that day's actual
    knowable return).
    """
    config = load_yaml_config("portfolio")["covariance"]
    window_days = window_days if window_days is not None else config["window_days"]

    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        history = point_in_time_closes(session, symbol, as_of=as_of, window_days=window_days)
        if not history:
            continue
        dates, closes = zip(*history, strict=True)
        series[symbol] = pd.Series(closes, index=pd.Index(dates, name="date"))

    if not series:
        return pd.DataFrame()

    prices = pd.DataFrame(series).sort_index().dropna(how="any")
    return prices.pct_change().dropna(how="any")


def ewma_covariance(returns: pd.DataFrame, *, halflife_days: int | None = None) -> pd.DataFrame:
    """Annualised EWMA covariance matrix - recent observations weighted more heavily,
    so the estimate adapts faster to a regime shift than an equal-weighted sample
    covariance would.
    """
    config = load_yaml_config("portfolio")["covariance"]
    halflife_days = halflife_days if halflife_days is not None else config["ewma_halflife_days"]

    demeaned = returns - returns.mean()
    cov = demeaned.ewm(halflife=halflife_days).cov(pairwise=True).iloc[-len(returns.columns) :]
    cov = cov.droplevel(0)
    return cov.reindex(index=returns.columns, columns=returns.columns) * _TRADING_DAYS_PER_YEAR


def ledoit_wolf_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Annualised Ledoit-Wolf shrinkage covariance - shrinks the noisy sample
    covariance towards a structured (scaled-identity) target, which is standard
    practice whenever the number of assets isn't tiny relative to the sample size.
    """
    estimator = LedoitWolf().fit(returns.to_numpy())
    cov = pd.DataFrame(estimator.covariance_, index=returns.columns, columns=returns.columns)
    return cov * _TRADING_DAYS_PER_YEAR


def sample_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Plain annualised sample covariance - the baseline the other two estimators
    are compared against, not intended as the platform's actual default.
    """
    return returns.cov() * _TRADING_DAYS_PER_YEAR


def annualised_volatility(returns: pd.DataFrame) -> pd.Series:
    return returns.std() * np.sqrt(_TRADING_DAYS_PER_YEAR)
