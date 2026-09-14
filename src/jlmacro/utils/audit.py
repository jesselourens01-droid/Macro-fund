"""The single sanctioned way to write to the audit log.

Every module that mutates fund state (data revisions, model versions, signal changes,
portfolio changes, risk-limit breaches, manual overrides, trade approvals, orders,
fills, position changes) should call log_event rather than writing AuditLogEntry rows
directly, so there is one place to reason about what gets audited.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from jlmacro.models.audit import AuditLogEntry


def log_event(
    session: Session,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    actor: str = "system",
) -> AuditLogEntry:
    entry = AuditLogEntry(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=payload or {},
        actor=actor,
    )
    session.add(entry)
    session.flush()
    return entry
