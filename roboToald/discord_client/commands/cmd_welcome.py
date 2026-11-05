"""Guild welcome / policy agreement → grant ``member_role`` (not DS active role)."""

from __future__ import annotations

import logging
from pathlib import Path

import disnake

from roboToald import config
from roboToald.discord_client import base

logger = logging.getLogger(__name__)

WELCOME_AGREE_PREFIX = "welcome_agree:"
WELCOME_MESSAGE_MARKER = "<!-- robotoald-welcome -->"


def _welcome_enabled(guild_id: int) -> bool:
    settings = config.GUILD_SETTINGS.get(guild_id, {})
    return bool(settings.get("enable_welcome")) and bool(settings.get("member_role"))


def _policy_text(guild_id: int) -> str:
    settings = config.GUILD_SETTINGS.get(guild_id, {})
    policy_file = settings.get("welcome_policy_file")
    if policy_file:
        path = Path(policy_file)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            logger.exception("Failed to read welcome_policy_file %s for guild %s", path, guild_id)
    inline = (settings.get("welcome_policy") or "").strip()
    if inline:
        return inline.replace("\\n", "\n")
    return (
        "Welcome!\n\n"
        "Please read our server policy and click **I Agree** to receive the member role "
        "and access the rest of the server."
    )


def _welcome_content(guild: disnake.Guild) -> str:
    role_id = config.GUILD_SETTINGS.get(guild.id, {}).get("member_role") or 0
    role = guild.get_role(role_id) if role_id else None
    role_label = role.mention if role else "the member role"
    policy = _policy_text(guild.id)
    return (
        f"{WELCOME_MESSAGE_MARKER}\n"
        f"**Welcome to {guild.name}**\n\n"
        f"{policy}\n\n"
        f"Click **I Agree** below to accept and receive {role_label}."
    )


def _agree_components(guild_id: int) -> list[disnake.ui.Button]:
    return [
        disnake.ui.Button(
            label="I Agree",
            style=disnake.ButtonStyle.success,
            custom_id=f"{WELCOME_AGREE_PREFIX}{guild_id}",
        )
    ]


def _message_is_welcome(message: disnake.Message, guild_id: int) -> bool:
    if message.author.id != base.DISCORD_CLIENT.user.id:
        return False
    if WELCOME_MESSAGE_MARKER in (message.content or ""):
        return True
    expected = f"{WELCOME_AGREE_PREFIX}{guild_id}"
    for row in message.components or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == expected:
                return True
    return False


async def ensure_welcome_message(guild: disnake.Guild) -> None:
    """Post or refresh the persistent welcome/policy message for one guild."""
    if not _welcome_enabled(guild.id):
        return
    settings = config.GUILD_SETTINGS[guild.id]
    channel_id = settings.get("welcome_channel") or 0
    if not channel_id:
        logger.warning("enable_welcome set for guild %s but welcome_channel is unset", guild.id)
        return
    channel = guild.get_channel(channel_id)
    if channel is None or not isinstance(channel, disnake.TextChannel):
        logger.warning("welcome_channel %s not found or not a text channel in guild %s", channel_id, guild.id)
        return

    content = _welcome_content(guild)
    components = _agree_components(guild.id)
    try:
        async for message in channel.history(limit=50):
            if _message_is_welcome(message, guild.id):
                await message.edit(content=content, components=components)
                logger.info("Refreshed welcome message in guild %s channel %s", guild.id, channel_id)
                return
        await channel.send(content=content, components=components)
        logger.info("Posted welcome message in guild %s channel %s", guild.id, channel_id)
    except disnake.Forbidden:
        logger.warning("Missing permission to manage welcome message in guild %s channel %s", guild.id, channel_id)
    except Exception:
        logger.exception("Failed to ensure welcome message for guild %s", guild.id)


async def ensure_all_welcome_messages() -> None:
    for guild_id, settings in config.GUILD_SETTINGS.items():
        if not settings.get("enable_welcome"):
            continue
        guild = base.DISCORD_CLIENT.get_guild(guild_id)
        if guild is None:
            logger.warning("Welcome guild %s not available", guild_id)
            continue
        await ensure_welcome_message(guild)


async def welcome_agree_listener(inter: disnake.MessageInteraction) -> None:
    custom_id = inter.component.custom_id or ""
    if not custom_id.startswith(WELCOME_AGREE_PREFIX):
        return
    try:
        guild_id = int(custom_id[len(WELCOME_AGREE_PREFIX) :])
    except ValueError:
        await inter.response.send_message("Invalid welcome button.", ephemeral=True)
        return

    if inter.guild is None or inter.guild.id != guild_id:
        await inter.response.send_message(
            "Please use this button in the server it belongs to.",
            ephemeral=True,
        )
        return

    if not _welcome_enabled(guild_id):
        await inter.response.send_message("Welcome agreement is not enabled here.", ephemeral=True)
        return

    role_id = config.GUILD_SETTINGS.get(guild_id, {}).get("member_role") or 0
    role = inter.guild.get_role(role_id)
    if role is None:
        await inter.response.send_message(
            "Member role is not configured correctly. Please contact a moderator.",
            ephemeral=True,
        )
        return

    member = inter.guild.get_member(inter.user.id)
    if member is None and isinstance(inter.author, disnake.Member):
        member = inter.author
    if member is None or not hasattr(member, "add_roles"):
        await inter.response.send_message("Could not resolve your membership.", ephemeral=True)
        return

    if role in member.roles:
        await inter.response.send_message(
            f"You already have {role.mention}. You're all set.",
            ephemeral=True,
        )
        return

    try:
        await member.add_roles(role, reason="Welcome policy accepted")
    except disnake.Forbidden:
        logger.warning(
            "Missing permission to grant member_role %s to %s in guild %s",
            role_id,
            member.id,
            guild_id,
        )
        await inter.response.send_message(
            "I don't have permission to grant that role. Please contact a moderator.",
            ephemeral=True,
        )
        return
    except Exception:
        logger.exception("Failed to grant member_role to %s in guild %s", member.id, guild_id)
        await inter.response.send_message(
            "Something went wrong granting the role. Please contact a moderator.",
            ephemeral=True,
        )
        return

    await inter.response.send_message(
        f"Thanks — policy accepted. You now have {role.mention}.",
        ephemeral=True,
    )


async def handle_member_join(member: disnake.Member) -> None:
    """DM a pointer to the welcome channel when a new member joins."""
    if member.bot or not _welcome_enabled(member.guild.id):
        return
    settings = config.GUILD_SETTINGS.get(member.guild.id, {})
    if not settings.get("welcome_dm_on_join", True):
        return
    role_id = settings.get("member_role") or 0
    if role_id and member.get_role(role_id):
        return
    channel_id = settings.get("welcome_channel") or 0
    if not channel_id:
        return
    try:
        await member.send(
            f"Welcome to **{member.guild.name}**!\n"
            f"Please open <#{channel_id}> , read the policy, and click **I Agree** "
            f"to get access."
        )
    except disnake.Forbidden:
        logger.info("Could not DM welcome instructions to user %s (DMs closed)", member.id)
    except Exception:
        logger.exception("Failed to DM welcome instructions to user %s", member.id)


BUTTON_LISTENERS = {
    WELCOME_AGREE_PREFIX: welcome_agree_listener,
}
