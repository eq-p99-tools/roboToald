import discord
import requests

import config
# import gmail

DISCORD_CLIENT = discord.Client()


def send_alert(title, message):
    requests.post(config.ALERT_WEBHOOK, json={
        "message": title,
        "description": message,
        "status": "trigger",
    })


@DISCORD_CLIENT.event
async def on_ready():
    print(f'Logged in as: {DISCORD_CLIENT.user.name}')


@DISCORD_CLIENT.event
async def on_message(message):
    if message.channel.id in config.BATPHONE_CHANNELS and message.mention_everyone:
        print(f"Sending alert: {message.content}")
        send_alert("BATPHONE", message.content)
    elif "!test" in message.content and DISCORD_CLIENT.user.id in message.raw_mentions:
        print(f"Logging test alert: {message.content}")
        # gmail.send_message("TEST ALERT", message.content)
        send_alert("TEST ALERT", message.content)


if __name__ == '__main__':
    DISCORD_CLIENT.run(config.DISCORD_TOKEN)
