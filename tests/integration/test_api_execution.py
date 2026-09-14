from __future__ import annotations

import datetime as dt

from jlmacro.data.loader import seed_instruments, seed_market_data

_TODAY = dt.datetime.now(dt.UTC).date()
_START = _TODAY - dt.timedelta(days=30)


def _seed_and_create_approved_trade(db_session, client):
    instruments = seed_instruments(db_session)
    seed_market_data(db_session, instruments, start=_START, end=_TODAY)
    db_session.flush()

    resp = client.post("/portfolios", json={"name": "Execution API Test Fund"})
    portfolio_id = resp.json()["id"]

    resp = client.post(
        "/trades",
        json={
            "portfolio_id": portfolio_id,
            "symbol": "SPX",
            "direction": "long",
            "thesis": "execution API test",
        },
    )
    trade_id = resp.json()["trade_id"]
    client.post(f"/trades/{trade_id}/transition", json={"new_status": "approved", "actor": "jesse"})
    return trade_id


def test_open_and_close_trade_via_paper_broker(db_session, client):
    trade_id = _seed_and_create_approved_trade(db_session, client)

    resp = client.post(
        f"/trades/{trade_id}/open-order",
        json={"quantity": 100, "as_of": _TODAY.isoformat(), "actor": "jesse"},
    )
    assert resp.status_code == 200
    order = resp.json()
    assert order["status"] == "filled"
    assert order["filled_price"] > 0

    resp = client.get(f"/trades/{trade_id}")
    assert resp.json()["status"] == "open"
    assert resp.json()["entry_price"] == order["filled_price"]

    resp = client.post(
        f"/trades/{trade_id}/close-order",
        json={"quantity": 100, "as_of": _TODAY.isoformat(), "actor": "jesse"},
    )
    assert resp.status_code == 200
    close_order = resp.json()
    assert close_order["status"] == "filled"

    resp = client.get(f"/trades/{trade_id}")
    assert resp.json()["status"] == "closed"


def test_open_order_on_non_approved_trade_fails(db_session, client):
    seed_instruments(db_session)
    db_session.flush()
    resp = client.post("/portfolios", json={"name": "Execution API Test Fund 2"})
    portfolio_id = resp.json()["id"]
    resp = client.post(
        "/trades",
        json={
            "portfolio_id": portfolio_id,
            "symbol": "SPX",
            "direction": "long",
            "thesis": "x",
        },
    )
    trade_id = resp.json()["trade_id"]  # still IDEA, not APPROVED

    resp = client.post(
        f"/trades/{trade_id}/open-order",
        json={"quantity": 100, "as_of": _TODAY.isoformat(), "actor": "jesse"},
    )
    assert resp.status_code == 400
