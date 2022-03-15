import discord

import config
import squadcast

DISCORD_CLIENT = discord.Client()


@DISCORD_CLIENT.event
async def on_ready():
    print(f'Logged in as: {DISCORD_CLIENT.user.name}')


@DISCORD_CLIENT.event
async def on_message(message):
    if message.channel.id in config.BATPHONE_CHANNELS and message.mention_everyone:
        print(f"Sending alert: {message.clean_content}")
        squadcast.send_alert("BATPHONE", message.clean_content)
    elif "!test" in message.content and DISCORD_CLIENT.user.id in message.raw_mentions:
        print(f"Logging test alert: {message.clean_content}")
        # squadcast.send_alert("TEST ALERT", message.clean_content)


if __name__ == '__main__':
    DISCORD_CLIENT.run(config.DISCORD_TOKEN)
