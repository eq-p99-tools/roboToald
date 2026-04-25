"""Tests for WebSocket FTE / mob-death handlers.

These exercise the post-relax ACL: ``character_name`` no longer needs to map
to an account the user owns, but the user must have access to at least one
SSO character in the guild (anti-troll gate). Time-skew rejection and
TOD-dedup behavior are also regression-tested here so they don't silently
break when the ACL block is rewritten.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from roboToald.api import server
from roboToald.api.websocket import ClientConnection


def _make_conn(*, guild_id: int = 1, user_id: int = 100, last_sent_state: dict | None = None) -> ClientConnection:
    return ClientConnection(
        websocket=MagicMock(),
        guild_id=guild_id,
        discord_user_id=user_id,
        last_sent_state=last_sent_state if last_sent_state is not None else {},
    )


# ---- user_has_any_character_access ----------------------------------------


def test_user_has_any_character_access_true_when_account_has_chars():
    conn = _make_conn(last_sent_state={1: {"name": "main", "characters": [{"name": "Toald"}]}})
    assert server.user_has_any_character_access(conn) is True


def test_user_has_any_character_access_false_when_no_accounts():
    conn = _make_conn(last_sent_state={})
    assert server.user_has_any_character_access(conn) is False


def test_user_has_any_character_access_false_when_accounts_have_no_chars():
    conn = _make_conn(
        last_sent_state={
            1: {"name": "alpha", "characters": []},
            2: {"name": "beta"},  # missing characters key entirely
        }
    )
    assert server.user_has_any_character_access(conn) is False


# ---- shared fixtures for handler tests ------------------------------------


@pytest.fixture()
def reset_dedup():
    """Ensure a clean dedup state between handler tests."""
    server._tod_recent.clear()
    yield
    server._tod_recent.clear()


@pytest.fixture()
def capture_tod(monkeypatch):
    """Replace ``_send_to_tod_channel`` with a recorder; returns the recorder list."""
    sent: list[tuple[int, str]] = []

    def _capture(guild_id: int, text: str):
        sent.append((guild_id, text))

    monkeypatch.setattr(server, "_send_to_tod_channel", _capture)
    return sent


@pytest.fixture()
def capture_auto_attendance(monkeypatch):
    """Replace ``_schedule_auto_attendance`` with a recorder; returns the recorder list."""
    fired: list[tuple[int, str]] = []

    def _capture(guild_id: int, mob_name: str):
        fired.append((guild_id, mob_name))

    monkeypatch.setattr(server, "_schedule_auto_attendance", _capture)
    return fired


@pytest.fixture()
def fail_if_db_called(monkeypatch):
    """Hard-fail if the handler reaches ``find_account_by_character``.

    The relaxed handlers must not hit the DB anymore; if a future refactor
    accidentally re-introduces a per-message DB call, this fixture catches it.
    """

    def _explode(*_args, **_kwargs):
        raise AssertionError("find_account_by_character must not be called by relaxed FTE/death handlers")

    import roboToald.db.models.sso as sso_model

    monkeypatch.setattr(sso_model, "find_account_by_character", _explode)


_HAS_CHAR_STATE = {1: {"name": "main", "characters": [{"name": "OtherChar"}]}}


# ---- _ws_handle_fte --------------------------------------------------------


@freeze_time("2026-03-06T11:13:03")
def test_fte_accepted_when_user_has_other_character(reset_dedup, capture_tod, fail_if_db_called):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",  # not in last_sent_state - that is fine now
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_fte(conn, msg))
    assert len(capture_tod) == 1
    guild_id, text = capture_tod[0]
    assert guild_id == 1
    assert "Cekenar" in text
    assert "Toald" in text


@freeze_time("2026-03-06T11:13:03")
def test_fte_rejected_when_user_has_no_character_access(reset_dedup, capture_tod, fail_if_db_called):
    conn = _make_conn(last_sent_state={1: {"name": "shell", "characters": []}})
    msg = {
        "character_name": "LocalOnly",
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_fte(conn, msg))
    assert capture_tod == []


@freeze_time("2026-03-08T11:13:03")
def test_fte_rejected_when_log_time_skewed_over_24h(reset_dedup, capture_tod, fail_if_db_called):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",  # >24h before frozen now
    }
    asyncio.run(server._ws_handle_fte(conn, msg))
    assert capture_tod == []


@freeze_time("2026-03-06T11:13:03")
def test_fte_dedups_repeat_messages(reset_dedup, capture_tod, fail_if_db_called, monkeypatch):
    monkeypatch.setattr(server, "TOD_DEDUP_SECONDS", 60)
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_fte(conn, msg))
    asyncio.run(server._ws_handle_fte(conn, dict(msg)))
    assert len(capture_tod) == 1


@freeze_time("2026-03-06T11:13:03")
@pytest.mark.parametrize(
    "missing",
    ["character_name", "mob", "player", "eq_log_time"],
)
def test_fte_drops_when_required_field_missing(missing, reset_dedup, capture_tod, fail_if_db_called):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    msg[missing] = ""
    asyncio.run(server._ws_handle_fte(conn, msg))
    assert capture_tod == []


# ---- _ws_handle_mob_death --------------------------------------------------


@freeze_time("2026-03-06T11:13:03")
def test_mob_death_accepted_when_user_has_other_character(
    reset_dedup, capture_tod, capture_auto_attendance, fail_if_db_called
):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "King Tormax",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    assert len(capture_tod) == 1
    guild_id, text = capture_tod[0]
    assert guild_id == 1
    assert text.startswith("!tod King Tormax,")
    assert capture_auto_attendance == [(1, "King Tormax")]


@freeze_time("2026-03-06T11:13:03")
def test_mob_death_rejected_when_user_has_no_character_access(
    reset_dedup, capture_tod, capture_auto_attendance, fail_if_db_called
):
    conn = _make_conn(last_sent_state={1: {"name": "shell", "characters": []}})
    msg = {
        "character_name": "LocalOnly",
        "mob": "King Tormax",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    assert capture_tod == []
    assert capture_auto_attendance == []


@freeze_time("2026-03-08T11:13:03")
def test_mob_death_rejected_when_log_time_skewed_over_24h(
    reset_dedup, capture_tod, capture_auto_attendance, fail_if_db_called
):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "King Tormax",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    assert capture_tod == []
    assert capture_auto_attendance == []


@freeze_time("2026-03-06T11:13:03")
def test_mob_death_dedups_repeat_messages(
    reset_dedup, capture_tod, capture_auto_attendance, fail_if_db_called, monkeypatch
):
    monkeypatch.setattr(server, "TOD_DEDUP_SECONDS", 60)
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "King Tormax",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    asyncio.run(server._ws_handle_mob_death(conn, dict(msg)))
    assert len(capture_tod) == 1
    # Auto-attendance only fires for the first (non-deduped) submission.
    assert capture_auto_attendance == [(1, "King Tormax")]


@freeze_time("2026-03-06T11:13:03")
@pytest.mark.parametrize(
    "missing",
    ["character_name", "mob", "eq_log_time"],
)
def test_mob_death_drops_when_required_field_missing(
    missing, reset_dedup, capture_tod, capture_auto_attendance, fail_if_db_called
):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "LocalOnly",
        "mob": "King Tormax",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    msg[missing] = ""
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    assert capture_tod == []
    assert capture_auto_attendance == []
