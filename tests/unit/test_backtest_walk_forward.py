from __future__ import annotations

import datetime as dt
from itertools import pairwise

from jlmacro.backtest.walk_forward import walk_forward_windows


def test_walk_forward_windows_are_consecutive_and_non_overlapping():
    windows = walk_forward_windows(dt.date(2024, 1, 1), dt.date(2024, 7, 1), window_days=60)

    for (_, prev_end), (next_start, _) in pairwise(windows):
        assert prev_end == next_start

    assert windows[0][0] == dt.date(2024, 1, 1)
    assert windows[-1][1] == dt.date(2024, 7, 1)


def test_walk_forward_windows_final_window_is_clipped_not_overshot():
    windows = walk_forward_windows(dt.date(2024, 1, 1), dt.date(2024, 1, 10), window_days=7)

    assert windows[-1][1] == dt.date(2024, 1, 10)
    assert all(end <= dt.date(2024, 1, 10) for _, end in windows)


def test_walk_forward_windows_single_window_when_range_shorter_than_window():
    windows = walk_forward_windows(dt.date(2024, 1, 1), dt.date(2024, 1, 5), window_days=30)

    assert windows == [(dt.date(2024, 1, 1), dt.date(2024, 1, 5))]
