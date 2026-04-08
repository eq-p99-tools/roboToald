"""Tests for `/sso reconcile` helpers and `_get_reconcile_embed_response`."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from roboToald.db.raid_models.raid import Event
from roboToald.db.raid_models.target import Target
from roboToald.discord_client.commands.cmd_sso import (
    SSOCommands,
    _infer_tod_naive_local_from_first_kill_message,
    _message_is_dollar_kill_or_nokill,
)

GUILD_ID = 910_001
CHANNEL_ID = 999_888


@pytest.fixture()
def patch_cmd_sso_raid_session(raid_session, monkeypatch):
    @contextlib.contextmanager
    def fake(guild_id: int):
        yield raid_session

    monkeypatch.setattr("roboToald.discord_client.commands.cmd_sso.get_raid_session", fake)


def _raid_config(monkeypatch, *, auto_attendance: bool, guild_ids: list[int] | None = None):
    gids = guild_ids if guild_ids is not None else [GUILD_ID]
    monkeypatch.setattr(
        "roboToald.discord_client.commands.cmd_sso.config.raid_guild_ids",
        lambda: gids,
    )
    monkeypatch.setattr(
        "roboToald.discord_client.commands.cmd_sso.config.get_raid_setting",
        lambda gid, key: auto_attendance if key == "auto_attendance" else False,
    )


def _channel_mock():
    ch = MagicMock()
    ch.id = CHANNEL_ID
    ch.guild = MagicMock()
    ch.guild.id = GUILD_ID
    return ch


# ---------------------------------------------------------------------------
# $kill / $nokill detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("$kill", True),
        ("$Kill extra", True),
        ("$nokill", True),
        ("$NOKILL", True),
        ("", False),
        ("kill", False),
        ("$k", False),
        (None, False),
    ],
)
def test_message_is_dollar_kill_or_nokill(content, expected):
    assert _message_is_dollar_kill_or_nokill(content) is expected


# ---------------------------------------------------------------------------
# Infer ToD from channel history
# ---------------------------------------------------------------------------


class _MockAsyncHistory:
    """Async iterable matching ``async for m in channel.history(...)``."""

    def __init__(self, messages: list):
        self._messages = list(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


@pytest.mark.asyncio
async def test_infer_tod_returns_first_kill_after_event_start():
    event_start_naive_utc = datetime(2025, 6, 15, 18, 0, 0)
    evt = MagicMock()
    evt.created_at = event_start_naive_utc

    kill_ts = datetime(2025, 6, 15, 19, 5, 0, tzinfo=timezone.utc)
    msg_kill = MagicMock()
    msg_kill.content = "$kill"
    msg_kill.created_at = kill_ts

    msg_skip = MagicMock()
    msg_skip.content = "hello"
    msg_skip.created_at = datetime(2025, 6, 15, 18, 30, 0, tzinfo=timezone.utc)

    ch = MagicMock()
    ch.history = MagicMock(return_value=_MockAsyncHistory([msg_skip, msg_kill]))

    local_tz = kill_ts.astimezone().tzinfo
    out = await _infer_tod_naive_local_from_first_kill_message(ch, evt, local_tz)

    assert out == kill_ts.astimezone(local_tz).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_infer_tod_returns_none_when_no_kill_messages():
    evt = MagicMock()
    evt.created_at = datetime(2025, 6, 15, 18, 0, 0)

    ch = MagicMock()
    ch.history = MagicMock(return_value=_MockAsyncHistory([]))

    out = await _infer_tod_naive_local_from_first_kill_message(ch, evt, timezone.utc)
    assert out is None


# ---------------------------------------------------------------------------
# _get_reconcile_embed_response (raid guild)
# ---------------------------------------------------------------------------


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_get_reconcile_open_event_returns_embeds_and_proposal(
    raid_session,
    monkeypatch,
    patch_cmd_sso_raid_session,
):
    _raid_config(monkeypatch, auto_attendance=True)

    now = datetime.now()
    local_tz = now.astimezone().tzinfo
    event_start_local = now - timedelta(minutes=30)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name="Dragon")
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(CHANNEL_ID),
            created_at=evt_created_at,
            killed=None,
            tod_at=None,
        )
    )
    raid_session.commit()

    def fake_qualifying(guild_id, event_start, end_time, presence_percent=50.0):
        return ([(100, 600.0, "CharA")], 120.0)

    async def fake_proposal_lines(guild_id, qualifying, guild):
        return ["+CharA (10m) [Tester]"]

    view_mock = MagicMock(name="proposal_view")
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.qualifying_players_for_event_window",
        fake_qualifying,
    )
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.format_qualifying_proposal_lines",
        fake_proposal_lines,
    )
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance._make_proposal_view",
        lambda gid: view_mock,
    )

    channel = _channel_mock()
    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None, attendance_percent=50.0)

    assert embeds is not None and len(embeds) >= 1
    assert embeds[0].title == "SSO Reconciliation (auto-attendance)"
    assert proposal is not None
    content, view = proposal
    assert "```diff" in content
    assert "+CharA (10m) [Tester]" in content
    assert "Suggested attendance (reconcile)" in content
    assert view is view_mock


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_get_reconcile_open_event_empty_proposal_plain_text_not_diff(
    raid_session,
    monkeypatch,
    patch_cmd_sso_raid_session,
):
    """No EQDKP +lines: follow-up is plain text, not an empty ```diff``` block."""
    _raid_config(monkeypatch, auto_attendance=True)

    now = datetime.now()
    local_tz = now.astimezone().tzinfo
    event_start_local = now - timedelta(minutes=30)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name="Dragon")
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(CHANNEL_ID),
            created_at=evt_created_at,
            killed=None,
            tod_at=None,
        )
    )
    raid_session.commit()

    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.qualifying_players_for_event_window",
        lambda *_a, **_k: ([(100, 600.0, "CharA")], 120.0),
    )
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.format_qualifying_proposal_lines",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance._make_proposal_view",
        lambda gid: MagicMock(),
    )

    channel = _channel_mock()
    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None, attendance_percent=50.0)

    assert proposal is not None
    content, _view = proposal
    assert "```diff" not in content
    assert "empty" in content.lower()


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_get_reconcile_closed_event_with_tod_returns_embeds_and_proposal(
    raid_session,
    monkeypatch,
    patch_cmd_sso_raid_session,
):
    _raid_config(monkeypatch, auto_attendance=True)

    now = datetime.now()
    local_tz = now.astimezone().tzinfo
    event_start_local = now - timedelta(hours=2)
    tod_local = now - timedelta(minutes=5)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name="Dragon")
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(CHANNEL_ID),
            created_at=evt_created_at,
            killed=True,
            tod_at=tod_local,
        )
    )
    raid_session.commit()

    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.qualifying_players_for_event_window",
        lambda *_a, **_k: ([(200, 300.0, "Zed")], 60.0),
    )

    async def fake_proposal_lines(guild_id, qualifying, guild):
        return ["+ Zed test (5m)"]

    view_mock = MagicMock(name="proposal_view")
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.format_qualifying_proposal_lines",
        fake_proposal_lines,
    )
    monkeypatch.setattr(
        "roboToald.raid.auto_attendance._make_proposal_view",
        lambda gid: view_mock,
    )

    channel = _channel_mock()
    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None, attendance_percent=50.0)

    assert embeds is not None and embeds[0].title == "SSO Reconciliation (auto-attendance)"
    fields = {f.name: f.value for f in embeds[0].fields}
    assert "Window" in fields
    assert "event start → ToD" in fields["Window"]
    assert proposal is not None
    content, view = proposal
    assert "```diff" in content
    assert "+ Zed test" in content
    assert view is view_mock


@pytest.mark.asyncio
async def test_get_reconcile_no_db_event_returns_nothing(
    raid_session,
    monkeypatch,
    patch_cmd_sso_raid_session,
):
    _raid_config(monkeypatch, auto_attendance=True)

    channel = _channel_mock()
    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None)

    assert embeds is None
    assert proposal is None


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_get_reconcile_legacy_when_no_tod_and_infer_fails(
    raid_session,
    monkeypatch,
    patch_cmd_sso_raid_session,
):
    _raid_config(monkeypatch, auto_attendance=True)

    now = datetime.now()
    local_tz = now.astimezone().tzinfo
    event_start_local = now - timedelta(hours=1)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name="Dragon")
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(CHANNEL_ID),
            created_at=evt_created_at,
            killed=True,
            tod_at=None,
        )
    )
    raid_session.commit()

    async def no_infer(*_a, **_k):
        return None

    monkeypatch.setattr(
        "roboToald.discord_client.commands.cmd_sso._infer_tod_naive_local_from_first_kill_message",
        no_infer,
    )
    monkeypatch.setattr(
        "roboToald.discord_client.commands.cmd_sso.sso_model.get_sessions_in_range",
        lambda *_a, **_k: [],
    )

    channel = _channel_mock()
    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None)

    assert proposal is None
    assert embeds is not None and embeds[0].title == "SSO Reconciliation"
    notes = [f.value for f in embeds[0].fields if f.name == "Note"]
    assert notes and "No ToD on file" in notes[0]


@pytest.mark.asyncio
async def test_get_reconcile_not_raid_guild_no_status_embed_returns_none(monkeypatch):
    """Non-raid guild falls back to Raid Status scrape; none found after retries → ``(None, None)``."""
    monkeypatch.setattr(
        "roboToald.discord_client.commands.cmd_sso.config.raid_guild_ids",
        lambda: [],
    )

    async def instant_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr("roboToald.discord_client.commands.cmd_sso.asyncio.sleep", instant_sleep)

    channel = _channel_mock()
    channel.send = AsyncMock()
    channel.history = MagicMock(return_value=_MockAsyncHistory([]))

    embeds, proposal = await SSOCommands._get_reconcile_embed_response(channel, inter=None)

    assert embeds is None
    assert proposal is None
