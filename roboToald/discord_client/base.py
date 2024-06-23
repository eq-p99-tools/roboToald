import re

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import alert as alert_model
from roboToald import utils

DISCORD_INTENTS = disnake.Intents.default()
DISCORD_INTENTS.message_content = True
DISCORD_INTENTS.guild_messages = True
DISCORD_INTENTS.members = True
DISCORD_SYNC_FLAGS = disnake.ext.commands.CommandSyncFlags.default()
DISCORD_SYNC_FLAGS.sync_commands_debug = True
DISCORD_CLIENT = commands.Bot(
    command_prefix="!",
    command_sync_flags=DISCORD_SYNC_FLAGS,
    intents=DISCORD_INTENTS
)


def find_match(channel, message):
    alerts_sent = set()
    for alert in alert_model.get_alerts_for_channel(channel):
        matches_filter = True
        if alert.alert_regex:
            matches_filter = re.match(
                alert.alert_regex, message.clean_content, flags=re.IGNORECASE)
        matches_role = True
        if alert.alert_role:
            matches_role = False
            for mention in message.role_mentions:
                # TODO: This doesn't work for @everyone because it is treated
                # differently than other roles...
                if mention.id == alert.alert_role:
                    matches_role = True
                    break
        if matches_filter and matches_role:
            # Check to make sure the user has the right role to see this alert
            if not is_user_authorized(
                    message.guild,
                    alert.user_id,
                    config.get_member_role(message.guild.id)):
                print(f"Skipping alert #{alert.id}, user not authorized")
            elif alert.alert_url not in alerts_sent:
                print(f"Sending alert #{alert.id}")
                utils.send_alert(alert, message.clean_content)
                alerts_sent.add(alert.alert_url)
            else:
                print(f"Skipping alert #{alert.id}, already triggered for "
                      f"this URL")


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
