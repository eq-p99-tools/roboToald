"""Integration-style tests for FastAPI routes in ``roboToald.api.server``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from starlette.testclient import TestClient

from roboToald.api.server import (
    LoginAuthResult,
    _des_encrypt_credentials,
    _get_client_ip,
    _parse_version,
    _validate_client_settings,
    app,
)


@pytest.fixture()
def client():
    with TestClient(app) as tc:
        yield tc


def test_root_without_discord_client(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "warning"
    assert "Discord" in body["message"]


def test_root_with_discord_client(client):
    client.app.state.discord_client = object()
    try:
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
    finally:
        del client.app.state.discord_client


def test_auth_invalid_access_key(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: None)
    monkeypatch.setattr("roboToald.api.server.sso_model.create_audit_log", lambda **kw: None)
    r = client.post("/auth", json={"username": "nobody", "password": "badkey"})
    assert r.status_code == 401


def test_auth_success(client, monkeypatch):
    key = MagicMock()
    key.guild_id = 1
    key.discord_user_id = 99
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a: False)

    def fake_perform(**kwargs):
        return LoginAuthResult(success=True, real_user="realuser", real_pass="realpass")

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fake_perform)
    r = client.post("/auth", json={"username": "tagname", "password": "goodkey"})
    assert r.status_code == 200
    data = r.json()
    assert data["real_user"] == "realuser"
    assert data["real_pass"] == "realpass"


def test_auth_min_client_version_422(client, monkeypatch):
    from roboToald import config

    key = MagicMock()
    key.guild_id = 777
    key.discord_user_id = 1
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a: False)
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        777,
        {"min_client_version": "2.0.0", "client_update_message": "Please update"},
    )
    try:
        r = client.post(
            "/auth",
            json={"username": "u", "password": "k"},
            headers={"X-Client-Version": "1.0.0"},
        )
        assert r.status_code == 422
        assert "update" in r.json()["detail"].lower() or "Please update" in r.json()["detail"]
    finally:
        config.GUILD_SETTINGS.pop(777, None)


def test_websocket_rejects_non_auth_first_message(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    with client.websocket_connect("/ws/accounts") as ws:
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        assert msg.get("type") == "error"
        assert "auth" in msg.get("detail", "").lower() or "Expected" in msg.get("detail", "")


def test_des_encrypt_credentials_block_aligned_and_decryptable():
    enc = _des_encrypt_credentials("u", "p")
    assert isinstance(enc, bytes)
    assert len(enc) % 8 == 0
    cipher = Cipher(TripleDES(b"\x00" * 8), modes.CBC(b"\x00" * 8))
    decryptor = cipher.decryptor()
    dec = decryptor.update(enc) + decryptor.finalize()
    # null-terminated user\0pass\0 padded with zeros
    parts = dec.rstrip(b"\x00").split(b"\x00")
    assert parts[0] == b"u"
    assert parts[1] == b"p"


def test_parse_version_semver_pre_release_ordering():
    assert _parse_version("1.2.3") == (1, 2, 3, 1)
    assert _parse_version("1.2.3-rc1") == (1, 2, 3, 0)
    assert _parse_version("2.0.0") > _parse_version("1.9.9")
    assert _parse_version("1.0.0") > _parse_version("1.0.0-beta")


def test_validate_client_settings_omitted_is_ok():
    assert _validate_client_settings(None, 1) is None


def test_validate_client_settings_block_rustle_exempt_role(monkeypatch):
    from roboToald import config

    gid = 991
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        gid,
        {"block_rustle": True, "block_rustle_exempt_roles": [42]},
    )
    try:
        assert _validate_client_settings({"rustle_present": True}, gid, user_role_ids=[42]) is None
    finally:
        config.GUILD_SETTINGS.pop(gid, None)


def test_get_client_ip_forwarded_for_first_hop():
    req = MagicMock()
    req.headers.get = lambda k: "203.0.113.9, 10.0.0.1" if k.lower() == "x-forwarded-for" else None
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    assert _get_client_ip(req) == "203.0.113.9"


def test_get_client_ip_without_forwarded_uses_client_host():
    req = MagicMock()
    req.headers.get = lambda k: None
    req.client.host = "198.51.100.2"
    assert _get_client_ip(req) == "198.51.100.2"


def test_auth_rate_limited_returns_401(client, monkeypatch):
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: True)
    r = client.post("/auth", json={"username": "u", "password": "k"})
    assert r.status_code == 401


def test_auth_revoked_returns_401(client, monkeypatch):
    key = MagicMock()
    key.guild_id = 1
    key.discord_user_id = 2
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: True)
    monkeypatch.setattr("roboToald.api.server.sso_model.create_audit_log", lambda **kw: None)
    r = client.post("/auth", json={"username": "u", "password": "k"})
    assert r.status_code == 401


def test_auth_tag_empty_returns_410(client, monkeypatch):
    key = MagicMock()
    key.guild_id = 1
    key.discord_user_id = 3
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: False)

    def fail_tag(**kwargs):
        return LoginAuthResult(success=False, error_detail="tag empty", error_status=410)

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", fail_tag)
    r = client.post("/auth", json={"username": "t", "password": "k"})
    assert r.status_code == 410


def test_auth_character_not_found_returns_400(client, monkeypatch):
    key = MagicMock()
    key.guild_id = 1
    key.discord_user_id = 4
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: False)

    def not_found(**kwargs):
        return LoginAuthResult(success=False, error_detail="Character not found", error_status=400)

    monkeypatch.setattr("roboToald.api.server._perform_login_auth", not_found)
    r = client.post("/auth", json={"username": "nope", "password": "k"})
    assert r.status_code == 400


def test_auth_client_settings_rejected_422(client, monkeypatch):
    from roboToald import config

    key = MagicMock()
    key.guild_id = 660
    key.discord_user_id = 1
    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.get_access_key_by_key", lambda k: key)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: False)
    monkeypatch.setitem(config.GUILD_SETTINGS, 660, {"require_log": True})
    try:
        r = client.post(
            "/auth",
            json={"username": "u", "password": "k", "client_settings": {"log_enabled": False}},
        )
        assert r.status_code == 422
        assert "log" in r.json()["detail"].lower()
    finally:
        config.GUILD_SETTINGS.pop(660, None)


def test_auth_success_with_real_sso_and_discord_roles(client, monkeypatch, sso_session):
    from roboToald.db.models import sso as sso

    GUILD_ID = 424242
    ROLE_ID = 91001
    DISCORD_UID = 88001

    sso.create_account_group(GUILD_ID, "team", role_id=ROLE_ID)
    sso.create_account(GUILD_ID, "mainuser", "secretpw", group="team")
    monkeypatch.setattr(sso, "generate_access_key", lambda: "IntegrationTestKey123456789012")
    ak = sso.reset_access_key(GUILD_ID, DISCORD_UID)
    plain_key = ak.access_key

    role = SimpleNamespace(id=ROLE_ID)
    member = MagicMock()
    member.roles = [role]
    member.display_name = "Tester"
    guild = MagicMock()
    guild.get_member.return_value = member
    guild.id = GUILD_ID
    dc = MagicMock()
    dc.get_guild.return_value = guild

    monkeypatch.setattr("roboToald.api.server.sso_model.is_ip_rate_limited", lambda *a, **k: False)
    monkeypatch.setattr("roboToald.api.server.sso_model.is_user_access_revoked", lambda *a, **k: False)

    client.app.state.discord_client = dc
    try:
        r = client.post("/auth", json={"username": "mainuser", "password": plain_key})
        assert r.status_code == 200
        data = r.json()
        assert data["real_user"] == "mainuser"
        assert data["real_pass"] == "secretpw"
    finally:
        del client.app.state.discord_client
