"""WebSocket ``/ws/accounts`` auth, ``login_auth``, and message handlers."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from roboToald.api.server import LoginAuthResult, _des_encrypt_credentials, app


def _make_key(guild_id: int = 1, discord_user_id: int = 99):
    key = MagicMock()
    key.guild_id = guild_id
    key.discord_user_id = discord_user_id
    return key


def _patch_ws_auth_ok(monkeypatch, guild_id: int = 1, discord_user_id: int = 99):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: False)
    k = _make_key(guild_id, discord_user_id)
    monkeypatch.setattr(
        "roboToald.api.server.sso_model.get_access_key_by_key", lambda access: k if access == "good" else None
    )

    async def fake_build_full_state(gid: int, uid: int):
        return {
            "acct": {
                "aliases": [],
                "tags": [],
                "characters": {},
                "last_login": None,
                "last_login_by": None,
                "active_character": None,
            }
        }

    monkeypatch.setattr("roboToald.api.server.ws_manager.build_full_state", fake_build_full_state)
    monkeypatch.setattr("roboToald.api.server.sso_model.create_audit_log", lambda **kw: None)


@pytest.fixture()
def client():
    with TestClient(app) as tc:
        yield tc


def test_ws_auth_happy_path_full_state(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        msg = ws.receive_json()
        assert msg["type"] == "full_state"
        assert msg["account_tree"] == {
            "acct": {
                "aliases": [],
                "tags": [],
                "characters": {},
                "last_login": None,
                "last_login_by": None,
                "active_character": None,
            }
        }
        assert msg["count"] == 1
        assert "dynamic_tag_zones" in msg
        assert "dynamic_tag_classes" in msg


def test_ws_auth_invalid_access_key(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.create_audit_log", lambda **kw: None)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "bad", "client_version": "2.0.0"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "access" in msg["detail"].lower() or "invalid" in msg["detail"].lower()


def test_ws_auth_rate_limited(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: True)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_ws_auth_revoked(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: True)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "revoked" in msg["detail"].lower()


def test_ws_auth_min_client_version_rejected(client, monkeypatch):
    from roboToald import config

    _patch_ws_auth_ok(monkeypatch, guild_id=888)
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        888,
        {"min_client_version": "2.0.0", "client_update_message": "Please update your client"},
    )
    try:
        with client.websocket_connect("/ws/accounts") as ws:
            ws.send_json({"type": "auth", "access_key": "good", "client_version": "1.0.0"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "update" in msg["detail"].lower() or "Please update" in msg["detail"]
    finally:
        config.GUILD_SETTINGS.pop(888, None)


def test_ws_auth_client_settings_rejected(client, monkeypatch):
    from roboToald import config

    _patch_ws_auth_ok(monkeypatch, guild_id=889)
    monkeypatch.setitem(config.GUILD_SETTINGS, 889, {"require_log": True})
    try:
        with client.websocket_connect("/ws/accounts") as ws:
            ws.send_json(
                {
                    "type": "auth",
                    "access_key": "good",
                    "client_version": "2.0.0",
                    "client_settings": {"log_enabled": False},
                }
            )
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "log" in msg["detail"].lower()
    finally:
        config.GUILD_SETTINGS.pop(889, None)


def test_ws_auth_bad_json_first_message(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_text("{not json")
        msg = ws.receive_json()
        assert msg["type"] == "error"


def test_ws_auth_missing_access_key(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "client_version": "2.0.0"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "auth" in msg["detail"].lower()


def test_ws_ping_pong(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "ping"})
        pong = ws.receive_json()
        assert pong == {"type": "pong"}


def test_ws_login_auth_success_encrypted_credentials(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)

    def fake_perform(**kwargs):
        return LoginAuthResult(success=True, real_user="realu", real_pass="realp")

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fake_perform)

    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "login_auth", "request_id": "req-1", "username": "tagname"})
        resp = ws.receive_json()
        assert resp["type"] == "login_auth_response"
        assert resp["request_id"] == "req-1"
        assert resp["real_user"] == "realu"
        raw = base64.b64decode(resp["encrypted_credentials"])
        assert raw == _des_encrypt_credentials("realu", "realp")


def test_ws_login_auth_missing_fields(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "login_auth", "request_id": "r1"})
        resp = ws.receive_json()
        assert resp["type"] == "login_auth_response"
        assert resp["status"] == 400
        assert "Missing" in resp.get("error", "")


def test_ws_login_auth_account_not_found(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)

    def fake_perform(**kwargs):
        return LoginAuthResult(success=False, error_detail="Character not found", error_status=400)

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fake_perform)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "login_auth", "request_id": "r2", "username": "nope"})
        resp = ws.receive_json()
        assert resp["type"] == "login_auth_response"
        assert resp["status"] == 400
        assert resp["error"] == "Character not found"


def test_ws_login_auth_rbac_denied(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)

    def fake_perform(**kwargs):
        return LoginAuthResult(success=False, error_detail="Authentication failed", error_status=401)

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fake_perform)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "login_auth", "request_id": "r3", "username": "x"})
        resp = ws.receive_json()
        assert resp["status"] == 401


def test_ws_login_auth_tag_empty(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)

    def fake_perform(**kwargs):
        return LoginAuthResult(
            success=False,
            error_detail="Tag is empty (possibly temporarily, due to inactivity requirements)",
            error_status=410,
        )

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fake_perform)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "login_auth", "request_id": "r4", "username": "tag"})
        resp = ws.receive_json()
        assert resp["status"] == 410


def test_ws_heartbeat_updates_session(client, monkeypatch):
    from types import SimpleNamespace

    _patch_ws_auth_ok(monkeypatch)
    calls: dict[str, list] = {"update_last_login": [], "record": [], "expire": [], "notify": []}

    acc = SimpleNamespace(id=7, real_user="u")

    def fake_find_char(gid, name):
        assert gid == 1
        assert name == "Hero"
        return acc

    monkeypatch.setattr("roboToald.api.server.sso_model.find_account_by_character", fake_find_char)
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])

    def ul(aid, login_by=None):
        calls["update_last_login"].append((aid, login_by))

    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login", ul)

    def rec(gid, aid, cname, duid):
        calls["record"].append((gid, aid, cname, duid))

    monkeypatch.setattr("roboToald.api.server.sso_model.record_heartbeat_session", rec)

    def exp(gid, duid, keep):
        calls["expire"].append((gid, duid, keep))

    monkeypatch.setattr("roboToald.api.server.sso_model.expire_other_sessions", exp)

    async def notify(gid, immediate=False):
        calls["notify"].append((gid, immediate))

    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild_async", notify)

    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json({"type": "heartbeat", "character_name": "Hero"})
        # Allow async handler to run
        import time

        time.sleep(0.05)
    assert calls["update_last_login"] == [(7, None)]
    assert calls["record"] == [(1, 7, "Hero", 99)]
    assert calls["expire"] == [(1, 99, 7)]
    assert calls["notify"] == [(1, False)]


def test_ws_update_location_updates_character(client, monkeypatch):
    from types import SimpleNamespace

    _patch_ws_auth_ok(monkeypatch)
    acc = SimpleNamespace(id=3, real_user="u")
    monkeypatch.setattr(
        "roboToald.api.server.sso_model.find_account_by_character", lambda g, n: acc if n == "Zed" else None
    )
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login", lambda *a, **k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.record_heartbeat_session", lambda *a, **k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.expire_other_sessions", lambda *a, **k: None)

    uac_calls: list[dict] = []

    def fake_uac(**kw):
        uac_calls.append(kw)
        return True

    monkeypatch.setattr("roboToald.api.server.sso_model.update_account_character", fake_uac)
    monkeypatch.setattr("roboToald.api.server.sso_model.mark_key_from_park_zone", lambda *a, **k: False)

    async def notify(gid, immediate=False):
        pass

    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild_async", notify)

    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json(
            {
                "type": "update_location",
                "character_name": "Zed",
                "bind_location": "PoK",
                "park_location": "veeshan",
                "level": 60,
                "items": {"seb": True, "vp": None, "st": False},
            }
        )
        import time

        time.sleep(0.05)
    assert len(uac_calls) == 1
    assert uac_calls[0]["guild_id"] == 1
    assert uac_calls[0]["name"] == "Zed"
    assert uac_calls[0]["bind_location"] == "PoK"
    assert uac_calls[0]["park_location"] == "veeshan"
    assert uac_calls[0]["level"] == 60
    assert uac_calls[0]["key_seb"] is True
    assert uac_calls[0]["key_vp"] is None
    assert uac_calls[0]["key_st"] is False


def test_ws_update_location_items_overrides_keys(client, monkeypatch):
    from types import SimpleNamespace

    _patch_ws_auth_ok(monkeypatch)
    acc = SimpleNamespace(id=3, real_user="u")
    monkeypatch.setattr(
        "roboToald.api.server.sso_model.find_account_by_character", lambda g, n: acc if n == "Zed" else None
    )
    monkeypatch.setattr("roboToald.api.server.user_has_access_to_accounts", lambda *a, **k: [acc])
    monkeypatch.setattr("roboToald.api.server.sso_model.update_last_login", lambda *a, **k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.record_heartbeat_session", lambda *a, **k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.expire_other_sessions", lambda *a, **k: None)

    uac_calls: list[dict] = []

    def fake_uac(**kw):
        uac_calls.append(kw)
        return True

    monkeypatch.setattr("roboToald.api.server.sso_model.update_account_character", fake_uac)
    monkeypatch.setattr("roboToald.api.server.sso_model.mark_key_from_park_zone", lambda *a, **k: False)

    async def notify(gid, immediate=False):
        pass

    monkeypatch.setattr("roboToald.api.server.ws_manager.notify_guild_async", notify)

    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_json(
            {
                "type": "update_location",
                "character_name": "Zed",
                "keys": {"seb": False, "vp": True},
                "items": {"seb": True, "void": True},
            }
        )
        import time

        time.sleep(0.05)
    assert len(uac_calls) == 1
    assert uac_calls[0]["key_seb"] is True
    assert uac_calls[0]["key_vp"] is True
    assert uac_calls[0]["item_void"] is True


def test_ws_json_decode_error_in_message_loop_ignored(client, monkeypatch):
    _patch_ws_auth_ok(monkeypatch)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "auth", "access_key": "good", "client_version": "2.0.0"})
        assert ws.receive_json()["type"] == "full_state"
        ws.send_text("not-json")
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
