"""Tests for raid auto-attendance (session overlap, proposals, Apply button).

Uses the in-memory ``raid_session`` fixture for real DB operations; mocks only
Discord, EQDKP HTTP (via ``EqdkpClient`` methods), and ``sso_model.get_sessions_in_range``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from roboToald import config
from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.raid import Attendee, Event
from roboToald.db.raid_models.target import Target
from roboToald.eqdkp.client import EqdkpClient
from roboToald.raid import auto_attendance
from roboToald.raid.auto_attendance import (
    MIN_PRESENCE_FRACTION,
    MIN_PRESENCE_SECONDS,
    _build_user_overlaps,
    _compute_overlap_seconds,
    on_auto_att_button,
    propose_online_players,
)

GUILD_ID = 900_001
EVENT_CHANNEL_ID = 999
MOB_NAME = "Lord Nagafen"


@dataclass
class SessionStub:
    """Duck-types ``SSOCharacterSession`` for overlap helpers and ``get_sessions_in_range`` stubs."""

    first_seen: datetime
    last_seen: datetime
    character_name: str
    discord_user_id: int


@pytest.fixture(autouse=True)
def clear_eqdkp_cache() -> None:
    auto_attendance._player_char_cache.clear()
    yield
    auto_attendance._player_char_cache.clear()


@pytest.fixture()
def patch_auto_att_raid_session(raid_session, monkeypatch):
    """Redirect ``get_raid_session`` in ``auto_attendance`` to the test in-memory session."""

    @contextlib.contextmanager
    def fake_raid_session(guild_id: int):
        yield raid_session

    monkeypatch.setattr("roboToald.raid.auto_attendance.get_raid_session", fake_raid_session)


@pytest.fixture()
def fake_auto_att_config(monkeypatch):
    """Per-guild raid + EQdkp settings so ``auto_attendance`` and ``eqdkp_is_configured`` pass."""

    raid = dict(config.RAID_SETTINGS)
    raid[GUILD_ID] = {
        **config.RAID_SETTINGS.get(GUILD_ID, {}),
        "database_path": ":memory:",
        "auto_attendance": True,
    }
    eqdkp = dict(config.EQDKP_SETTINGS)
    eqdkp[GUILD_ID] = {
        "url": "https://example.test/api",
        "host": "example.test",
        "api_key": "test-api-key",
        "adjustment_event_id": 0,
    }
    monkeypatch.setattr(config, "RAID_SETTINGS", raid)
    monkeypatch.setattr(config, "EQDKP_SETTINGS", eqdkp)


def _presence_threshold_seconds(event_start: datetime, death_time: datetime) -> float:
    event_duration = max(1.0, (death_time - event_start).total_seconds())
    return min(event_duration * MIN_PRESENCE_FRACTION, MIN_PRESENCE_SECONDS)


def _qualifying_discord_ids(sessions: list, event_start: datetime, death_time: datetime) -> set[int]:
    threshold = _presence_threshold_seconds(event_start, death_time)
    overlaps = _build_user_overlaps(sessions, event_start, death_time)
    return {uid for uid, (sec, _) in overlaps.items() if sec >= threshold}


# ---------------------------------------------------------------------------
# Pure logic (no I/O)
# ---------------------------------------------------------------------------


def test_compute_overlap_seconds_full_and_partial():
    es = datetime(2025, 1, 1, 10, 0, 0)
    de = datetime(2025, 1, 1, 11, 0, 0)
    # Fully inside
    assert _compute_overlap_seconds(datetime(2025, 1, 1, 10, 0, 0), datetime(2025, 1, 1, 10, 30, 0), es, de) == 1800.0
    # Partial overlap at start
    assert _compute_overlap_seconds(datetime(2025, 1, 1, 9, 30, 0), datetime(2025, 1, 1, 10, 15, 0), es, de) == 900.0
    # No overlap (before window)
    assert _compute_overlap_seconds(datetime(2025, 1, 1, 8, 0, 0), datetime(2025, 1, 1, 9, 0, 0), es, de) == 0.0


def test_build_user_overlaps_picks_dominant_char():
    es = datetime(2025, 1, 1, 10, 0, 0)
    de = datetime(2025, 1, 1, 12, 0, 0)
    uid = 42
    sessions = [
        SessionStub(
            first_seen=datetime(2025, 1, 1, 10, 0, 0),
            last_seen=datetime(2025, 1, 1, 10, 10, 0),
            character_name="CharA",
            discord_user_id=uid,
        ),
        SessionStub(
            first_seen=datetime(2025, 1, 1, 10, 10, 0),
            last_seen=datetime(2025, 1, 1, 10, 15, 0),
            character_name="CharB",
            discord_user_id=uid,
        ),
    ]
    out = _build_user_overlaps(sessions, es, de)
    total, dominant = out[uid]
    assert total == pytest.approx(600.0 + 300.0)
    assert dominant == "CharA"


def test_threshold_filtering_short_and_long_events():
    es = datetime(2025, 1, 1, 10, 0, 0)
    # Short 3-minute event: threshold = min(90, 120) = 90s
    de_short = es + timedelta(minutes=3)
    assert _presence_threshold_seconds(es, de_short) == 90.0
    sessions_short = [
        SessionStub(es, es + timedelta(seconds=100), "A", 1),
        SessionStub(es, es + timedelta(seconds=80), "B", 2),
    ]
    q = _qualifying_discord_ids(sessions_short, es, de_short)
    assert 1 in q and 2 not in q

    # Long 30-minute event: threshold = 120s
    de_long = es + timedelta(minutes=30)
    assert _presence_threshold_seconds(es, de_long) == 120.0
    sessions_long = [
        SessionStub(es, es + timedelta(seconds=121), "C", 3),
        SessionStub(es, es + timedelta(seconds=119), "D", 4),
    ]
    q2 = _qualifying_discord_ids(sessions_long, es, de_long)
    assert 3 in q2 and 4 not in q2


# ---------------------------------------------------------------------------
# propose_online_players e2e
# ---------------------------------------------------------------------------


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_propose_online_players_e2e(
    raid_session,
    monkeypatch,
    patch_auto_att_raid_session,
    fake_auto_att_config,
):
    now = datetime.now()
    local_tz = datetime.now().astimezone().tzinfo
    event_start_local = now - timedelta(minutes=30)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name=MOB_NAME)
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(EVENT_CHANNEL_ID),
            created_at=evt_created_at,
            killed=False,
        )
    )
    raid_session.commit()

    stubs = [
        SessionStub(event_start_local, now, "Boxchar1", 100),
        SessionStub(event_start_local + timedelta(minutes=10), now, "Ownmain", 200),
        SessionStub(event_start_local, event_start_local + timedelta(seconds=30), "Shortie", 300),
    ]

    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.sso_model.get_sessions_in_range",
        lambda *_a, **_k: stubs,
    )

    async def fake_find_by_discord(self, discord_id: str | int) -> list[dict]:
        did = int(discord_id)
        if did == 100:
            return [{"name": "Amy"}]
        if did == 200:
            return [{"name": "Ownmain"}]
        return []

    monkeypatch.setattr(EqdkpClient, "find_characters_by_discord_id", fake_find_by_discord)

    channel = AsyncMock()
    guild = MagicMock()
    guild.get_channel = MagicMock(return_value=channel)
    discord_client = MagicMock()
    discord_client.get_guild = MagicMock(return_value=guild)

    await propose_online_players(GUILD_ID, MOB_NAME, discord_client)

    channel.send.assert_awaited_once()
    content = channel.send.call_args[0][0]
    assert "Suggested attendance" in content and MOB_NAME in content
    assert "+Amy on Boxchar1" in content
    assert "+Ownmain" in content
    assert "Ownmain on" not in content
    assert "Shortie" not in content
    assert "view" in channel.send.call_args.kwargs


# ---------------------------------------------------------------------------
# Apply button
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_button_creates_attendees(
    raid_session,
    monkeypatch,
    patch_auto_att_raid_session,
    fake_auto_att_config,
):
    target = Target(name=MOB_NAME)
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(EVENT_CHANNEL_ID),
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            killed=False,
        )
    )
    raid_session.add(Character(name="Boxchar1"))
    raid_session.commit()

    async def fake_find_character(self, char_name: str) -> dict | None:
        return {"id": 101, "user_id": 201, "main_id": None}

    monkeypatch.setattr(EqdkpClient, "find_character", fake_find_character)

    inter = MagicMock()
    inter.component.custom_id = f"{auto_attendance.CUSTOM_ID_APPLY}:{GUILD_ID}"
    inter.channel_id = EVENT_CHANNEL_ID
    inter.message.content = "Suggested attendance\n```\n+Amy on Boxchar1 (30m)\n+Betty (20m)\n```"
    inter.author.display_name = "RaidLead"
    inter.response = AsyncMock()
    inter.followup = AsyncMock()

    await on_auto_att_button(inter)

    inter.response.edit_message.assert_awaited_once()
    inter.followup.send.assert_awaited_once()
    followup_text = inter.followup.send.call_args[0][0]
    assert "Amy" in followup_text
    assert "Betty" in followup_text
    assert "was added" in followup_text

    evt = raid_session.query(Event).filter_by(channel_id=str(EVENT_CHANNEL_ID)).one()
    names = {c.name for c in raid_session.query(Character).all()}
    assert "Amy" in names and "Betty" in names
    attendees = raid_session.query(Attendee).filter_by(event_id=evt.id).all()
    assert len(attendees) == 2
    box = raid_session.query(Character).filter_by(name="Boxchar1").one()
    amy_att = next(
        a for a in attendees if raid_session.query(Character).filter_by(id=int(a.character_id)).one().name == "Amy"
    )
    assert amy_att.on_character_id == str(box.id)


@pytest.mark.asyncio
async def test_apply_button_dedup(
    raid_session,
    monkeypatch,
    patch_auto_att_raid_session,
    fake_auto_att_config,
):
    target = Target(name=MOB_NAME)
    raid_session.add(target)
    raid_session.flush()
    amy_char = Character(name="Amy")
    raid_session.add(amy_char)
    raid_session.flush()
    evt = Event(
        target_id=target.id,
        channel_id=str(EVENT_CHANNEL_ID),
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        killed=False,
    )
    raid_session.add(evt)
    raid_session.flush()
    raid_session.add(Attendee(event_id=evt.id, character_id=str(amy_char.id), reason=""))
    raid_session.add(Character(name="Boxchar1"))
    raid_session.commit()

    async def fake_find_character(self, char_name: str) -> dict | None:
        return {"id": 101, "user_id": 201, "main_id": None}

    monkeypatch.setattr(EqdkpClient, "find_character", fake_find_character)

    inter = MagicMock()
    inter.component.custom_id = f"{auto_attendance.CUSTOM_ID_APPLY}:{GUILD_ID}"
    inter.channel_id = EVENT_CHANNEL_ID
    inter.message.content = "```\n+Amy on Boxchar1 (30m)\n+Betty (20m)\n```"
    inter.author.display_name = "RaidLead"
    inter.response = AsyncMock()
    inter.followup = AsyncMock()

    await on_auto_att_button(inter)

    followup_text = inter.followup.send.call_args[0][0]
    assert "already exists in this event" in followup_text
    assert "Betty" in followup_text
    evt_db = raid_session.query(Event).filter_by(channel_id=str(EVENT_CHANNEL_ID)).one()
    count = raid_session.query(Attendee).filter_by(event_id=evt_db.id).count()
    assert count == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@freeze_time("2025-06-15 14:00:00")
@pytest.mark.asyncio
async def test_propose_skips_killed_event(
    raid_session,
    monkeypatch,
    patch_auto_att_raid_session,
    fake_auto_att_config,
):
    now = datetime.now()
    local_tz = datetime.now().astimezone().tzinfo
    event_start_local = now - timedelta(minutes=30)
    evt_created_at = event_start_local.replace(tzinfo=local_tz).astimezone(timezone.utc).replace(tzinfo=None)

    target = Target(name=MOB_NAME)
    raid_session.add(target)
    raid_session.flush()
    raid_session.add(
        Event(
            target_id=target.id,
            channel_id=str(EVENT_CHANNEL_ID),
            created_at=evt_created_at,
            killed=True,
        )
    )
    raid_session.commit()

    monkeypatch.setattr(
        "roboToald.raid.auto_attendance.sso_model.get_sessions_in_range",
        lambda *_a, **_k: [SessionStub(event_start_local, now, "X", 1)],
    )

    channel = AsyncMock()
    guild = MagicMock()
    guild.get_channel = MagicMock(return_value=channel)
    discord_client = MagicMock()
    discord_client.get_guild = MagicMock(return_value=guild)

    await propose_online_players(GUILD_ID, MOB_NAME, discord_client)

    channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_propose_skips_when_disabled(monkeypatch):
    raid = dict(config.RAID_SETTINGS)
    raid[GUILD_ID] = {
        **config.RAID_SETTINGS.get(GUILD_ID, {}),
        "database_path": ":memory:",
        "auto_attendance": False,
    }
    eqdkp = dict(config.EQDKP_SETTINGS)
    eqdkp[GUILD_ID] = {
        "url": "https://example.test/api",
        "host": "example.test",
        "api_key": "key",
        "adjustment_event_id": 0,
    }
    monkeypatch.setattr(config, "RAID_SETTINGS", raid)
    monkeypatch.setattr(config, "EQDKP_SETTINGS", eqdkp)

    def boom(*_a, **_k):
        raise AssertionError("get_raid_session should not run when auto_attendance is disabled")

    monkeypatch.setattr("roboToald.raid.auto_attendance.get_raid_session", boom)

    discord_client = MagicMock()
    await propose_online_players(GUILD_ID, MOB_NAME, discord_client)


@pytest.mark.asyncio
async def test_propose_skips_no_target_match(
    raid_session,
    monkeypatch,
    patch_auto_att_raid_session,
    fake_auto_att_config,
):
    channel = AsyncMock()
    guild = MagicMock()
    guild.get_channel = MagicMock(return_value=channel)
    discord_client = MagicMock()
    discord_client.get_guild = MagicMock(return_value=guild)

    await propose_online_players(GUILD_ID, "Unknown Mob XYZ", discord_client)

    channel.send.assert_not_awaited()
