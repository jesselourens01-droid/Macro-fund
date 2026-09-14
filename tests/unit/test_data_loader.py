from __future__ import annotations

import datetime as dt

from jlmacro.data.loader import seed_instruments, seed_macro_data, seed_market_data


def test_seed_instruments_from_config(db_session):
    instruments = seed_instruments(db_session)
    assert len(instruments) > 20
    symbols = {i.symbol for i in instruments}
    assert "SPX" in symbols
    assert "EURUSD" in symbols
    assert "XAU" in symbols
    assert "US10Y" in symbols


def test_seed_instruments_is_idempotent(db_session):
    first = seed_instruments(db_session)
    second = seed_instruments(db_session)
    assert len(first) == len(second)


def test_seed_market_data_and_idempotency(db_session):
    instruments = seed_instruments(db_session)
    start, end = dt.date(2026, 1, 1), dt.date(2026, 2, 1)

    inserted_first = seed_market_data(db_session, instruments, start=start, end=end)
    assert inserted_first > 0

    inserted_second = seed_market_data(db_session, instruments, start=start, end=end)
    assert inserted_second == 0


def test_seed_macro_data_and_idempotency(db_session):
    seed_instruments(db_session)
    start, end = dt.date(2026, 1, 1), dt.date(2026, 6, 1)

    inserted_first = seed_macro_data(db_session, start=start, end=end)
    assert inserted_first > 0

    inserted_second = seed_macro_data(db_session, start=start, end=end)
    assert inserted_second == 0
