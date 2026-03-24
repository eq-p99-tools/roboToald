"""Shared test fixtures for raid functionality tests."""

import os
import sys

import pytest
import sqlalchemy
import sqlalchemy.orm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def raid_session():
    """In-memory SQLite session that mirrors the raid schema for unit testing."""
    from roboToald.db.raid_base import RaidBase

    engine = sqlalchemy.create_engine("sqlite:///:memory:", echo=False)
    RaidBase.metadata.create_all(engine)
    Session = sqlalchemy.orm.sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()
