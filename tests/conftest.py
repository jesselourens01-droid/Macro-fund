"""Shared pytest fixtures.

Tests run against a real Postgres database (jlmacro_test) rather than SQLite, since the
schema uses Postgres-specific features (native ENUM types, JSON columns) and the whole
point of Phase 1 is to prove the platform against the same database engine used in
docker-compose. Point POSTGRES_* env vars at a disposable database before running tests
locally outside Docker; see README.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("POSTGRES_DB", "jlmacro_test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "jlmacro")
os.environ.setdefault("POSTGRES_PASSWORD", "jlmacro_dev_password")
os.environ.setdefault("JLMACRO_CONFIG_DIR", str(ROOT / "config"))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import jlmacro.models  # noqa: F401  (registers all mapped classes)
from jlmacro.config.settings import get_settings
from jlmacro.database.base import Base

get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    eng = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine) -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, future=True, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    from jlmacro.api.deps import get_db
    from jlmacro.api.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
