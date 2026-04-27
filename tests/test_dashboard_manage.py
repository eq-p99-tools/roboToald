"""Tests for the SSO dashboard management routes."""

from __future__ import annotations

import time
import contextlib
from types import SimpleNamespace

import pytest
import sqlalchemy
import sqlalchemy.orm
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from roboToald import config
from roboToald.api import dashboard_manage
from roboToald.api.dashboard import COOKIE_NAME, _make_session_cookie
from roboToald.api.server import app
from roboToald.db import base
from roboToald.db.models import sso

GUILD_ID = 424242
OTHER_GUILD_ID = 515151
CSRF = "test-csrf"


def _session_cookie(guilds: list[int] | None = None, csrf: str = CSRF) -> str:
    return _make_session_cookie(
        {
            "uid": 1001,
            "name": "Dashboard Admin",
            "guilds": guilds or [GUILD_ID],
            "csrf": csrf,
            "iat": int(time.time()),
        }
    )


def _client(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, GUILD_ID, {"enable_sso": True})
    monkeypatch.setitem(config.GUILD_SETTINGS, OTHER_GUILD_ID, {"enable_sso": True})
    return TestClient(app)


@pytest.fixture()
def dashboard_sso_session(monkeypatch):
    engine = sqlalchemy.create_engine(
        "sqlite://",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    base.Base.metadata.create_all(engine)
    SessionLocal = sqlalchemy.orm.sessionmaker(bind=engine, future=True)
    session = SessionLocal()

    @contextlib.contextmanager
    def get_session_patched(autocommit=False):
        yield session

    monkeypatch.setattr(base, "get_session", get_session_patched)
    sso.invalidate_access_key_cache()
    sso.invalidate_revocation_cache()
    yield session
    sso.invalidate_access_key_cache()
    sso.invalidate_revocation_cache()
    session.close()
    engine.dispose()


def test_manage_partial_redirects_when_unauthenticated(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/admin/manage/partials/accounts", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_manage_create_rejects_unauthenticated(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.post(
            "/admin/manage/accounts",
            data={"guild_id": GUILD_ID, "csrf": CSRF, "real_user": "bot", "real_pass": "pw"},
        )
    assert response.status_code == 401


def test_manage_create_rejects_cross_guild(monkeypatch, dashboard_sso_session):
    notifications = []
    monkeypatch.setattr(
        "roboToald.api.dashboard_manage.ws_manager.notify_guild", lambda *a, **k: notifications.append(a)
    )

    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie([GUILD_ID]))
        response = client.post(
            "/admin/manage/accounts",
            data={"guild_id": OTHER_GUILD_ID, "csrf": CSRF, "real_user": "bot", "real_pass": "pw"},
        )

    assert response.status_code == 403
    assert notifications == []
    assert dashboard_sso_session.query(sso.SSOAccount).count() == 0


def test_manage_create_rejects_bad_csrf(monkeypatch, dashboard_sso_session):
    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie())
        response = client.post(
            "/admin/manage/accounts",
            data={"guild_id": GUILD_ID, "csrf": "bad", "real_user": "bot", "real_pass": "pw"},
        )

    assert response.status_code == 403
    assert dashboard_sso_session.query(sso.SSOAccount).count() == 0


def test_manage_account_create_delete_notifies_and_audits(monkeypatch, dashboard_sso_session):
    notifications = []
    audits = []
    monkeypatch.setattr(
        "roboToald.api.dashboard_manage.ws_manager.notify_guild",
        lambda guild_id, immediate=False: notifications.append((guild_id, immediate)),
    )
    monkeypatch.setattr("roboToald.api.dashboard_manage.sso_model.create_audit_log", lambda **kw: audits.append(kw))

    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie())
        create_response = client.post(
            "/admin/manage/accounts",
            data={"guild_id": GUILD_ID, "csrf": CSRF, "real_user": "BotOne", "real_pass": "pw"},
        )
        delete_response = client.request(
            "DELETE",
            "/admin/manage/accounts/botone",
            data={"guild_id": GUILD_ID, "csrf": CSRF},
        )

    assert create_response.status_code == 200
    assert delete_response.status_code == 200
    assert dashboard_sso_session.query(sso.SSOAccount).count() == 0
    assert notifications == [(GUILD_ID, True), (GUILD_ID, True)]
    assert [audit["details"] for audit in audits] == [
        "dashboard:create account botone",
        "dashboard:delete account botone",
    ]


