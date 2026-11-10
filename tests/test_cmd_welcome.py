"""Tests for welcome / policy-agree helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from roboToald import config
from roboToald.discord_client.commands import cmd_welcome


def test_welcome_enabled_requires_channel_and_policy_file(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_channel": 0, "welcome_policy_file": "p.txt"})
    assert cmd_welcome._welcome_enabled(1) is False
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_channel": 123, "welcome_policy_file": ""})
    assert cmd_welcome._welcome_enabled(1) is False
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_channel": 123, "welcome_policy_file": "p.txt"})
    assert cmd_welcome._welcome_enabled(1) is True


def test_policy_text_reads_file(tmp_path, monkeypatch):
    policy = tmp_path / "policy.txt"
    policy.write_text("File policy body", encoding="utf-8")
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy_file": str(policy)})
    assert cmd_welcome._policy_text(1) == "File policy body"


def test_policy_text_missing_file(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy_file": "/no/such/policy.txt"})
    assert cmd_welcome._policy_text(1) is None
    monkeypatch.setitem(config.GUILD_SETTINGS, 2, {})
    assert cmd_welcome._policy_text(2) is None


@pytest.mark.asyncio
async def test_welcome_agree_grants_member_role(monkeypatch):
    guild = MagicMock()
    guild.id = 10
    role = MagicMock()
    role.id = 55
    role.mention = "<@&55>"
    guild.get_role.return_value = role

    member = MagicMock()
    member.id = 100
    member.roles = []
    member.add_roles = AsyncMock()
    guild.get_member.return_value = member

    inter = MagicMock()
    inter.guild = guild
    inter.user.id = 100
    inter.author = member
    inter.component.custom_id = "welcome_agree:10"
    inter.response.send_message = AsyncMock()

    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {"member_role": 55, "welcome_channel": 1, "welcome_policy_file": "policy.txt"},
    )

    await cmd_welcome.welcome_agree_listener(inter)

    member.add_roles.assert_awaited_once()
    inter.response.send_message.assert_awaited()
    assert "policy accepted" in inter.response.send_message.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_welcome_agree_noop_if_already_has_role(monkeypatch):
    guild = MagicMock()
    guild.id = 10
    role = MagicMock()
    role.id = 55
    role.mention = "<@&55>"
    guild.get_role.return_value = role

    member = MagicMock()
    member.id = 100
    member.roles = [role]
    member.add_roles = AsyncMock()
    guild.get_member.return_value = member

    inter = MagicMock()
    inter.guild = guild
    inter.user.id = 100
    inter.author = member
    inter.component.custom_id = "welcome_agree:10"
    inter.response.send_message = AsyncMock()

    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {"member_role": 55, "welcome_channel": 1, "welcome_policy_file": "policy.txt"},
    )

    await cmd_welcome.welcome_agree_listener(inter)
    member.add_roles.assert_not_called()
    assert "already have" in inter.response.send_message.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_handle_member_join_dms_pointer(monkeypatch):
    member = MagicMock()
    member.bot = False
    member.id = 7
    member.guild.id = 10
    member.guild.name = "SKP"
    member.get_role.return_value = None
    member.send = AsyncMock()

    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {
            "member_role": 55,
            "welcome_channel": 123,
            "welcome_policy_file": "policy.txt",
            "welcome_dm_on_join": True,
            "welcome_ping_on_join": False,
        },
    )

    await cmd_welcome.handle_member_join(member)
    member.send.assert_awaited_once()
    assert "#123" in member.send.await_args.args[0]


def _join_member(channel):
    member = MagicMock()
    member.bot = False
    member.id = 7
    member.mention = "<@7>"
    member.guild.id = 10
    member.guild.name = "SKP"
    member.guild.get_channel.return_value = channel
    member.get_role.return_value = None
    member.send = AsyncMock()
    return member


def _welcome_channel():
    channel = MagicMock(spec=disnake.TextChannel)
    channel.send = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_handle_member_join_pings_even_when_dm_blocked(monkeypatch):
    channel = _welcome_channel()
    member = _join_member(channel)
    member.send.side_effect = disnake.Forbidden(MagicMock(status=403), "Cannot send messages to this user")
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {"member_role": 55, "welcome_channel": 123, "welcome_policy_file": "policy.txt"},
    )

    await cmd_welcome.handle_member_join(member)

    channel.send.assert_awaited_once()
    assert "<@7>" in channel.send.await_args.args[0]
    assert channel.send.await_args.kwargs["delete_after"] == cmd_welcome.WELCOME_PING_DELETE_AFTER_SECONDS
    member.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_member_join_skips_existing_members(monkeypatch):
    channel = _welcome_channel()
    member = _join_member(channel)
    member.get_role.return_value = MagicMock()
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {"member_role": 55, "welcome_channel": 123, "welcome_policy_file": "policy.txt"},
    )

    await cmd_welcome.handle_member_join(member)

    channel.send.assert_not_called()
    member.send.assert_not_called()
