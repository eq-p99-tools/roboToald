import asyncio
import datetime
import time

import disnake

from roboToald.discord_client import commands
from roboToald.discord_client.base import DISCORD_CLIENT

SUBSCRIPTION_TASK = None


async def announce_subscriptions_task():
    while True:
        start = time.time()
        try:
            # print(f"Running Subscription Notifier: {datetime.datetime.now()}")
            await commands.cmd_raidtarget.announce_subscriptions()
        except Exception as e:
            print(e)
        end = time.time()
        await asyncio.sleep(60 - (end - start))  # Try to avoid drift


@DISCORD_CLIENT.event
async def on_ready():
    global SUBSCRIPTION_TASK

    print(f'Logged in as: {DISCORD_CLIENT.user.name}')
    await commands.cmd_timer.load_timers()
    print("Loaded timers from DB.")
    SUBSCRIPTION_TASK = asyncio.create_task(announce_subscriptions_task())
    asyncio.ensure_future(SUBSCRIPTION_TASK)
    print("Started Subscription Notifier.")


@DISCORD_CLIENT.listen("on_button_click")
async def help_listener(inter: disnake.MessageInteraction):
    if inter.component.custom_id not in commands.BUTTON_LISTENERS:
        # We filter out any other button presses except
        # the components we wish to process.
        return

    await commands.BUTTON_LISTENERS[inter.component.custom_id](inter)
