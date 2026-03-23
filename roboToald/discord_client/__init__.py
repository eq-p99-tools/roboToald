import asyncio
import time

import disnake

from roboToald.discord_client import commands
from roboToald.discord_client.base import DISCORD_CLIENT

SUBSCRIPTION_TASK = None


async def announce_subscriptions_task():
    while True:
        start = time.time()
        try:
            # print(
            #     f"Running Subscription Notifier: {datetime.datetime.now()}"
            # )
            await commands.cmd_raidtarget.announce_subscriptions()
        except Exception as e:
            print(e)
        end = time.time()
        await asyncio.sleep(60 - (end - start))  # Try to avoid drift


@DISCORD_CLIENT.event
async def on_ready():
    global SUBSCRIPTION_TASK

    print(f"Logged in as: {DISCORD_CLIENT.user.name}")
    await commands.cmd_timer.load_timers()
    print("Loaded timers from DB.")
    await commands.cmd_ds.restore_spawn_overrides()
    print("Restored DS spawn overrides from timers.")
    await commands.cmd_ds.schedule_messages()
    print("Scheduled DS messages.")
    SUBSCRIPTION_TASK = asyncio.create_task(announce_subscriptions_task())
    asyncio.ensure_future(SUBSCRIPTION_TASK)
    print("Started Subscription Notifier.")


@DISCORD_CLIENT.listen("on_button_click")
async def help_listener(inter: disnake.MessageInteraction):
    # Match by prefix so custom_ids can embed metadata
    # (e.g. "unsubscribe:Target:guild_id").
    # Longest keys first so a prefix cannot steal a longer match.
    sorted_listeners = sorted(
        commands.BUTTON_LISTENERS.items(),
        key=lambda kv: -len(kv[0]),
    )
    for key, handler in sorted_listeners:
        if inter.component.custom_id.startswith(key):
            await handler(inter)
            return
