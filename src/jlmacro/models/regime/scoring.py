"""Point-in-time indicator scoring: rolling z-scores and momentum, computed only from
observations that were actually knowable as of a given date.

The critical discipline: for every effective_date period, pick the single vintage
whose vintage date (revision_date, falling back to release_date) is the latest one
<= as_of - i.e. reconstruct exactly what was known on that date, the same way FRED's
ALFRED vintages let jlmacro.data.macro.fred.FredProvider avoid look-ahead bias. Never
take "the latest row in the table" unconditionally; that reads the future.
"""

from __future__ import annotations

import datetime as dt
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from jlmacro.config import load_yaml_config
from jlmacro.models.macro_data import MacroDataPoint


def _vintage_date(row: MacroDataPoint) -> dt.date:
    return row.revision_date or row.release_date or row.effective_date


def point_in_time_history(
    session: Session,
    country: str,
    indicator_code: str,
    *,
    as_of: dt.date,
    window_days: int,
) -> list[tuple[dt.date, float]]:
    """Return [(effective_date, value)] sorted by effective_date, using only the
    vintage of each period that was known by `as_of`, restricted to a trailing
    `window_days` window. At most one value per effective_date: the latest vintage of
    that period which was already known as of `as_of`.
    """
    window_start = as_of - dt.timedelta(days=window_days)
    stmt = (
        select(MacroDataPoint)
        .where(MacroDataPoint.country == country)
        .where(MacroDataPoint.indicator_code == indicator_code)
        .where(MacroDataPoint.effective_date >= window_start)
        .where(MacroDataPoint.effective_date <= as_of)
    )
    rows = session.scalars(stmt).all()

    latest_by_period: dict[dt.date, MacroDataPoint] = {}
    for row in rows:
        vintage = _vintage_date(row)
        if vintage > as_of:
            continue  # Not yet known as of this date - excluded. This is the whole point.
        existing = latest_by_period.get(row.effective_date)
        if existing is None or _vintage_date(existing) < vintage:
            latest_by_period[row.effective_date] = row

    return sorted((period, row.value) for period, row in latest_by_period.items())


def rolling_zscore(
    session: Session,
    country: str,
    indicator_code: str,
    *,
    as_of: dt.date,
) -> float | None:
    """Z-score of the latest known value against its own trailing history, using only
    data knowable as of `as_of`. Returns None when there isn't enough history yet
    (config/regime.yaml's scoring.min_observations) rather than a noisy estimate.
    """
    config = load_yaml_config("regime")["scoring"]
    history = point_in_time_history(
        session, country, indicator_code, as_of=as_of, window_days=config["zscore_window_days"]
    )
    if len(history) < config["min_observations"]:
        return None

    values = [v for _, v in history]
    return _zscore_of_last(values)


def _zscore_of_last(values: list[float]) -> float:
    latest = values[-1]
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    stdev = math.sqrt(variance)
    if stdev == 0:
        return 0.0
    return (latest - mean) / stdev


def zscore_momentum(
    session: Session,
    country: str,
    indicator_code: str,
    *,
    as_of: dt.date,
) -> float | None:
    """Change in the rolling z-score over the configured lookback (in periods, not
    days), used to detect turning points (e.g. growth troughing -> RECOVERY). Computed
    causally: the earlier z-score is itself computed only from data knowable as of
    that earlier period's date, never with hindsight from `as_of`.
    """
    config = load_yaml_config("regime")["scoring"]
    lookback = config["momentum_lookback_periods"]

    history = point_in_time_history(
        session, country, indicator_code, as_of=as_of, window_days=config["zscore_window_days"]
    )
    if len(history) < config["min_observations"] + lookback:
        return None

    periods = [period for period, _ in history]
    earlier_as_of = periods[-1 - lookback]

    current = rolling_zscore(session, country, indicator_code, as_of=as_of)
    earlier = rolling_zscore(session, country, indicator_code, as_of=earlier_as_of)
    if current is None or earlier is None:
        return None
    return current - earlier
