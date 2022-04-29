import re

from disnake.ext import commands

from roboToald import config
from roboToald.db import models
from roboToald import utils

DISCORD_CLIENT = commands.Bot(
    command_prefix="!",
    test_guilds=config.TEST_GUILDS,
    sync_commands_debug=True
)


def find_match(channel, message):
    for alert in models.get_alerts_for_channel(channel):
        matches_filter = alert.alert_regex and re.match(
            alert.alert_regex, message, flags=re.IGNORECASE)
        matches_role = True
        if matches_filter or matches_role:
            utils.send_alert(alert.alert_url, alert.id, message)


@DISCORD_CLIENT.event
async def on_ready():
    print(f'Logged in as: {DISCORD_CLIENT.user.name}')


@DISCORD_CLIENT.event
async def on_message(message):
    # Don't trigger on our own messages
    if message.author.id == DISCORD_CLIENT.user.id:
        return

    # Search for matches to registered alerts
    if message.channel.id in models.get_registered_channels():
        find_match(channel=message.channel.id, message=message.clean_content)
