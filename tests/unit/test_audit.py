from __future__ import annotations

from jlmacro.models.audit import AuditLogEntry
from jlmacro.utils.audit import log_event


def test_log_event_writes_audit_entry(db_session):
    entry = log_event(
        db_session,
        event_type="risk_limit_breach",
        entity_type="portfolio",
        entity_id="1",
        payload={"limit": "hard_volatility_limit", "value": 0.14},
        actor="risk_engine",
    )
    assert entry.id is not None
    assert entry.entry_id  # UUID auto-generated

    fetched = db_session.get(AuditLogEntry, entry.id)
    assert fetched.event_type == "risk_limit_breach"
    assert fetched.payload["value"] == 0.14
    assert fetched.actor == "risk_engine"


def test_log_event_defaults_actor_to_system(db_session):
    entry = log_event(db_session, event_type="test_event", entity_type="test", entity_id="x")
    assert entry.actor == "system"
    assert entry.payload == {}
