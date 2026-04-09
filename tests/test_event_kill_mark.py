"""Unit tests for shared kill / no-kill event marking helpers."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from roboToald.db.raid_models.raid import Event
from roboToald.db.raid_models.target import Target, Tier
from roboToald.raid.event_kill_mark import (
    NOKILL_EMOJI,
    KILL_EMOJI,
    apply_kill_state_to_event,
    channel_name_prefix_for_kill,
    event_channel_name_with_kill_prefix,
    rename_event_channel_for_kill_name,
    rename_event_channel_for_kill_state,
)


def test_channel_name_prefix_for_kill():
    assert channel_name_prefix_for_kill(True) == KILL_EMOJI
    assert channel_name_prefix_for_kill(False) == NOKILL_EMOJI


def test_event_channel_name_with_kill_prefix():
    evt = Event(name="Raid", created_at=datetime(2024, 1, 15, 18, 0, 0))
    s = event_channel_name_with_kill_prefix(evt, True)
    assert s.startswith(KILL_EMOJI)
    assert "Raid" in s


def test_apply_kill_state_no_op_already_killed():
    evt = Event(killed=True, dkp=10, nokill_dkp=5)
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert r.status_changed is False
    assert r.dkp_value == 10


def test_apply_kill_state_no_op_already_nokill():
    evt = Event(killed=False, dkp=10, nokill_dkp=5)
    r = apply_kill_state_to_event(evt, False, set_tod_if_missing=False)
    assert r.status_changed is False
    assert r.dkp_value == 5


def test_apply_kill_state_sets_killed_from_none():
    evt = Event(killed=None, dkp=100, nokill_dkp=20)
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert r.status_changed is True
    assert evt.killed is True
    assert r.dkp_value == 100


def test_apply_kill_state_flips_nokill_to_kill():
    evt = Event(killed=False, dkp=10, nokill_dkp=25)
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert r.status_changed is True
    assert evt.killed is True
    assert r.dkp_value == 10


def test_apply_kill_state_sets_tod_when_missing():
    evt = Event(killed=None, dkp=1, nokill_dkp=1, tod_at=None)
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=True)
    assert r.status_changed is True
    assert evt.tod_at is not None


def test_apply_kill_state_does_not_set_tod_for_dollar_kill_semantics():
    evt = Event(killed=None, dkp=1, nokill_dkp=1, tod_at=None)
    apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert evt.tod_at is None


def test_apply_kill_state_dkp_none_without_target():
    evt = Event(killed=None, dkp=None, target_id=None)
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert r.status_changed is True
    assert r.dkp_value is None


def test_apply_kill_state_dkp_from_target(raid_session):
    tier = Tier(name="T", value=200, nokill_value=40)
    raid_session.add(tier)
    raid_session.flush()
    tgt = Target(name="Boss", tier_id=tier.id, value=None, nokill_value=None)
    raid_session.add(tgt)
    raid_session.flush()
    evt = Event(target_id=tgt.id, killed=None, dkp=None)
    raid_session.add(evt)
    raid_session.commit()
    r = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
    assert r.status_changed is True
    assert r.dkp_value == 200


@pytest.mark.asyncio
async def test_rename_event_channel_for_kill_name_calls_edit():
    ch = MagicMock()
    ch.edit = AsyncMock()
    await rename_event_channel_for_kill_name(ch, f"{KILL_EMOJI}my-channel")
    ch.edit.assert_awaited_once_with(name=f"{KILL_EMOJI}my-channel")


@pytest.mark.asyncio
async def test_rename_event_channel_for_kill_state_delegates():
    ch = MagicMock()
    ch.edit = AsyncMock()
    evt = Event(name="R", created_at=datetime(2024, 3, 1, 12, 0, 0))
    await rename_event_channel_for_kill_state(ch, evt, False)
    assert ch.edit.await_count == 1
    call_kw = ch.edit.await_args.kwargs
    assert "name" in call_kw
    assert call_kw["name"].startswith(NOKILL_EMOJI)


@pytest.mark.asyncio
async def test_rename_event_channel_for_kill_name_swallows_http_exception():
    ch = MagicMock()
    ch.edit = AsyncMock(side_effect=disnake.HTTPException(MagicMock(), []))
    await rename_event_channel_for_kill_name(ch, "x")
    ch.edit.assert_awaited_once()
