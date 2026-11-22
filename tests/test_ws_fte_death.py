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


# ---- relayed text safety ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Lord   Nagafen ", "Lord Nagafen"),
        ("Vox\n!tod Trakanon, 1/1 00:00:00", "Vox !tod Trakanon, 1/1 00:00:00"),
        ("Zlandi\u200b\u0007", "Zlandi"),
        ("x" * server.LOG_NAME_MAX_LEN, "x" * server.LOG_NAME_MAX_LEN),
        ("x" * (server.LOG_NAME_MAX_LEN + 1), ""),
        (123, ""),
        (None, ""),
    ],
)
def test_clean_log_name(raw, expected):
    assert server._clean_log_name(raw) == expected


@freeze_time("2026-03-06T11:13:03")
def test_mob_death_posts_cleaned_single_line_text(reset_dedup, capture_tod, capture_auto_attendance):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "Toald",
        "mob": "Vox\n@everyone",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    asyncio.run(server._ws_handle_mob_death(conn, msg))
    assert len(capture_tod) == 1
    _guild, text = capture_tod[0]
    assert "\n" not in text
    assert text.startswith("!tod Vox @everyone, ")
    assert capture_auto_attendance == [(1, "Vox @everyone")]


@freeze_time("2026-03-06T11:13:03")
@pytest.mark.parametrize("field", ["mob", "player", "character_name"])
def test_fte_with_oversized_or_non_string_name_is_dropped(reset_dedup, capture_tod, field):
    conn = _make_conn(last_sent_state=_HAS_CHAR_STATE)
    msg = {
        "character_name": "Toald",
        "mob": "Cekenar",
        "player": "Toald",
        "eq_log_time": "Fri Mar 06 11:13:03 2026",
    }
    for bad in ("x" * (server.LOG_NAME_MAX_LEN + 1), 42):
        asyncio.run(server._ws_handle_fte(conn, {**msg, field: bad}))
    assert capture_tod == []


def test_tod_channel_send_disables_all_mentions(monkeypatch):
    channel = MagicMock()
    guild = MagicMock()
    guild.get_channel.return_value = channel
    discord_client = MagicMock()
    discord_client.get_guild.return_value = guild
    monkeypatch.setattr(server.ws_manager, "_discord_client", discord_client)
    monkeypatch.setattr(server.config, "get_tod_channel_id", lambda _gid: 555)
    monkeypatch.setattr(server.asyncio, "run_coroutine_threadsafe", lambda coro, loop: coro)

    server._send_to_tod_channel(1, "!tod @everyone, 3/6 11:13:03")

    _args, kwargs = channel.send.call_args
    mentions = kwargs["allowed_mentions"]
    assert (mentions.everyone, mentions.users, mentions.roles, mentions.replied_user) == (False, False, False, False)
