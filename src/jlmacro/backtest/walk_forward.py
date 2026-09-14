"""Walk-forward validation.

This platform's engines are rule-based (Phase 3/4/5), not fitted to a training
window, so there is no model to "train" the way walk-forward validation usually
implies - every `run_backtest` window already only uses data knowable as of its own
decision dates (see `jlmacro.backtest.engine`'s module docstring). What walk-forward
validation means *here* is: split history into consecutive, non-overlapping windows
and run the same procedure independently on each one, to check that performance is
reasonably consistent across different historical periods rather than being an
artifact of one lucky window. (Phase 11's ML layer is where an actual train/test
split with refitting will matter.)
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from jlmacro.backtest.engine import BacktestResult, run_backtest


@dataclass
class WalkForwardResult:
    windows: list[tuple[dt.date, dt.date]] = field(default_factory=list)
    results: list[BacktestResult] = field(default_factory=list)

    @property
    def mean_sharpe_ratio(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.sharpe_ratio for r in self.results) / len(self.results)

    @property
    def worst_max_drawdown(self) -> float:
        if not self.results:
            return 0.0
        return min(r.max_drawdown for r in self.results)


def walk_forward_windows(
    start: dt.date, end: dt.date, window_days: int
) -> list[tuple[dt.date, dt.date]]:
    """Consecutive, non-overlapping [start, end) windows of `window_days` calendar
    days each, covering [start, end] (the final window is clipped to `end`, so it may
    be shorter than the others).
    """
    windows: list[tuple[dt.date, dt.date]] = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + dt.timedelta(days=window_days), end)
        windows.append((window_start, window_end))
        window_start = window_end
    return windows


def run_walk_forward(
    session,
    symbols: list[str],
    *,
    start: dt.date,
    end: dt.date,
    window_days: int,
    nav0: float = 10_000_000.0,
    rebalance_frequency_days: int | None = None,
    weighting_method: str | None = None,
    target_volatility: float | None = None,
) -> WalkForwardResult:
    windows = walk_forward_windows(start, end, window_days)
    result = WalkForwardResult(windows=windows)

    for window_start, window_end in windows:
        backtest_result = run_backtest(
            session,
            symbols,
            start=window_start,
            end=window_end,
            nav0=nav0,
            rebalance_frequency_days=rebalance_frequency_days,
            weighting_method=weighting_method,
            target_volatility=target_volatility,
        )
        result.results.append(backtest_result)

    return result
