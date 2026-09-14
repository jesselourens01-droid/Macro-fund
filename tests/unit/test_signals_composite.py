from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.models.enums import AssetClass
from jlmacro.models.instrument import Instrument
from jlmacro.models.signals.composite import _action_and_units, compute_investment_score


@pytest.mark.parametrize(
    "score,expected_action,expected_units",
    [
        (0.0, "no_position", 0.0),
        (54.9, "no_position", 0.0),
        (55.0, "watchlist", 0.0),
        (64.9, "watchlist", 0.0),
        (65.0, "half_unit", 0.5),
        (74.9, "half_unit", 0.5),
        (75.0, "full_unit", 1.0),
        (84.9, "full_unit", 1.0),
        (85.0, "max_unit", 1.5),
        (100.0, "max_unit", 1.5),
    ],
)
def test_action_and_units_thresholds(score, expected_action, expected_units):
    thresholds = {
        "no_position_max": 55,
        "watchlist_max": 65,
        "half_unit_max": 75,
        "full_unit_max": 85,
    }
    action, units = _action_and_units(score, thresholds)
    assert action == expected_action
    assert units == expected_units


def test_compute_investment_score_unknown_symbol_raises(db_session):
    with pytest.raises(ValueError, match="Unknown instrument symbol"):
        compute_investment_score(db_session, "DOES_NOT_EXIST", as_of=dt.date(2024, 6, 30))


def test_compute_investment_score_no_position_when_almost_all_components_missing(db_session):
    # A brand-new instrument with zero market/macro data behind it. catalyst_score
    # always returns a neutral 50.0 baseline rather than None (see catalyst.py), so
    # it's the only "available" component here; the composite should just equal that
    # neutral value, landing in no_position rather than erroring or producing
    # anything more opinionated than "neutral, no data."
    instrument = Instrument(
        symbol="TESTEMPTY",
        name="Empty",
        asset_class=AssetClass.EQUITY_INDEX,
        country="ZZ",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()

    result = compute_investment_score(db_session, "TESTEMPTY", as_of=dt.date(2024, 6, 30))
    assert result.composite_score == pytest.approx(50.0)
    assert result.action == "no_position"
    assert result.suggested_risk_units == 0.0
    assert result.detail["available_components"] == ["catalyst"]
    assert result.macro_score is None
    assert result.valuation_score is None
    assert result.trend_score is None
    assert result.positioning_score is None


def test_compute_investment_score_renormalizes_over_available_components(db_session, monkeypatch):
    """When some components are unavailable, the composite must be the weighted
    average over *only the available ones* (weights renormalized to sum to 1), not
    silently treat missing components as zero.
    """
    import jlmacro.models.signals.composite as composite_module

    instrument = Instrument(
        symbol="TESTPARTIAL",
        name="Partial",
        asset_class=AssetClass.EQUITY_INDEX,
        country="US",
        currency="USD",
    )
    db_session.add(instrument)
    db_session.flush()

    from jlmacro.models.signals.catalyst import CatalystResult
    from jlmacro.models.signals.macro_factor import MacroFactorResult
    from jlmacro.models.signals.positioning import PositioningResult
    from jlmacro.models.signals.trend import TrendResult
    from jlmacro.models.signals.valuation import ValuationResult

    monkeypatch.setattr(
        composite_module, "compute_macro_factor", lambda *a, **k: MacroFactorResult(score=80.0)
    )
    monkeypatch.setattr(
        composite_module,
        "compute_valuation",
        lambda *a, **k: ValuationResult(score=None, method="test"),
    )
    monkeypatch.setattr(
        composite_module, "compute_trend", lambda *a, **k: TrendResult(score=None, label="unknown")
    )
    monkeypatch.setattr(
        composite_module,
        "compute_positioning",
        lambda *a, **k: PositioningResult(score=None, label="unknown"),
    )
    monkeypatch.setattr(
        composite_module, "catalyst_score", lambda *a, **k: CatalystResult(score=60.0)
    )

    result = compute_investment_score(db_session, "TESTPARTIAL", as_of=dt.date(2024, 6, 30))

    # weights: macro=0.30, catalyst=0.15 -> renormalized: macro=0.30/0.45, catalyst=0.15/0.45
    expected = (0.30 * 80.0 + 0.15 * 60.0) / (0.30 + 0.15)
    assert result.composite_score == pytest.approx(expected)
    assert result.detail["available_components"] == ["catalyst", "macro"]
