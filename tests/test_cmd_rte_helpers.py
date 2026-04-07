"""Tests for RTE command helpers (duration formatting, autocomplete data)."""

from __future__ import annotations

import contextlib

import pytest

from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.target import Target, TargetAlias
from roboToald.discord_client.commands import cmd_rte


@pytest.fixture()
def patch_cmd_rte_raid_session(raid_session, monkeypatch):
    @contextlib.contextmanager
    def fake_get_raid_session(_guild_id: int):
        yield raid_session

    monkeypatch.setattr(cmd_rte, "get_raid_session", fake_get_raid_session)


def test_fmt_duration_none_and_zero():
    assert cmd_rte._fmt_duration(None) == "0m"
    assert cmd_rte._fmt_duration(0) == "0m"
    assert cmd_rte._fmt_duration(-5) == "0m"


def test_fmt_duration_minutes_only():
    assert cmd_rte._fmt_duration(90) == "1m"


def test_fmt_duration_hours_and_minutes():
    assert cmd_rte._fmt_duration(3661) == "1h 1m"


def test_rte_target_choices_filters_by_name(patch_cmd_rte_raid_session, raid_session):
    raid_session.add_all(
        [
            Target(name="Alpha Dragon", can_rte=True, parent=""),
            Target(name="Beta Wurm", can_rte=True, parent=None),
        ]
    )
    raid_session.commit()

    choices = cmd_rte._rte_target_choices("alp", 1)
    assert choices == {"Alpha Dragon": "Alpha Dragon"}


def test_rte_target_choices_includes_alias_match(patch_cmd_rte_raid_session, raid_session):
    t = Target(name="Lord Nagafen", can_rte=True, parent="")
    raid_session.add(t)
    raid_session.flush()
    raid_session.add(TargetAlias(target_id=t.id, name="naggy"))
    raid_session.commit()

    choices = cmd_rte._rte_target_choices("nag", 1)
    assert "Lord Nagafen" in choices.values()


def test_character_choices_prefix(patch_cmd_rte_raid_session, raid_session):
    raid_session.add_all(
        [
            Character(name="Alice", klass="Warlord"),
            Character(name="Bob", klass="Arch Mage"),
        ]
    )
    raid_session.commit()

    choices = cmd_rte._character_choices("ali", 1)
    assert choices == {"Alice": "Alice"}


@pytest.mark.asyncio
async def test_rte_status_smoke_no_active_trackings(patch_cmd_rte_raid_session, fake_inter):
    """Smoke: ``/rte status`` with empty DB sends the no-sessions message."""
    inter = fake_inter
    await cmd_rte.status(inter)
    inter.response.send_message.assert_awaited_once()
    args, kwargs = inter.response.send_message.call_args
    assert args[0] == "No active RTE sessions."
    assert kwargs.get("ephemeral") is True
