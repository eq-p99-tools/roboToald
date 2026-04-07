"""Shared test fixtures for raid functionality tests."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy
import sqlalchemy.orm
from cryptography.fernet import Fernet

# Ensure encryption key exists before any test module imports SSO models (EncryptedType).
from roboToald import config

if not config.ENCRYPTION_KEY:
    config.ENCRYPTION_KEY = Fernet.generate_key().decode()


def make_fake_inter(**overrides: Any) -> MagicMock:
    """Build a ``MagicMock`` matching attributes used by RTE / DS / event slash commands.

    Defaults mirror typical guild/channel/user IDs. Pass keyword overrides to replace
    any attribute (e.g. ``guild_id=2``, ``author=...``).
    """
    inter = MagicMock(name="ApplicationCommandInteraction")
    guild = MagicMock()
    guild.id = 1
    guild.get_channel = MagicMock(return_value=MagicMock())
    inter.guild = guild
    inter.guild_id = 1

    author = MagicMock()
    author.id = 100
    author.display_name = "TestUser"
    author.send = AsyncMock()
    inter.author = author
    inter.user = author
    inter.user.roles = []

    channel = MagicMock()
    channel.id = 200
    channel.send = AsyncMock()
    channel.fetch_message = AsyncMock()
    channel.get_partial_message = MagicMock()
    channel.edit = AsyncMock()
    inter.channel = channel

    inter.response = AsyncMock()
    inter.followup = AsyncMock()
    inter.send = AsyncMock()
    inter.delete_original_response = AsyncMock()
    inter.component = MagicMock()
    inter.component.custom_id = ""

    for key, value in overrides.items():
        setattr(inter, key, value)
    return inter


@pytest.fixture()
def fake_inter() -> MagicMock:
    """Pre-built interaction mock for slash-command smoke tests."""
    return make_fake_inter()


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


@pytest.fixture()
def sso_session(monkeypatch):
    """In-memory SQLite with SSO schema; patches ``base.get_session`` to use this session."""
    import roboToald.db.models.sso as sso_module  # noqa: F401 — register models on Base.metadata
    from roboToald.db import base

    # ``check_same_thread=False`` allows Starlette ``TestClient`` (runs the app in another thread)
    # to use the same in-memory SQLite session as the test thread.
    engine = sqlalchemy.create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    base.Base.metadata.create_all(engine)
    SessionLocal = sqlalchemy.orm.sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    @contextlib.contextmanager
    def get_session_patched(autocommit=False):
        yield session

    monkeypatch.setattr(base, "get_session", get_session_patched)

    sso_module.invalidate_access_key_cache()
    sso_module.invalidate_revocation_cache()

    yield session

    sso_module.invalidate_access_key_cache()
    sso_module.invalidate_revocation_cache()
    session.close()
    engine.dispose()


@pytest.fixture()
def points_session(monkeypatch):
    """In-memory SQLite with points (DS) schema; patches ``base.get_session`` for tests."""
    import roboToald.db.models.points  # noqa: F401 — register PointsAudit etc. on Base.metadata

    from roboToald.db import base

    engine = sqlalchemy.create_engine(
        "sqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    base.Base.metadata.create_all(engine)
    SessionLocal = sqlalchemy.orm.sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    @contextlib.contextmanager
    def get_session_patched(autocommit=False):
        yield session

    monkeypatch.setattr(base, "get_session", get_session_patched)

    yield session

    session.close()
    engine.dispose()
