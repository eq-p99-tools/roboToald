"""Tests for the WebSocket ``faction_hits`` handler and faction storage."""

from __future__ import annotations

import asyncio
import datetime
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from roboToald.api import server
from roboToald.api.websocket import ClientConnection
from roboToald.db.models import sso

GUILD_ID = 1
USER_ID = 100
LOG_TIME = "Sat Nov 21 09:55:01 2026"
NOW = "2026-11-21T09:55:01"


def _make_conn() -> ClientConnection:
    return ClientConnection(websocket=MagicMock(), guild_id=GUILD_ID, discord_user_id=USER_ID)


def _msg(*hits: tuple[str, str], character_name: str = "Hero", eq_log_time: str = LOG_TIME) -> dict:
    return {
        "type": "faction_hits",
        "character_name": character_name,
        "eq_log_time": eq_log_time,
        "hits": [{"faction": f, "direction": d} for f, d in hits],
    }


@pytest.fixture()
def account(sso_session, monkeypatch):
    acc = sso.create_account(GUILD_ID, "heroacct", "pw")
    sso.add_account_character(GUILD_ID, "heroacct", "Hero", sso.CharacterClass.Warrior)
    monkeypatch.setattr(server, "user_has_access_to_accounts", lambda *_a, **_k: [acc])
    monkeypatch.setattr(server, "_resolve_display_name", lambda *_a, **_k: "Player One")
    monkeypatch.setattr(server, "_faction_last_prune", None)

    # The in-memory SQLite database is per thread, so run handler DB work inline.
    async def _inline(fn, /, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)
    return acc


def _states(session) -> dict[str, sso.SSOCharacterFaction]:
    return {row.faction: row for row in session.query(sso.SSOCharacterFaction).all()}


def _events(session) -> list[sso.SSOFactionEvent]:
    return session.query(sso.SSOFactionEvent).order_by(sso.SSOFactionEvent.id).all()


@freeze_time(NOW)
def test_hits_update_state_and_event_log(sso_session, account):
    conn = _make_conn()
    asyncio.run(
        server._ws_handle_faction_hits(
            conn,
            _msg(("Coldain", "better"), ("Kromrif", "worse"), ("Coldain", "better"), ("Claws of Veeshan", "max")),
        )
    )

    states = _states(sso_session)
    assert set(states) == {"Coldain", "Kromrif", "Claws of Veeshan"}
    assert (states["Coldain"].hits_better, states["Coldain"].hits_worse) == (2, 0)
    assert (states["Kromrif"].hits_better, states["Kromrif"].hits_worse) == (0, 1)
    assert states["Claws of Veeshan"].cap == "max"
    assert states["Claws of Veeshan"].hits_better == 0
    assert states["Coldain"].account_id == account.id

    events = _events(sso_session)
    assert [(e.faction, e.direction) for e in events] == [
        ("Coldain", "better"),
        ("Kromrif", "worse"),
        ("Coldain", "better"),
        ("Claws of Veeshan", "max"),
    ]
    first = events[0]
    assert first.account_id == account.id
    assert first.character_name == "Hero"
    assert first.discord_user_id == USER_ID
    assert first.login_by == "Player One"
    assert first.eq_log_time == LOG_TIME


@freeze_time(NOW)
def test_successful_hit_clears_cap(sso_session, account):
    conn = _make_conn()
    asyncio.run(server._ws_handle_faction_hits(conn, _msg(("Coldain", "max"))))
    asyncio.run(server._ws_handle_faction_hits(conn, _msg(("Coldain", "worse"))))
    state = _states(sso_session)["Coldain"]
    assert state.cap is None
    assert state.cap_at is not None
    assert state.last_direction == "worse"
    assert state.hits_worse == 1


@freeze_time(NOW)
def test_unknown_character_is_ignored(sso_session, account):
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), _msg(("Coldain", "better"), character_name="Nobody")))
    assert _events(sso_session) == []


