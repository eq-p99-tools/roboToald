"""Guild welcome / policy agreement → grant ``member_role`` (not DS active role)."""

from __future__ import annotations

import logging
from pathlib import Path

import disnake

from roboToald import config
from roboToald.discord_client import base

logger = logging.getLogger(__name__)

WELCOME_AGREE_PREFIX = "welcome_agree:"
# Visible marker kept for older messages; prefer button custom_id for identity.
WELCOME_MESSAGE_MARKER = "<!-- robotoald-welcome -->"
# Soft cap so Discord 2000-char limit leaves room for header/footer.
_MAX_POLICY_CHARS = 1600


def _welcome_enabled(guild_id: int) -> bool:
    """Enabled when both welcome_channel and welcome_policy_file are configured."""
    settings = config.GUILD_SETTINGS.get(guild_id, {})
    channel_id = settings.get("welcome_channel") or 0
    policy_file = (settings.get("welcome_policy_file") or "").strip().strip("\"'")
    return bool(channel_id) and bool(policy_file)


def _config_dir() -> Path:
    """Directory containing batphone.ini (relative paths resolve from here, then cwd)."""
    conf_path = Path(config.CONFIG_FILENAME)
    if not conf_path.is_absolute():
        conf_path = Path.cwd() / conf_path
    return conf_path.parent


def _policy_path(guild_id: int) -> Path | None:
    settings = config.GUILD_SETTINGS.get(guild_id, {})
    policy_file = (settings.get("welcome_policy_file") or "").strip().strip("\"'")
    if not policy_file:
        return None
    path = Path(policy_file)
    if path.is_absolute():
        return path
    # Prefer paths relative to batphone.ini (Docker: /app), then cwd.
    candidates = [_config_dir() / path, Path.cwd() / path]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    # Return the ini-relative path for error messages even when missing.
    return candidates[0]


def _policy_text(guild_id: int) -> str | None:
    path = _policy_path(guild_id)
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        logger.exception("Failed to read welcome_policy_file %s for guild %s", path, guild_id)
        return None
    return text or None


def _welcome_content(guild: disnake.Guild) -> str | None:
    policy = _policy_text(guild.id)
    if not policy:
        return None
    if len(policy) > _MAX_POLICY_CHARS:
        logger.warning(
            "welcome_policy_file for guild %s is %d chars; truncating to %d for Discord limit",
            guild.id,
            len(policy),
            _MAX_POLICY_CHARS,
        )
        policy = policy[:_MAX_POLICY_CHARS].rstrip() + "\n…"
    role_id = config.GUILD_SETTINGS.get(guild.id, {}).get("member_role") or 0
    role = guild.get_role(role_id) if role_id else None
    role_label = role.mention if role else "the member role"
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
    if base.DISCORD_CLIENT.user is None or message.author.id != base.DISCORD_CLIENT.user.id:
        return False
    if WELCOME_MESSAGE_MARKER in (message.content or ""):
        return True
    expected = f"{WELCOME_AGREE_PREFIX}{guild_id}"
    for row in message.components or []:
        for child in getattr(row, "children", []) or []:
            if getattr(child, "custom_id", None) == expected:
                return True
    return False


