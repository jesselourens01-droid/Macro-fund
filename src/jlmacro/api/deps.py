"""FastAPI dependency helpers."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from jlmacro.database.engine import get_session_factory


def get_db() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
