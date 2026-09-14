"""Context-manager convenience for scripts/tests that aren't inside a FastAPI request.

Usage:
    from jlmacro.database.session import session_scope
    with session_scope() as session:
        session.add(obj)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from jlmacro.database.engine import get_session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
