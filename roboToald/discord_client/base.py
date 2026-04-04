import logging
import re

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import alert as alert_model
from roboToald.discord_client.wakeup import wakeup
from roboToald import utils

logger = logging.getLogger(__name__)


def resolve_alert_owner_display_name(guild: disnake.Guild | None, user_id: int) -> str | None:
    """Best-effort display name for the alert owner (member in guild, else global user)."""
    if guild:
        member = guild.get_member(user_id)
        if member:
            return member.display_name
    user = DISCORD_CLIENT.get_user(user_id)
    if user:
        return user.global_name or user.name
    return None


def resolve_guild_display_name(guild: disnake.Guild | None, guild_id: int) -> str | None:
    """Best-effort guild name from a guild object or DISCORD_CLIENT cache."""
    if guild is not None and guild.id == guild_id:
        return guild.name
    g = DISCORD_CLIENT.get_guild(guild_id)
    return g.name if g else None


DISCORD_INTENTS = disnake.Intents.default()
# DISCORD_INTENTS = disnake.Intents.all()
DISCORD_INTENTS.message_content = True
DISCORD_INTENTS.guild_messages = True
DISCORD_INTENTS.members = True
DISCORD_SYNC_FLAGS = disnake.ext.commands.CommandSyncFlags.all()
# DISCORD_SYNC_FLAGS.sync_commands_debug = True
DISCORD_CLIENT = commands.Bot(command_prefix="!", command_sync_flags=DISCORD_SYNC_FLAGS, intents=DISCORD_INTENTS)
DISCORD_CLIENT.load_extension("roboToald.discord_client.commands.cmd_sso")


def find_match(channel, message):
    alerts_sent = set()
    for alert in alert_model.get_alerts_for_channel(channel):
        matches_filter = True
        if alert.alert_regex:
            matches_filter = re.match(alert.alert_regex, message.clean_content, flags=re.IGNORECASE)
        matches_role = True
        if alert.alert_role:
            matches_role = False
            for mention in message.role_mentions:
                # TODO: This doesn't work for @everyone because it is treated
                # differently than other roles...
                if mention.id == alert.alert_role:
                    matches_role = True
                    break
            # handle if the role is @everyone
            if message.mention_everyone:
                role_name = message.guild.get_role(alert.alert_role).mention
                if role_name == "@everyone":
                    matches_role = True
        if matches_filter and matches_role:
            # Check to make sure the user has the right role to see this alert
            if not is_user_authorized(message.guild, alert.user_id, config.get_member_role(message.guild.id)):
                logger.info("Skipping alert #%s, user not authorized", alert.id)
            elif alert.alert_url not in alerts_sent:
                logger.info("Sending alert #%s", alert.id)
                owner_display = resolve_alert_owner_display_name(message.guild, alert.user_id)
                guild_display = resolve_guild_display_name(message.guild, alert.guild_id)
                utils.send_alert(
                    alert,
                    message.clean_content,
                    alert_owner_display_name=owner_display,
                    guild_name=guild_display,
                )
                alerts_sent.add(alert.alert_url)
            else:
                logger.info("Skipping alert #%s, already triggered for this URL", alert.id)


def is_user_authorized(guild: disnake.Guild, user_id: int, role_id: int) -> bool:
    user = guild.get_member(user_id)
    if user:
        role = user.get_role(role_id)
        if role:
            return True
    return False


@DISCORD_CLIENT.event
async def on_message(message):
    # Don't trigger on our own messages
    if message.author.id == DISCORD_CLIENT.user.id:
        return

    # Search for matches to registered alerts
    if message.channel.id in alert_model.get_registered_channels():
        find_match(channel=message.channel.id, message=message)

    await wakeup.process_message(message)