def test_manage_alias_delete_accepts_htmx_query_params(monkeypatch, dashboard_sso_session):
    sso.create_account(GUILD_ID, "botone", "pw")
    sso.create_account_alias(GUILD_ID, "botone", "healbot")
    notifications = []
    audits = []
    monkeypatch.setattr(
        "roboToald.api.dashboard_manage.ws_manager.notify_guild",
        lambda guild_id, immediate=False: notifications.append((guild_id, immediate)),
    )
    monkeypatch.setattr("roboToald.api.dashboard_manage.sso_model.create_audit_log", lambda **kw: audits.append(kw))

    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie())
        response = client.request(
            "DELETE",
            "/admin/manage/aliases/healbot",
            params={"guild_id": GUILD_ID, "csrf": CSRF},
        )

    assert response.status_code == 200
    assert dashboard_sso_session.query(sso.SSOAccountAlias).count() == 0
    assert notifications == [(GUILD_ID, True)]
    assert [audit["details"] for audit in audits] == ["dashboard:delete alias healbot"]


def test_manage_mutation_response_preserves_selected_guild(monkeypatch, dashboard_sso_session):
    sso.create_account_group(GUILD_ID, "raiders", 12345)
    sso.create_account_group(OTHER_GUILD_ID, "outsiders", 67890)
    monkeypatch.setattr("roboToald.api.dashboard_manage.ws_manager.notify_guild", lambda *a, **k: None)
    monkeypatch.setattr("roboToald.api.dashboard_manage.sso_model.create_audit_log", lambda **kw: None)

    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie([GUILD_ID, OTHER_GUILD_ID]))
        response = client.request(
            "PUT",
            "/admin/manage/groups/raiders",
            data={"guild_id": GUILD_ID, "csrf": CSRF, "new_name": "raid-team"},
        )

    assert response.status_code == 200
    assert "raid-team" in response.text
    assert "outsiders" not in response.text
    assert str(OTHER_GUILD_ID) not in response.text


def test_manage_accounts_owner_dropdown_uses_guild_members(monkeypatch, dashboard_sso_session):
    sso.create_account(GUILD_ID, "botone", "pw", owner_discord_user_id=2002)
    member = SimpleNamespace(id=2002, display_name="Cleric Main")
    guild = SimpleNamespace(members=[member], roles=[], name="Test Guild", get_member=lambda user_id: member)
    discord_client = SimpleNamespace(get_guild=lambda guild_id: guild if guild_id == GUILD_ID else None)

    with _client(monkeypatch) as client:
        client.app.state.discord_client = discord_client
        try:
            client.cookies.set(COOKIE_NAME, _session_cookie())
            response = client.get("/admin/manage/partials/accounts")
        finally:
            del client.app.state.discord_client

    assert response.status_code == 200
    assert '<option value="">Admin-only</option>' in response.text
    assert '<option value="__unchanged__">Owner unchanged</option>' in response.text
    assert '<option value="2002" selected>Cleric Main</option>' in response.text


def test_zone_form_values_normalize_to_internal_keys():
    assert dashboard_manage._normalize_zone_key("East Commonlands") == "ecommons"
    assert dashboard_manage._normalize_zone_key("ecommons") == "ecommons"
    assert dashboard_manage._normalize_zone_key("SomeUnmappedZone") == "someunmappedzone"
    assert dashboard_manage._normalize_zone_key("") is None


def test_manage_partials_render_populated_tables(monkeypatch, dashboard_sso_session):
    sso.create_account_group(GUILD_ID, "raiders", 12345)
    sso.create_account(GUILD_ID, "botone", "pw", "raiders")
    sso.tag_account(GUILD_ID, "botone", "clerics")
    sso.create_account_alias(GUILD_ID, "botone", "healbot")
    sso.add_account_character(GUILD_ID, "botone", "Healmain", sso.CharacterClass.Cleric)
    sso.update_account_character(GUILD_ID, "Healmain", bind_location="ecommons", park_location="sebilis")
    sso.add_account_user_share(GUILD_ID, "botone", 2002, created_by_discord_user_id=1001)

    with _client(monkeypatch) as client:
        client.cookies.set(COOKIE_NAME, _session_cookie())
        for partial in ("accounts", "groups", "tags", "aliases", "characters", "shares"):
            response = client.get(f"/admin/manage/partials/{partial}")
            assert response.status_code == 200
            assert "botone" in response.text or partial == "groups"

        form_response = client.get(f"/admin/manage/partials/character_form?guild_id={GUILD_ID}&name=Healmain")

    assert form_response.status_code == 200
    assert "Healmain" in form_response.text
    assert 'value="ecommons" selected' in form_response.text
    assert "East Commonlands" in form_response.text
    assert 'value="sebilis" selected' in form_response.text
    assert "Ruins Of Sebilis" in form_response.text
    assert "Trakanon Idol (Sebilis key)" in form_response.text
    assert 'title="key_seb"' in form_response.text
    assert "Mana Battery - Class Five" in form_response.text
    assert 'title="item_mb5"' in form_response.text
