"""Tests for the login-notes Discord command helpers in ``cmd_sso``."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from roboToald.db.models import sso as sso_model
from roboToald.discord_client.commands import cmd_sso
from tests.conftest import make_fake_inter

GUILD_ID = 1
OWNER_ID = 100
OTHER_ID = 999


@pytest.fixture()
def notify(monkeypatch):
    calls = []
    monkeypatch.setattr(cmd_sso.ws_manager, "notify_guild", lambda gid, immediate=False: calls.append((gid, immediate)))
    return calls


@pytest.fixture()
def audits(monkeypatch):
    calls = []
    monkeypatch.setattr(cmd_sso.sso_model, "create_audit_log", lambda **kw: calls.append(kw))
    return calls


@pytest.fixture()
def not_admin(monkeypatch):
    monkeypatch.setattr(cmd_sso, "_inter_is_admin", lambda inter: False)


async def test_owner_sets_and_clears_account_notes(sso_session, notify, audits, not_admin):
    sso_model.create_account(GUILD_ID, "ownedbot", "pw", owner_discord_user_id=OWNER_ID)
    cog = cmd_sso.SSOCommands(MagicMock())
    inter = make_fake_inter()

    await cog._apply_account_notes(inter, "ownedbot", "Kael factioned")
    assert sso_model.get_account(GUILD_ID, "ownedbot").notes == "Kael factioned"
    assert "Kael factioned" in inter.send.await_args.kwargs["content"]
    assert inter.send.await_args.kwargs["ephemeral"] is True
    public = inter.channel.send.await_args.args[0]
    assert "ownedbot" in public and "Kael factioned" not in public

    await cog._apply_account_notes(inter, "ownedbot", None)
    assert sso_model.get_account(GUILD_ID, "ownedbot").notes is None

    assert [a["details"] for a in audits] == ["discord:set account notes", "discord:cleared account notes"]
    assert all(a["rate_limit"] is False and a["discord_user_id"] == OWNER_ID for a in audits)
    assert notify == [(GUILD_ID, True), (GUILD_ID, True)]


async def test_non_owner_cannot_set_account_notes(sso_session, notify, audits, not_admin):
    sso_model.create_account(GUILD_ID, "otherbot", "pw", owner_discord_user_id=OTHER_ID)
    cog = cmd_sso.SSOCommands(MagicMock())
    inter = make_fake_inter()

    await cog._apply_account_notes(inter, "otherbot", "nope")
    assert sso_model.get_account(GUILD_ID, "otherbot").notes is None
    assert "do not own" in inter.send.await_args.kwargs["content"]
    assert audits == [] and notify == []


async def test_owner_sets_character_notes(sso_session, notify, audits, not_admin):
    sso_model.create_account(GUILD_ID, "ownedbot", "pw", owner_discord_user_id=OWNER_ID)
    sso_model.add_account_character(GUILD_ID, "ownedbot", "Tank", sso_model.CharacterClass.Warrior)
    cog = cmd_sso.SSOCommands(MagicMock())
    inter = make_fake_inter()

    await cog._apply_character_notes(inter, "tank", "Bound in Kael")
    account = sso_model.find_account_by_username("ownedbot", GUILD_ID)
    assert sso_model.login_notes_for_account(account) == {"account": None, "characters": {"Tank": "Bound in Kael"}}
    assert audits[0]["details"] == "discord:set character notes Tank"
    assert notify == [(GUILD_ID, True)]
