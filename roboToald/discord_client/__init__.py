import asyncio
import datetime
import logging
import time

import disnake

from roboToald import asyncio_default_executor, config
from roboToald.discord_client import commands
from roboToald.discord_client.base import DISCORD_CLIENT
from roboToald.discord_dm_log_handler import install_discord_dm_handler

logger = logging.getLogger(__name__)

SUBSCRIPTION_TASK = None
RAID_TIMERS_BOARD_TASK = None
LOG_STREAM_TASKS = []
_BOT_READY = False


async def announce_subscriptions_task():
    while True:
        start = time.time()
        try:
            logger.info("Running Subscription Notifier: %s", datetime.datetime.now())
            await commands.cmd_raidtarget.announce_subscriptions()
        except Exception:
            logger.exception("Subscription notifier failed")
        end = time.time()
        await asyncio.sleep(60 - (end - start))  # Try to avoid drift


async def raid_timers_board_task():
    from roboToald.raidtargets import rt_board

    while True:
        start = time.time()
        try:
            for guild_id, settings in config.GUILD_SETTINGS.items():
                if not settings.get("raid_timers_channel_id"):
                    continue
                try:
                    await rt_board.update_board(guild_id, DISCORD_CLIENT)
                except Exception:
                    logger.exception("Raid timers board update failed for guild=%s", guild_id)
        except Exception:
            logger.exception("Raid timers board task failed")
        end = time.time()
        await asyncio.sleep(max(1, 60 - (end - start)))


@DISCORD_CLIENT.event
async def on_ready():
    global SUBSCRIPTION_TASK, RAID_TIMERS_BOARD_TASK, LOG_STREAM_TASKS, _BOT_READY

    asyncio_default_executor.install_enlarged_default_executor(
        asyncio.get_running_loop(),
        thread_name_prefix="discord-asyncio",
    )

    if _BOT_READY:
        logger.info("Discord client reconnected as: %s", DISCORD_CLIENT.user.name)
        return

    _BOT_READY = True
    logger.info("Logged in as: %s", DISCORD_CLIENT.user.name)

    await commands.cmd_timer.load_timers()
    logger.info("Loaded timers from DB.")
    await commands.cmd_ds.restore_spawn_overrides()
    logger.info("Restored DS spawn overrides from timers.")
    await commands.cmd_ds.reconcile_ds_active_roles()
    logger.info("Reconciled DS active roles.")
    await commands.cmd_ds.schedule_messages()
    logger.info("Scheduled DS messages.")
    install_discord_dm_handler(DISCORD_CLIENT, config.ERROR_DM_USER_ID)

    from roboToald.raidtargets import rt_service

    for guild_id in config.GUILD_SETTINGS:
        if config.get_raidtargets_source(guild_id) == "local":
            try:
                seeded = await asyncio.to_thread(rt_service.seed_guild_if_empty, guild_id)
                if seeded:
                    logger.info("Seeded %s raid targets for guild %s", seeded, guild_id)
            except Exception:
                logger.exception("Failed to seed raid targets for guild %s", guild_id)

    SUBSCRIPTION_TASK = asyncio.create_task(announce_subscriptions_task())
    asyncio.ensure_future(SUBSCRIPTION_TASK)
    logger.info("Started Subscription Notifier.")

    RAID_TIMERS_BOARD_TASK = asyncio.create_task(raid_timers_board_task())
    asyncio.ensure_future(RAID_TIMERS_BOARD_TASK)
    logger.info("Started Raid Timers Board.")

    from roboToald.raidtargets import rt_log_reader

    LOG_STREAM_TASKS = rt_log_reader.start_log_stream_tasks(DISCORD_CLIENT)


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
