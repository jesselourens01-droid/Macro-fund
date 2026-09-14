from __future__ import annotations

import datetime as dt
from itertools import pairwise

import pytest

from jlmacro.backtest.engine import (
    BacktestPeriodResult,
    BacktestResult,
    _populate_performance_stats,
    _rebalance_dates,
)


def test_rebalance_dates_spans_start_to_end_at_fixed_frequency():
    dates = _rebalance_dates(dt.date(2025, 1, 1), dt.date(2025, 2, 1), frequency_days=10)

    assert dates[0] == dt.date(2025, 1, 1)
    assert dates[-1] == dt.date(2025, 2, 1)
    # Every gap except possibly the last should equal the requested frequency.
    for a, b in pairwise(dates[:-1]):
        assert (b - a).days == 10


def test_rebalance_dates_handles_end_exactly_on_a_boundary():
    dates = _rebalance_dates(dt.date(2025, 1, 1), dt.date(2025, 1, 21), frequency_days=7)
    assert dates == [
        dt.date(2025, 1, 1),
        dt.date(2025, 1, 8),
        dt.date(2025, 1, 15),
        dt.date(2025, 1, 21),
    ]


def _make_result(period_returns: list[float], nav0: float = 1_000_000.0) -> BacktestResult:
    result = BacktestResult(
        start=dt.date(2025, 1, 1),
        end=dt.date(2025, 1, 1) + dt.timedelta(days=21 * len(period_returns)),
        nav0=nav0,
    )
    nav = nav0
    day = dt.date(2025, 1, 1)
    for r in period_returns:
        period_start = day
        period_end = day + dt.timedelta(days=21)
        nav_start = nav
        nav = nav * (1 + r)
        result.periods.append(
            BacktestPeriodResult(
                period_start=period_start,
                period_end=period_end,
                weights={},
                period_return=r,
                nav_start=nav_start,
                nav_end=nav,
            )
        )
        day = period_end
    return result


def test_nav_curve_and_period_returns_are_consistent_with_periods():
    result = _make_result([0.01, -0.02, 0.03])

    nav_curve = result.nav_curve()
    period_returns = result.period_returns()

    assert len(nav_curve) == 4  # nav0 plus one point per period
    assert nav_curve.iloc[0] == pytest.approx(1_000_000.0)
    assert len(period_returns) == 3
    assert period_returns.iloc[0] == pytest.approx(0.01)


def test_populate_performance_stats_computes_total_return_and_drawdown():
    result = _make_result([0.10, -0.20, 0.10])
    _populate_performance_stats(result)

    expected_total_return = 1.10 * 0.80 * 1.10 - 1.0
    assert result.total_return == pytest.approx(expected_total_return)
    # The only drawdown is the -20% period relative to the post-first-period peak.
    assert result.max_drawdown == pytest.approx(-0.20, abs=1e-9)
    assert result.hit_rate == pytest.approx(2 / 3)


def test_populate_performance_stats_handles_empty_periods_without_error():
    result = BacktestResult(start=dt.date(2025, 1, 1), end=dt.date(2025, 6, 1), nav0=1_000_000.0)
    _populate_performance_stats(result)

    assert result.total_return == 0.0
    assert result.sharpe_ratio == 0.0


def test_calmar_ratio_is_zero_when_there_is_no_drawdown():
    result = _make_result([0.01, 0.02, 0.01])
    _populate_performance_stats(result)

    assert result.max_drawdown == pytest.approx(0.0, abs=1e-12)
    assert result.calmar_ratio == 0.0
