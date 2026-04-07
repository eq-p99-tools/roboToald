"""Tests for ``ConnectionManager`` helpers in ``roboToald.api.websocket``."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocket, WebSocketState

from roboToald.api.websocket import ClientConnection, ConnectionManager, _brief_exc_info


def test_filter_accessible_no_discord_client():
    mgr = ConnectionManager()
    acc = SimpleNamespace(groups=[SimpleNamespace(role_id=1)])
    assert mgr._filter_accessible(1, 10, [acc]) == []


def test_filter_accessible_no_member():
    mgr = ConnectionManager()
    dc = MagicMock()
    dc.get_guild.return_value.get_member.return_value = None
    mgr.set_discord_client(dc)
    acc = SimpleNamespace(groups=[SimpleNamespace(role_id=1)])
    assert mgr._filter_accessible(1, 10, [acc]) == []


def test_filter_accessible_matches_role():
    mgr = ConnectionManager()
    role = SimpleNamespace(id=100)
    member = MagicMock()
    member.roles = [role]
    guild = MagicMock()
    guild.get_member.return_value = member
    dc = MagicMock()
    dc.get_guild.return_value = guild
    mgr.set_discord_client(dc)

    acc_ok = SimpleNamespace(groups=[SimpleNamespace(role_id=100)])
    acc_no = SimpleNamespace(groups=[SimpleNamespace(role_id=200)])
    out = mgr._filter_accessible(42, 7, [acc_ok, acc_no])
    assert out == [acc_ok]


def test_brief_exc_info_inside_except():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        s = _brief_exc_info()
        assert "RuntimeError" in s
        assert "boom" in s


def test_register_unregister_and_guild_snapshot():
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    conn = ClientConnection(
        websocket=ws,
        guild_id=10,
        discord_user_id=20,
        client_version="1.0",
        client_ip="198.51.100.1",
    )
    mgr.register(conn)
    assert len(mgr._get_connections_for_guild(10)) == 1
    mgr.unregister(ws)
    assert mgr._get_connections_for_guild(10) == []


def test_get_connections_summary_metadata():
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    conn = ClientConnection(
        websocket=ws,
        guild_id=5,
        discord_user_id=7,
        client_version="2.1.0",
        client_ip="198.51.100.3",
    )
    mgr.register(conn)
    g = MagicMock()
    g.name = "TestGuild"
    g.get_member.return_value = SimpleNamespace(display_name="MemberName")
    dc = MagicMock()
    dc.get_guild.return_value = g
    mgr.set_discord_client(dc)
    rows = mgr.get_connections_summary()
    assert len(rows) == 1
    row = rows[0]
    assert row["guild_id"] == 5
    assert row["discord_user_id"] == 7
    assert row["client_version"] == "2.1.0"
    assert row["guild_name"] == "TestGuild"
    assert row["user_name"] == "MemberName"
    assert row["ip_hash"]


@pytest.mark.asyncio
async def test_disconnect_user_async_sends_error_and_unregisters(monkeypatch):
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    conn = ClientConnection(websocket=ws, guild_id=1, discord_user_id=2)
    mgr.register(conn)
    await mgr._disconnect_user_async(1, 2, 4003, "gone")
    ws.send_json.assert_awaited()
    ws.close.assert_awaited()
    assert mgr._get_connections_for_guild(1) == []


@pytest.mark.asyncio
async def test_build_full_state(monkeypatch):
    mgr = ConnectionManager()
    acc = SimpleNamespace(
        id=1,
        real_user="alpha",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
    )
    monkeypatch.setattr("roboToald.api.websocket.sso_model.list_accounts", lambda gid: [acc])
    monkeypatch.setattr("roboToald.api.websocket.sso_model.get_active_characters", lambda gid: {})
    monkeypatch.setattr(mgr, "_filter_accessible", lambda uid, gid, accounts: accounts)
    tree = await mgr.build_full_state(1, 99)
    assert tree["alpha"]["aliases"] == []


@pytest.mark.asyncio
async def test_push_delta_sends_when_tree_changes(monkeypatch):
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock()
    acc = SimpleNamespace(
        id=1,
        real_user="alpha",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
    )
    conn = ClientConnection(
        websocket=ws,
        guild_id=1,
        discord_user_id=9,
        last_sent_state={
            "alpha": {
                "aliases": [],
                "tags": [],
                "characters": {},
                "last_login": None,
                "last_login_by": None,
                "active_character": None,
            }
        },
    )
    monkeypatch.setattr("roboToald.api.websocket.sso_model.list_accounts", lambda gid: [acc])
    monkeypatch.setattr("roboToald.api.websocket.sso_model.get_active_characters", lambda gid: {})
    monkeypatch.setattr(mgr, "_filter_accessible", lambda uid, gid, accounts: accounts)
    acc2 = SimpleNamespace(
        id=1,
        real_user="alpha",
        aliases=[SimpleNamespace(alias="newalias")],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
    )
    await mgr._push_delta(conn, 1, [acc2], {})
    ws.send_json.assert_awaited()
    call = ws.send_json.await_args[0][0]
    assert call["type"] == "delta"
    assert call["changes"]


@pytest.mark.asyncio
async def test_push_delta_skips_when_no_changes(monkeypatch):
    mgr = ConnectionManager()
    ws = MagicMock(spec=WebSocket)
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock()
    blob = {
        "aliases": [],
        "tags": [],
        "characters": {},
        "last_login": None,
        "last_login_by": None,
        "active_character": None,
    }
    acc = SimpleNamespace(
        id=1,
        real_user="alpha",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
    )
    conn = ClientConnection(websocket=ws, guild_id=1, discord_user_id=9, last_sent_state={"alpha": dict(blob)})
    monkeypatch.setattr("roboToald.api.websocket.sso_model.list_accounts", lambda gid: [acc])
    monkeypatch.setattr("roboToald.api.websocket.sso_model.get_active_characters", lambda gid: {})
    monkeypatch.setattr(mgr, "_filter_accessible", lambda uid, gid, accounts: accounts)
    await mgr._push_delta(conn, 1, [acc], {})
    ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_notify_guild_async_no_connections():
    mgr = ConnectionManager()
    # Should not raise when nobody is connected
    await mgr._notify_guild_async(999)


def test_notify_guild_no_loop_logs_warning(caplog):
    import logging

    mgr = ConnectionManager()
    mgr._loop = None
    with caplog.at_level(logging.WARNING, logger="roboToald.api.websocket"):
        mgr.notify_guild(1)
    assert "not available" in caplog.text.lower() or "cannot notify" in caplog.text.lower()


@pytest.mark.asyncio
async def test_notify_guild_entry_immediate_pushes_delta(monkeypatch):
    mgr = ConnectionManager()
    loop = asyncio.get_running_loop()
    mgr.set_event_loop(loop)
    ws = MagicMock(spec=WebSocket)
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock()
    acc = SimpleNamespace(
        id=1,
        real_user="a",
        aliases=[],
        tags=[],
        characters=[],
        last_login=None,
        last_login_by=None,
    )
    conn = ClientConnection(websocket=ws, guild_id=7, discord_user_id=8, last_sent_state={})
    mgr.register(conn)
    monkeypatch.setattr("roboToald.api.websocket.sso_model.list_accounts", lambda gid: [acc])
    monkeypatch.setattr("roboToald.api.websocket.sso_model.get_active_characters", lambda gid: {})
    monkeypatch.setattr(mgr, "_filter_accessible", lambda uid, gid, accounts: accounts)
    await mgr._notify_guild_entry(7, immediate=True)
    ws.send_json.assert_awaited()
    assert ws.send_json.await_args[0][0]["type"] == "delta"
