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
    monkeypatch.setitem(
        config.GUILD_SETTINGS, 1, {"welcome_channel": 123, "welcome_policy_file": '  "data/welcome_policy.txt"  '}
    )
    assert cmd_welcome._welcome_enabled(1) is True


def test_policy_text_reads_file(tmp_path, monkeypatch):
    policy = tmp_path / "policy.txt"
    policy.write_text("File policy body", encoding="utf-8")
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy_file": str(policy)})
    assert cmd_welcome._policy_text(1) == "File policy body"


def test_policy_text_strips_quotes_and_resolves_relative(tmp_path, monkeypatch):
    policy = tmp_path / "welcome_policy.txt"
    policy.write_text("Quoted path body", encoding="utf-8")
    monkeypatch.setattr(cmd_welcome, "_config_dir", lambda: tmp_path)
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy_file": '"welcome_policy.txt"'})
    assert cmd_welcome._policy_text(1) == "Quoted path body"


def test_policy_text_missing_file(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 1, {"welcome_policy_file": "/no/such/policy.txt"})
    assert cmd_welcome._policy_text(1) is None
    monkeypatch.setitem(config.GUILD_SETTINGS, 2, {})
    assert cmd_welcome._policy_text(2) is None


@pytest.mark.asyncio
async def test_welcome_agree_grants_member_role(monkeypatch):
    guild = MagicMock()
    guild.id = 10
    guild.me = MagicMock()
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = MagicMock()
    role = MagicMock()
    role.id = 55
    role.mention = "<@&55>"
    # role < bot top role
    role.__ge__ = MagicMock(return_value=False)
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
    guild.me = MagicMock()
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = MagicMock()
    role = MagicMock()
    role.id = 55
    role.mention = "<@&55>"
    role.__ge__ = MagicMock(return_value=False)
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
async def test_welcome_agree_rejects_role_hierarchy(monkeypatch):
    guild = MagicMock()
    guild.id = 10
    guild.me = MagicMock()
    guild.me.guild_permissions.manage_roles = True
    guild.me.top_role = MagicMock()
    role = MagicMock()
    role.id = 55
    role.mention = "<@&55>"
    role.__ge__ = MagicMock(return_value=True)  # role >= bot top role
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
    member.add_roles.assert_not_called()
    assert "higher" in inter.response.send_message.await_args.args[0].lower()


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
        },
    )
    monkeypatch.setattr(cmd_welcome, "ensure_welcome_message", AsyncMock(return_value=True))

    await cmd_welcome.handle_member_join(member)
    member.send.assert_awaited_once()
    assert "#123" in member.send.await_args.args[0]
    cmd_welcome.ensure_welcome_message.assert_awaited_once_with(member.guild)


@pytest.mark.asyncio
async def test_ensure_welcome_posts_when_history_forbidden(tmp_path, monkeypatch):
    """History Forbidden must not block the initial channel.send."""
    policy = tmp_path / "policy.txt"
    policy.write_text("Be excellent", encoding="utf-8")

    guild = MagicMock()
    guild.id = 10
    guild.name = "SKP"
    guild.me = MagicMock()
    role = MagicMock()
    role.mention = "<@&55>"
    guild.get_role.return_value = role

    guild.default_role = MagicMock()

    channel = MagicMock(spec=disnake.TextChannel)
    channel.id = 123

    class _ForbiddenHistory:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise disnake.Forbidden(MagicMock(), "no history")

    channel.history = MagicMock(return_value=_ForbiddenHistory())
    channel.send = AsyncMock()
    channel.permissions_for = MagicMock(
        return_value=MagicMock(
            view_channel=True,
            send_messages=True,
            read_message_history=False,
        )
    )

    monkeypatch.setitem(
        config.GUILD_SETTINGS,
        10,
        {
            "member_role": 55,
            "welcome_channel": 123,
            "welcome_policy_file": str(policy),
        },
    )
    monkeypatch.setattr(cmd_welcome, "_resolve_welcome_channel", AsyncMock(return_value=channel))

    ok = await cmd_welcome.ensure_welcome_message(guild)
    assert ok is True
    channel.send.assert_awaited_once()
    kwargs = channel.send.await_args.kwargs
    assert "I Agree" in kwargs["components"][0].label
    assert "Be excellent" in kwargs["content"]