async def _resolve_welcome_channel(guild: disnake.Guild, channel_id: int) -> disnake.TextChannel | None:
    channel = guild.get_channel(channel_id)
    if channel is None:
        try:
            fetched = await base.DISCORD_CLIENT.fetch_channel(channel_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            logger.warning(
                "welcome_channel %s not found or inaccessible in guild %s",
                channel_id,
                guild.id,
            )
            return None
        channel = fetched
    if not isinstance(channel, disnake.TextChannel):
        logger.warning(
            "welcome_channel %s is not a text channel in guild %s (got %s)",
            channel_id,
            guild.id,
            type(channel).__name__,
        )
        return None
    return channel


def _log_channel_permission_gaps(guild: disnake.Guild, channel: disnake.TextChannel) -> None:
    me = guild.me
    if me is None:
        return
    perms = channel.permissions_for(me)
    if not perms.view_channel:
        logger.warning("Bot cannot view welcome_channel %s in guild %s", channel.id, guild.id)
    if not perms.send_messages:
        logger.warning("Bot cannot send messages in welcome_channel %s in guild %s", channel.id, guild.id)
    if not perms.read_message_history:
        logger.warning(
            "Bot cannot read message history in welcome_channel %s in guild %s "
            "(will post a new welcome message without refreshing an existing one)",
            channel.id,
            guild.id,
        )
    everyone_view = channel.permissions_for(guild.default_role).view_channel
    if not everyone_view:
        logger.warning(
            "welcome_channel %s in guild %s is not visible to @everyone — "
            "new members cannot see the I Agree button until they already have access",
            channel.id,
            guild.id,
        )


async def _find_existing_welcome(
    channel: disnake.TextChannel, guild_id: int
) -> disnake.Message | None:
    """Best-effort search; returns None if history is denied or no match."""
    try:
        async for message in channel.history(limit=50):
            if _message_is_welcome(message, guild_id):
                return message
    except disnake.Forbidden:
        logger.warning(
            "Cannot read history in welcome_channel %s (guild %s); will send a new message",
            channel.id,
            guild_id,
        )
    except disnake.HTTPException:
        logger.exception(
            "Failed reading history in welcome_channel %s (guild %s); will send a new message",
            channel.id,
            guild_id,
        )
    return None


async def ensure_welcome_message(guild: disnake.Guild) -> bool:
    """Post or refresh the persistent welcome/policy message for one guild.

    Returns True when a welcome message was posted or refreshed.
    """
    if not _welcome_enabled(guild.id):
        return False
    settings = config.GUILD_SETTINGS[guild.id]
    channel_id = settings.get("welcome_channel") or 0
    channel = await _resolve_welcome_channel(guild, channel_id)
    if channel is None:
        return False

    _log_channel_permission_gaps(guild, channel)

    content = _welcome_content(guild)
    if not content:
        path = _policy_path(guild.id)
        logger.warning(
            "Welcome enabled for guild %s but policy file is missing or empty (path=%s)",
            guild.id,
            path,
        )
        return False
    if not (settings.get("member_role") or 0):
        logger.warning(
            "Welcome enabled for guild %s but member_role is unset — not posting agree button",
            guild.id,
        )
        return False
    role_id = settings.get("member_role") or 0
    if guild.get_role(role_id) is None:
        logger.warning(
            "Welcome enabled for guild %s but member_role %s is not in this guild",
            guild.id,
            role_id,
        )
        return False

    components = _agree_components(guild.id)
    existing = await _find_existing_welcome(channel, guild.id)
    try:
        if existing is not None:
            await existing.edit(content=content, components=components)
            logger.info("Refreshed welcome message in guild %s channel %s", guild.id, channel_id)
            return True
        await channel.send(content=content, components=components)
        logger.info("Posted welcome message in guild %s channel %s", guild.id, channel_id)
        return True
    except disnake.Forbidden:
        logger.warning(
            "Missing permission to manage welcome message in guild %s channel %s",
            guild.id,
            channel_id,
        )
    except Exception:
        logger.exception("Failed to ensure welcome message for guild %s", guild.id)
    return False


async def ensure_all_welcome_messages() -> None:
    ensured = 0
    for guild_id in config.GUILD_SETTINGS:
        if not _welcome_enabled(guild_id):
            continue
        guild = base.DISCORD_CLIENT.get_guild(guild_id)
        if guild is None:
            logger.warning("Welcome guild %s not available (is the bot in that server?)", guild_id)
            continue
        if await ensure_welcome_message(guild):
            ensured += 1
    logger.info(
        "Welcome ensure finished: %d guild(s) with a live agree message",
        ensured,
    )


async def welcome_agree_listener(inter: disnake.MessageInteraction) -> None:
    custom_id = (inter.component.custom_id if inter.component else None) or ""
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
        await inter.response.send_message("Welcome agreement is not configured here.", ephemeral=True)
        return

    role_id = config.GUILD_SETTINGS.get(guild_id, {}).get("member_role") or 0
    role = inter.guild.get_role(role_id) if role_id else None
    if role is None:
        await inter.response.send_message(
            "Member role is not configured correctly. Please contact a moderator.",
            ephemeral=True,
        )
        return

    me = inter.guild.me
    if me is not None:
        if not me.guild_permissions.manage_roles:
            logger.warning("Bot lacks Manage Roles in guild %s", guild_id)
            await inter.response.send_message(
                "I don't have permission to grant that role. Please contact a moderator.",
                ephemeral=True,
            )
            return
        if role >= me.top_role:
            logger.warning(
                "member_role %s is at or above bot top role in guild %s",
                role_id,
                guild_id,
            )
            await inter.response.send_message(
                "I can't assign that role (my role must be higher than it). Please contact a moderator.",
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
    """Ensure the agree message exists, then DM a pointer to the welcome channel."""
    if member.bot or not _welcome_enabled(member.guild.id):
        return
    settings = config.GUILD_SETTINGS.get(member.guild.id, {})
    # Re-ensure on join so a missed startup post / deleted message still recovers.
    try:
        await ensure_welcome_message(member.guild)
    except Exception:
        logger.exception("Failed ensuring welcome message on join for guild %s", member.guild.id)

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
