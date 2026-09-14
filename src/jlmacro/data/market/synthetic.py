"""Synthetic market data provider.

Generates deterministic (seeded per-symbol), asset-class-aware daily OHLCV series so
Phase 1 can seed a realistic-looking database with zero external API calls. Not intended
to resemble any real market outcome - purely for wiring/testing the platform end-to-end.
Real providers (Phase 2) implement the same BaseMarketDataProvider interface.
"""

from __future__ import annotations

import datetime as dt
import zlib
from typing import Any

import numpy as np
import pandas_market_calendars as mcal

from jlmacro.data.base import BaseMarketDataProvider

# Rough starting levels / annualised vol / annual drift per asset class, just enough to
# make synthetic series look plausible (equities trend up and are volatile, FX is
# range-bound, rates are low-vol mean-reverting, commodities are volatile).
_ASSET_CLASS_PARAMS: dict[str, dict[str, float]] = {
    "equity_index": {"start": 4500.0, "vol": 0.16, "drift": 0.07, "mean_revert": 0.0},
    "rate": {"start": 4.0, "vol": 0.15, "drift": 0.0, "mean_revert": 0.02},
    "fx": {"start": 1.0, "vol": 0.09, "drift": 0.0, "mean_revert": 0.0},
    "commodity": {"start": 70.0, "vol": 0.28, "drift": 0.02, "mean_revert": 0.0},
}

_INSTRUMENT_START_OVERRIDES: dict[str, float] = {
    "XAU": 1950.0,
    "XAG": 24.0,
    "WTI": 78.0,
    "BRENT": 82.0,
    "HG": 3.8,
    "NG": 2.6,
    "EURUSD": 1.08,
    "GBPUSD": 1.27,
    "USDJPY": 148.0,
    "AUDUSD": 0.66,
    "USDCAD": 1.36,
    "NZDUSD": 0.61,
    "USDCHF": 0.88,
    "EURJPY": 160.0,
    "AUDJPY": 97.0,
    "EURGBP": 0.85,
    "AS51": 7300.0,
    "HSI": 18000.0,
    "NKY": 33000.0,
    "TPX": 2400.0,
    "DAX": 16000.0,
    "UKX": 7600.0,
    "SX5E": 4300.0,
    "RTY": 2000.0,
    "NDX": 15500.0,
    "SPX": 4500.0,
}


def _seed_for_symbol(symbol: str) -> int:
    return zlib.crc32(symbol.encode("utf-8")) % (2**32)


class SyntheticMarketDataProvider(BaseMarketDataProvider):
    name = "SYNTHETIC"

    def fetch(
        self,
        *,
        identifiers: list[str],
        start: dt.date,
        end: dt.date,
        asset_classes: dict[str, str] | None = None,
        calendar: str = "NYSE",
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        asset_classes = asset_classes or {}
        cal = mcal.get_calendar(calendar)
        schedule = cal.schedule(start_date=start, end_date=end)
        sessions = [d.date() for d in schedule.index]

        records: list[dict[str, Any]] = []
        for symbol in identifiers:
            asset_class = asset_classes.get(symbol, "equity_index")
            params = _ASSET_CLASS_PARAMS.get(asset_class, _ASSET_CLASS_PARAMS["equity_index"])
            start_level = _INSTRUMENT_START_OVERRIDES.get(symbol, params["start"])
            records.extend(self._generate_series(symbol, sessions, start_level, params))
        return records

    @staticmethod
    def _generate_series(
        symbol: str,
        sessions: list[dt.date],
        start_level: float,
        params: dict[str, float],
    ) -> list[dict[str, Any]]:
        rng = np.random.default_rng(_seed_for_symbol(symbol))
        n = len(sessions)
        if n == 0:
            return []

        daily_vol = params["vol"] / np.sqrt(252)
        daily_drift = params["drift"] / 252
        mean_revert = params["mean_revert"]

        log_level = np.log(max(start_level, 1e-6))
        levels = np.empty(n)
        level = start_level
        for i in range(n):
            shock = rng.normal(loc=0.0, scale=1.0)
            if mean_revert > 0:
                # Simple mean-reverting process for rate-like instruments, in level space.
                level = level + mean_revert * (start_level - level) + params["vol"] * shock
                level = max(level, 0.01)
            else:
                log_level = log_level + daily_drift - 0.5 * daily_vol**2 + daily_vol * shock
                level = float(np.exp(log_level))
            levels[i] = level

        records: list[dict[str, Any]] = []
        prev_close = start_level
        for i, session_date in enumerate(sessions):
            close = float(levels[i])
            intraday_range = abs(close - prev_close) * 0.5 + close * daily_vol * 0.3
            open_ = prev_close
            high = max(open_, close) + intraday_range * rng.uniform(0.0, 0.5)
            low = min(open_, close) - intraday_range * rng.uniform(0.0, 0.5)
            volume = float(rng.uniform(1e5, 1e6))

            records.append(
                {
                    "symbol": symbol,
                    "timestamp": dt.datetime.combine(session_date, dt.time(21, 0), tzinfo=dt.UTC),
                    "frequency": "daily",
                    "open": round(open_, 6),
                    "high": round(high, 6),
                    "low": round(low, 6),
                    "close": round(close, 6),
                    "volume": round(volume, 2),
                    "source": "SYNTHETIC",
                    "effective_date": session_date,
                    "release_date": session_date,
                    "revision_date": None,
                    "original_value": None,
                    "revised_value": None,
                }
            )
            prev_close = close
        return records