@freeze_time(NOW)
def test_inaccessible_character_is_ignored(sso_session, account, monkeypatch):
    monkeypatch.setattr(server, "user_has_access_to_accounts", lambda *_a, **_k: [])
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), _msg(("Coldain", "better"))))
    assert _events(sso_session) == []
    assert _states(sso_session) == {}


@freeze_time("2026-11-23T09:55:01")
def test_skewed_log_time_is_rejected(sso_session, account):
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), _msg(("Coldain", "better"))))
    assert _events(sso_session) == []


@freeze_time(NOW)
def test_malformed_hits_are_skipped(sso_session, account):
    msg = _msg(("Coldain", "better"))
    msg["hits"] += [
        {"faction": "Kromrif", "direction": "sideways"},
        {"faction": "", "direction": "better"},
        {"faction": "x" * 256, "direction": "better"},
        {"direction": "worse"},
        "Coldain",
    ]
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), msg))
    assert [(e.faction, e.direction) for e in _events(sso_session)] == [("Coldain", "better")]


@pytest.mark.parametrize("hits", [None, [], "Coldain", [{"faction": "Coldain", "direction": "up"}]])
@freeze_time(NOW)
def test_message_without_valid_hits_is_dropped(sso_session, account, hits):
    msg = _msg()
    msg["hits"] = hits
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), msg))
    assert _events(sso_session) == []


@freeze_time(NOW)
def test_hits_per_message_are_capped(sso_session, account):
    msg = _msg(*[("Coldain", "better")] * (server.FACTION_HITS_MAX_PER_MESSAGE + 10))
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), msg))
    assert len(_events(sso_session)) == server.FACTION_HITS_MAX_PER_MESSAGE


def test_rate_limit_is_a_sliding_window_per_connection():
    conn = _make_conn()
    for i in range(server.FACTION_HITS_RATE_MAX_MESSAGES):
        assert server._faction_hits_rate_limited(conn, now=100.0 + i * 0.1) is False
    assert server._faction_hits_rate_limited(conn, now=110.0) is True
    assert server._faction_hits_rate_limited(_make_conn(), now=110.0) is False
    assert server._faction_hits_rate_limited(conn, now=100.0 + server.FACTION_HITS_RATE_WINDOW_SECONDS) is False


@freeze_time(NOW)
def test_rate_limited_messages_are_not_stored(sso_session, account, monkeypatch):
    monkeypatch.setattr(server, "FACTION_HITS_RATE_MAX_MESSAGES", 2)
    conn = _make_conn()
    for _ in range(3):
        asyncio.run(server._ws_handle_faction_hits(conn, _msg(("Coldain", "better"))))
    assert len(_events(sso_session)) == 2


def test_purge_old_faction_events_keeps_state(sso_session, account):
    now = datetime.datetime(2026, 11, 21, 9, 55, 1)
    sso.record_faction_hits(
        GUILD_ID,
        account.id,
        "Hero",
        USER_ID,
        None,
        LOG_TIME,
        [("Coldain", "better")],
        now=now - datetime.timedelta(days=91),
    )
    sso.record_faction_hits(GUILD_ID, account.id, "Hero", USER_ID, None, LOG_TIME, [("Coldain", "better")], now=now)

    assert sso.purge_old_faction_events(retention_days=90, now=now) == 1
    assert [e.received_at for e in _events(sso_session)] == [now]
    assert _states(sso_session)["Coldain"].hits_better == 2


@freeze_time(NOW)
def test_handler_prunes_old_events(sso_session, account):
    old = datetime.datetime(2026, 11, 21, 9, 55, 1) - datetime.timedelta(days=200)
    sso.record_faction_hits(GUILD_ID, account.id, "Hero", USER_ID, None, LOG_TIME, [("Kromrif", "worse")], now=old)
    asyncio.run(server._ws_handle_faction_hits(_make_conn(), _msg(("Coldain", "better"))))
    assert [e.faction for e in _events(sso_session)] == ["Coldain"]
