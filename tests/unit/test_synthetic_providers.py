from __future__ import annotations

import datetime as dt

from jlmacro.data.macro.synthetic import SyntheticMacroDataProvider
from jlmacro.data.market.synthetic import SyntheticMarketDataProvider


def test_market_provider_is_deterministic():
    provider = SyntheticMarketDataProvider()
    kwargs = {
        "identifiers": ["SPX"],
        "start": dt.date(2026, 1, 1),
        "end": dt.date(2026, 1, 31),
        "asset_classes": {"SPX": "equity_index"},
    }
    run1 = provider.fetch(**kwargs)
    run2 = provider.fetch(**kwargs)
    assert run1 == run2
    assert len(run1) > 0
    assert all(r["close"] > 0 for r in run1)


def test_market_provider_no_lookahead_fields_leaked():
    provider = SyntheticMarketDataProvider()
    records = provider.fetch(
        identifiers=["EURUSD"],
        start=dt.date(2026, 1, 1),
        end=dt.date(2026, 1, 10),
        asset_classes={"EURUSD": "fx"},
    )
    for rec in records:
        assert rec["effective_date"] <= rec["timestamp"].date()
        assert rec["release_date"] == rec["effective_date"]


def test_macro_provider_generates_revisions():
    provider = SyntheticMacroDataProvider()
    records = provider.fetch(
        identifiers=["CPI_HEADLINE"],
        start=dt.date(2020, 1, 1),
        end=dt.date(2026, 1, 1),
        countries=["US"],
    )
    assert len(records) > 0
    revisions = [r for r in records if r["revised_value"] is not None]
    # With ~35% revision probability over 6 years of monthly data, expect at least some.
    assert len(revisions) > 0
    for rec in revisions:
        assert rec["revision_date"] > rec["release_date"]


def test_macro_provider_release_date_after_effective_date():
    provider = SyntheticMacroDataProvider()
    records = provider.fetch(
        identifiers=["GDP"],
        start=dt.date(2024, 1, 1),
        end=dt.date(2025, 1, 1),
        countries=["AU"],
    )
    for rec in records:
        assert rec["release_date"] > rec["effective_date"]
        assert rec["country"] == "AU"
