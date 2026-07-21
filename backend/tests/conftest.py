"""Test fixtures. The API runs against an in-memory SQLite DB (via a get_db
override) so tests need no Postgres and stay isolated per test."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(_engine):
    TestingSession = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def db_session(_engine):
    """A read session bound to the same DB the API writes to (for assertions)."""
    TestingSession = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
