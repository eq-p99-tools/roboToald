"""Tests for welcome / policy-agree helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from roboToald import config
from roboToald.discord_client.commands import cmd_welcome


def test_welcome_enabled_requires_flag_and_member_role(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"enable_welcome": True, "member_role": 0})
    assert cmd_welcome._welcome_enabled(1) is False
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"enable_welcome": True, "member_role": 99})
    assert cmd_welcome._welcome_enabled(1) is True
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"enable_welcome": False, "member_role": 99})
    assert cmd_welcome._welcome_enabled(1) is False


def test_policy_text_prefers_file(tmp_path, monkeypatch):
    policy = tmp_path / "policy.txt"
    policy.write_text("File policy body", encoding="utf-8")
    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        1,
        {"welcome_policy_file": str(policy), "welcome_policy": "inline ignored"},
    )
    assert cmd_welcome._policy_text(1) == "File policy body"


def test_policy_text_inline_and_default(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy": "Line1\\nLine2"})
    assert cmd_welcome._policy_text(1) == "Line1\nLine2"
    monkeypatch.setitem(config.GUILD_SETTINGS, 2, {})
    assert "I Agree" in cmd_welcome._policy_text(2)


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
        {"enable_welcome": True, "member_role": 55, "welcome_channel": 1},
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
        {"enable_welcome": True, "member_role": 55},
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
            "enable_welcome": True,
            "member_role": 55,
            "welcome_channel": 123,
            "welcome_dm_on_join": True,
        },
    )

    await cmd_welcome.handle_member_join(member)
    member.send.assert_awaited_once()
    assert "#123" in member.send.await_args.args[0]
