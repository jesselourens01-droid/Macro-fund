from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from jlmacro.models.enums import AssetClass, Frequency, MacroCategory, TradeDirection, TradeStatus
from jlmacro.models.instrument import Instrument
from jlmacro.models.macro_data import MacroDataPoint
from jlmacro.models.market_data import MarketDataPoint
from jlmacro.models.portfolio import Portfolio, Trade


def test_instrument_roundtrip(db_session):
    inst = Instrument(
        symbol="TEST_SPX",
        name="Test S&P 500",
        asset_class=AssetClass.EQUITY_INDEX,
        country="US",
        currency="USD",
        calendar="NYSE",
        metadata_json={"note": "unit test"},
    )
    db_session.add(inst)
    db_session.flush()

    fetched = db_session.get(Instrument, inst.id)
    assert fetched.symbol == "TEST_SPX"
    assert fetched.asset_class == AssetClass.EQUITY_INDEX
    assert fetched.metadata_json == {"note": "unit test"}
    assert fetched.is_active is True


def test_instrument_symbol_unique(db_session):
    db_session.add(Instrument(symbol="DUP", name="A", asset_class=AssetClass.FX, currency="USD"))
    db_session.flush()
    db_session.add(Instrument(symbol="DUP", name="B", asset_class=AssetClass.FX, currency="USD"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_market_data_point_pit_fields(db_session):
    inst = Instrument(symbol="TEST_FX", name="Test FX", asset_class=AssetClass.FX, currency="USD")
    db_session.add(inst)
    db_session.flush()

    point = MarketDataPoint(
        instrument_id=inst.id,
        timestamp=dt.datetime(2026, 1, 2, 21, 0, tzinfo=dt.UTC),
        frequency=Frequency.DAILY,
        close=1.2345,
        source="SYNTHETIC",
        effective_date=dt.date(2026, 1, 2),
        release_date=dt.date(2026, 1, 2),
    )
    db_session.add(point)
    db_session.flush()

    fetched = db_session.get(MarketDataPoint, (point.id, point.timestamp))
    assert fetched.close == pytest.approx(1.2345)
    assert fetched.ingestion_timestamp is not None
    assert fetched.original_value is None


def test_macro_data_point_revision_semantics(db_session):
    first = MacroDataPoint(
        country="US",
        indicator_code="TEST_CPI",
        category=MacroCategory.INFLATION,
        frequency=Frequency.MONTHLY,
        value=3.0,
        original_value=3.0,
        source="SYNTHETIC",
        effective_date=dt.date(2026, 1, 31),
        release_date=dt.date(2026, 2, 14),
        revision_date=dt.date(2026, 2, 14),
    )
    revision = MacroDataPoint(
        country="US",
        indicator_code="TEST_CPI",
        category=MacroCategory.INFLATION,
        frequency=Frequency.MONTHLY,
        value=3.2,
        original_value=3.0,
        revised_value=3.2,
        source="SYNTHETIC",
        effective_date=dt.date(2026, 1, 31),
        release_date=dt.date(2026, 2, 14),
        revision_date=dt.date(2026, 3, 14),
    )
    db_session.add_all([first, revision])
    db_session.flush()

    # release_date is constant across vintages of the same effective_date, so it must
    # NOT be used to answer "what did we know as of date X" - only revision_date (the
    # date each specific row's value became known) may be used for that. A query as-of
    # the first release date must not see the later revision, even though both rows
    # share the same release_date.
    from sqlalchemy import select

    as_of_first_release = db_session.scalars(
        select(MacroDataPoint)
        .where(MacroDataPoint.indicator_code == "TEST_CPI")
        .where(MacroDataPoint.revision_date <= dt.date(2026, 2, 14))
    ).all()
    assert len(as_of_first_release) == 1
    assert as_of_first_release[0].value == 3.0

    as_of_after_revision = db_session.scalars(
        select(MacroDataPoint)
        .where(MacroDataPoint.indicator_code == "TEST_CPI")
        .where(MacroDataPoint.revision_date <= dt.date(2026, 3, 14))
        .order_by(MacroDataPoint.revision_date.desc())
    ).first()
    assert as_of_after_revision.value == 3.2


def test_trade_default_status_is_idea(db_session):
    portfolio = Portfolio(name="Test Fund")
    inst = Instrument(
        symbol="TEST_TRADE", name="X", asset_class=AssetClass.COMMODITY, currency="USD"
    )
    db_session.add_all([portfolio, inst])
    db_session.flush()

    trade = Trade(
        portfolio_id=portfolio.id,
        instrument_id=inst.id,
        direction=TradeDirection.LONG,
    )
    db_session.add(trade)
    db_session.flush()

    assert trade.status == TradeStatus.IDEA
    assert trade.trade_id  # UUID auto-generated
