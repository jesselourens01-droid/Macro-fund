from __future__ import annotations

import datetime as dt
import io
import json
import zipfile

import pandas as pd
import pytest

from jlmacro.models.enums import AssetClass, Frequency, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio, Trade
from jlmacro.reporting.investor import (
    build_data_room_export,
    data_quality_snapshot,
    market_pulse,
    portfolio_operating_summary,
)


def _market_point(instrument_id: int, day: dt.date, close: float) -> MarketDataPoint:
    return MarketDataPoint(
        instrument_id=instrument_id,
        timestamp=dt.datetime.combine(day, dt.time(21), tzinfo=dt.UTC),
        frequency=Frequency.DAILY,
        close=close,
        source="TEST",
        effective_date=day,
        release_date=day,
        revision_date=day,
    )


def test_market_pulse_returns_latest_change_and_coverage(db_session):
    instrument = Instrument(
        symbol="PULSE",
        name="Pulse Index",
        asset_class=AssetClass.EQUITY_INDEX,
        country="US",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()
    start = dt.date(2026, 1, 1)
    for offset in range(21):
        db_session.add(
            _market_point(instrument.id, start + dt.timedelta(days=offset), 100 + offset)
        )
    db_session.flush()

    pulse = market_pulse(db_session)
    row = pulse.loc[pulse["symbol"] == "PULSE"].iloc[0]
    assert row["last"] == pytest.approx(120.0)
    assert row["change_1d"] == pytest.approx(120 / 119 - 1)
    assert row["return_20d"] == pytest.approx(0.20)

    quality = data_quality_snapshot(db_session)
    assert quality.active_instruments == 1
    assert quality.instruments_with_prices == 1
    assert quality.price_coverage_pct == pytest.approx(1.0)
    assert quality.latest_market_date == start + dt.timedelta(days=20)


def test_portfolio_operating_summary_uses_only_live_trade_notional(db_session):
    portfolio = Portfolio(name="Investor Test")
    instrument = Instrument(
        symbol="BOOK",
        name="Book Asset",
        asset_class=AssetClass.FX,
        country="US",
        currency="USD",
    )
    db_session.add_all([portfolio, instrument])
    db_session.flush()
    db_session.add_all(
        [
            Trade(
                portfolio_id=portfolio.id,
                instrument_id=instrument.id,
                direction=TradeDirection.LONG,
                status=TradeStatus.OPEN,
                position_size=250_000,
            ),
            Trade(
                portfolio_id=portfolio.id,
                instrument_id=instrument.id,
                direction=TradeDirection.SHORT,
                status=TradeStatus.REDUCE,
                position_size=100_000,
            ),
            Trade(
                portfolio_id=portfolio.id,
                instrument_id=instrument.id,
                direction=TradeDirection.LONG,
                status=TradeStatus.IDEA,
                position_size=900_000,
            ),
        ]
    )
    db_session.flush()

    summary = portfolio_operating_summary(db_session, portfolio.id)
    assert summary["trades_total"] == 3
    assert summary["live_trades"] == 2
    assert summary["gross_notional"] == pytest.approx(350_000)
    assert summary["net_notional"] == pytest.approx(150_000)
    assert summary["status_counts"]["idea"] == 1


def test_data_room_export_contains_manifest_and_curated_csvs(db_session):
    quality = data_quality_snapshot(db_session)
    frame = pd.DataFrame([{"symbol": "SPX", "value": 1.0}])
    payload = build_data_room_export(
        market=frame,
        regimes=pd.DataFrame(),
        instruments=frame,
        audit=pd.DataFrame(),
        quality=quality,
        generated_at=dt.datetime(2026, 9, 15, tzinfo=dt.UTC),
    )

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "market_pulse.csv",
            "regimes.csv",
            "instruments.csv",
            "audit_trail.csv",
            "manifest.json",
        }
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["data_classification"] == "research"
        assert manifest["live_trading_enabled"] is False
