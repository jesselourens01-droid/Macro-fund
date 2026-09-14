from __future__ import annotations

import datetime as dt

from jlmacro.models.enums import AssetClass, RegimeLabel
from jlmacro.models.instrument import Instrument
from jlmacro.models.regime_snapshot import RegimeSnapshot
from jlmacro.models.signals.macro_factor import compute_macro_factor


def _insert_snapshot(db_session, country: str, regime: RegimeLabel) -> None:
    db_session.add(
        RegimeSnapshot(
            country=country, as_of=dt.date(2024, 6, 30), regime_label=regime, regime_confidence=0.8
        )
    )
    db_session.flush()


def test_macro_factor_equity_index_uses_country_regime(db_session):
    _insert_snapshot(db_session, "US", RegimeLabel.GOLDILOCKS)
    instrument = Instrument(
        symbol="TESTSPX",
        name="Test SPX",
        asset_class=AssetClass.EQUITY_INDEX,
        country="US",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_macro_factor(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score == 90  # goldilocks equity_index score from config/signals.yaml
    assert result.detail["regime"] == "goldilocks"


def test_macro_factor_none_without_regime_snapshot(db_session):
    instrument = Instrument(
        symbol="TESTNOREG",
        name="No regime",
        asset_class=AssetClass.EQUITY_INDEX,
        country="ZZ",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_macro_factor(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score is None


def test_macro_factor_rate_maps_de_to_ea(db_session):
    _insert_snapshot(db_session, "EA", RegimeLabel.DEFLATION)
    instrument = Instrument(
        symbol="TESTDE10Y",
        name="Test Bund",
        asset_class=AssetClass.RATE,
        country="DE",
        currency="EUR",
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_macro_factor(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score == 85  # deflation rate score - long duration attractive in deflation
    assert result.detail["regime"] == "deflation"


def test_macro_factor_fx_is_relative_to_both_countries(db_session):
    _insert_snapshot(db_session, "AU", RegimeLabel.RISK_OFF)
    _insert_snapshot(db_session, "US", RegimeLabel.RECOVERY)
    instrument = Instrument(
        symbol="TESTAUDUSD",
        name="Test AUDUSD",
        asset_class=AssetClass.FX,
        currency="USD",
        metadata_json={"base_currency": "AUD", "quote_currency": "USD"},
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_macro_factor(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score is not None
    assert result.score < 50.0  # AU risk_off vs US recovery -> unattractive to be long AUD
    assert result.detail == {"base_regime": "risk_off", "quote_regime": "recovery"}


def test_macro_factor_commodity_uses_us_regime(db_session):
    _insert_snapshot(db_session, "US", RegimeLabel.REFLATION)
    instrument = Instrument(
        symbol="TESTGOLD2", name="Test Gold", asset_class=AssetClass.COMMODITY, currency="USD"
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_macro_factor(db_session, instrument, as_of=dt.date(2024, 6, 30))
    assert result.score == 80  # reflation commodity score
