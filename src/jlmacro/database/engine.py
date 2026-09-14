"""Engine/session factory. All application code obtains sessions through here rather
than constructing its own engine, so there is exactly one place that knows the DB URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from jlmacro.config import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI-style dependency / general-purpose session getter."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
