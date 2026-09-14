from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.backtest.engine import run_backtest
from jlmacro.backtest.monte_carlo import bootstrap_terminal_nav
from jlmacro.backtest.walk_forward import run_walk_forward
from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data

_START = dt.date(2024, 1, 1)
_END = dt.date(2026, 6, 30)


@pytest.fixture()
def seeded(db_session):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_END)
    seed_macro_data(db_session, start=_START, end=_END)
    db_session.flush()
    return [i.symbol for i in instruments]


def test_run_backtest_produces_a_period_per_rebalance_and_a_consistent_nav_curve(
    db_session, seeded
):
    result = run_backtest(
        db_session,
        seeded,
        start=dt.date(2025, 1, 1),
        end=dt.date(2026, 6, 30),
        nav0=10_000_000.0,
        rebalance_frequency_days=63,
    )

    assert len(result.periods) > 0
    nav_curve = result.nav_curve()
    assert nav_curve.iloc[0] == pytest.approx(10_000_000.0)
    assert nav_curve.iloc[-1] == pytest.approx(result.periods[-1].nav_end)

    # NAV compounds period-over-period - each nav_start must equal the prior nav_end.
    for prev, current in zip(result.periods[:-1], result.periods[1:], strict=True):
        assert current.nav_start == pytest.approx(prev.nav_end)

    assert 0.0 <= result.hit_rate <= 1.0


def test_run_backtest_periods_with_no_actionable_signal_are_held_flat(db_session, seeded):
    # A single symbol can never form a two-symbol covariance, so every period must
    # be held flat (zero return, empty weights) - the documented fail-safe behaviour.
    result = run_backtest(
        db_session,
        [seeded[0]],
        start=dt.date(2025, 1, 1),
        end=dt.date(2025, 6, 1),
        rebalance_frequency_days=30,
    )

    assert all(p.weights == {} for p in result.periods)
    assert all(p.period_return == 0.0 for p in result.periods)


def test_run_walk_forward_covers_the_full_range_across_its_windows(db_session, seeded):
    wf = run_walk_forward(
        db_session,
        seeded,
        start=dt.date(2025, 1, 1),
        end=dt.date(2026, 6, 30),
        window_days=180,
        rebalance_frequency_days=63,
    )

    assert len(wf.windows) == len(wf.results)
    assert wf.windows[0][0] == dt.date(2025, 1, 1)
    assert wf.windows[-1][1] == dt.date(2026, 6, 30)
    for backtest_result in wf.results:
        assert backtest_result.nav0 == 10_000_000.0


def test_monte_carlo_over_a_real_backtests_returns(db_session, seeded):
    backtest_result = run_backtest(
        db_session,
        seeded,
        start=dt.date(2025, 1, 1),
        end=dt.date(2026, 6, 30),
        rebalance_frequency_days=63,
    )
    period_returns = backtest_result.period_returns()
    if period_returns.empty:
        pytest.skip("no periods produced for this seed - nothing to bootstrap")

    mc_result = bootstrap_terminal_nav(
        period_returns, nav0=backtest_result.nav0, num_simulations=2_000, seed=11
    )

    p = mc_result.terminal_nav_percentiles
    assert p["p5"] <= p["p50"] <= p["p95"]
    assert 0.0 <= mc_result.probability_of_loss <= 1.0
