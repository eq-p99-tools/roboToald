"""Unit tests for ``_perform_login_auth`` in ``roboToald.api.server``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from roboToald.api.server import LoginAuthResult, _perform_login_auth
from roboToald.db.models import sso as sso_model


GUILD_ID = 101
DISCORD_UID = 555
CLIENT_IP = "198.51.100.1"


def _account(
    *,
    aid: int = 1,
    real_user: str = "realuser",
    characters: tuple | None = None,
    aliases: tuple | None = None,
):
    chars = [SimpleNamespace(name=n) for n in (characters or ())]
    als = [SimpleNamespace(alias=a) for a in (aliases or ())]
    return SimpleNamespace(id=aid, real_user=real_user, characters=chars, aliases=als)


def test_perform_login_auth_account_not_found(monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: None)
    r = _perform_login_auth(
        "nobody",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        "1.0.0",
        None,
        auth_source="http",
    )
    assert r == LoginAuthResult(success=False, error_detail="Character not found", error_status=400)


def test_perform_login_auth_tag_temporarily_empty(monkeypatch):
    def raise_empty(*a, **k):
        raise sso_model.SSOTagTemporarilyEmptyError()

    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", raise_empty)
    r = _perform_login_auth(
        "tag",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        None,
        None,
        auth_source="http",
    )
    assert r.success is False
    assert r.error_status == 410
    assert "Tag is empty" in (r.error_detail or "")


def test_perform_login_auth_rbac_denied(monkeypatch):
    acc = _account()
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: acc)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [])
    audit: list[dict] = []
    monkeypatch.setattr("roboToald.api.server.sso_model.create_audit_log", lambda **kw: audit.append(kw))
    r = _perform_login_auth(
        "realuser",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        "2.0.0",
        None,
        auth_source="http",
    )
    assert r.success is False
    assert r.error_status == 401
    assert audit and audit[0]["details"] == "Access denied"


def test_perform_login_auth_success_via_account_name(monkeypatch):
    # Server compares ``username.lower()`` to ``account.real_user`` (see ``server.py``).
    acc = _account(real_user="myaccount")
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: acc)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    log_calls: list[dict] = []
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login_and_log", lambda **kw: log_calls.append(kw))
    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild", lambda *a, **k: None)
    acc.real_pass = "secretpw"
    r = _perform_login_auth(
        "MyAccount",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        "2.0.0",
        None,
        auth_source="http",
    )
    assert r.success is True
    assert r.real_user == "myaccount"
    assert r.real_pass == "secretpw"
    assert log_calls[0]["details"] == "Authentication successful (account name)"


def test_perform_login_auth_success_via_character(monkeypatch):
    acc = _account(real_user="owner", characters=("RaidMain",))
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: acc)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    log_calls: list[dict] = []
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login_and_log", lambda **kw: log_calls.append(kw))
    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild", lambda *a, **k: None)
    acc.real_pass = "pw"
    r = _perform_login_auth(
        "RaidMain",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        None,
        None,
        auth_source="websocket",
    )
    assert r.success is True
    assert "character" in log_calls[0]["details"]


def test_perform_login_auth_success_via_alias(monkeypatch):
    acc = _account(real_user="owner", aliases=("bob",))
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: acc)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    log_calls: list[dict] = []
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login_and_log", lambda **kw: log_calls.append(kw))
    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild", lambda *a, **k: None)
    acc.real_pass = "pw"
    r = _perform_login_auth(
        "bob",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        "1.1.1",
        MagicMock(),
        auth_source="http",
    )
    assert r.success is True
    assert "alias" in log_calls[0]["details"]


def test_perform_login_auth_success_via_tag(monkeypatch):
    acc = _account(real_user="owner", characters=("Other",), aliases=("a",))
    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_username", lambda *a, **k: acc)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    log_calls: list[dict] = []
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login_and_log", lambda **kw: log_calls.append(kw))
    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild", lambda *a, **k: None)
    acc.real_pass = "pw"
    r = _perform_login_auth(
        "sharedtag",
        GUILD_ID,
        DISCORD_UID,
        CLIENT_IP,
        None,
        None,
        auth_source="http",
    )
    assert r.success is True
    assert "tag" in log_calls[0]["details"]
