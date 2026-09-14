from __future__ import annotations

import datetime as dt

import pytest

from jlmacro.data.loader import seed_instruments, seed_market_data

_TODAY = dt.datetime.now(dt.UTC).date()
_START = _TODAY - dt.timedelta(days=400)


@pytest.fixture()
def seeded_with_trade(db_session, client):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_TODAY)
    db_session.flush()

    resp = client.post("/portfolios", json={"name": "NAV API Test Fund"})
    portfolio_id = resp.json()["id"]

    resp = client.post(
        "/trades",
        json={
            "portfolio_id": portfolio_id,
            "symbol": "SPX",
            "direction": "long",
            "thesis": "NAV API test",
            "entry_price": 4300.0,
            "position_size": 500_000.0,
        },
    )
    trade_id = resp.json()["trade_id"]
    client.post(f"/trades/{trade_id}/transition", json={"new_status": "approved", "actor": "jesse"})
    client.post(f"/trades/{trade_id}/transition", json={"new_status": "open", "actor": "jesse"})

    return portfolio_id


def test_get_nav_endpoint(client, seeded_with_trade):
    resp = client.get(
        "/nav",
        params={
            "portfolio_id": seeded_with_trade,
            "start": _START.isoformat(),
            "as_of": _TODAY.isoformat(),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["starting_capital"] > 0
    assert body["nav_gross"] != 0
    assert body["high_water_mark"] >= body["nav_gross"] + body["drawdown"] * body["nav_gross"] - 1
    assert body["nav_net"] <= body["nav_gross"]


def test_get_nav_history_endpoint(client, seeded_with_trade):
    resp = client.get(
        "/nav/history",
        params={
            "portfolio_id": seeded_with_trade,
            "start": _START.isoformat(),
            "end": _TODAY.isoformat(),
            "frequency_days": 30,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["nav"]) > 1
    assert _START.isoformat() in body["nav"]
    assert _TODAY.isoformat() in body["nav"]


def test_get_attribution_endpoint(client, seeded_with_trade):
    resp = client.get(
        "/nav/attribution",
        params={
            "portfolio_id": seeded_with_trade,
            "as_of": _TODAY.isoformat(),
            "group_by": "symbol",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "SPX" in body["breakdown"]


def test_get_nav_for_portfolio_with_no_trades_equals_starting_capital(client, db_session):
    seed_instruments(db_session)
    db_session.flush()
    resp = client.post("/portfolios", json={"name": "Empty NAV Fund"})
    portfolio_id = resp.json()["id"]

    resp = client.get(
        "/nav",
        params={
            "portfolio_id": portfolio_id,
            "start": _START.isoformat(),
            "as_of": _TODAY.isoformat(),
        },
    )
    body = resp.json()
    assert body["nav_gross"] == pytest.approx(body["starting_capital"])
    assert body["drawdown"] == pytest.approx(0.0)
    assert body["performance_fee_accrued"] == 0.0
