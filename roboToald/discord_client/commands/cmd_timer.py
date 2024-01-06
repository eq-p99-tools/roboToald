import asyncio
import datetime
import secrets
import time
import typing

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.db.models import timer as timer_model
from roboToald.discord_client import base

TIMER_GUILDS = config.guilds_for_command('timer')
MIN_TIMER = 5
TIMERS = {}


async def repeat_every_x_seconds(tid: str, name: str, timeout: int,
                                 repeat: bool, func: typing.Callable,
                                 first_time_int: int):
    run = True
    next_time_int = first_time_int
    while run:
        await asyncio.sleep(next_time_int - time.time())
        timer_obj = timer_model.get_timer(timer_id=tid)
        if repeat:
            next_time_int += timeout
            next_time = f"Next: <t:{next_time_int}:R>. "
            timer_obj.next_run = next_time_int
            timer_obj.store()
        else:
            next_time = ""
            run = False
            timer_obj.delete()

        timer_string = f":timer: [**{name}**] :timer: {next_time}*<ID={tid}>*"
        await func(timer_string)
    try:
        del TIMERS[tid]
    except KeyError:
        pass


@base.DISCORD_CLIENT.slash_command(
    description="Timer Registration",
    guild_ids=TIMER_GUILDS)
async def timer(inter):
    pass


@timer.sub_command(description="List Timers", name="list")
async def list_timers(
        inter: disnake.ApplicationCommandInteraction,
        all_users: bool = commands.Param(
            default=False, description="Show timers for all users?"),
        channel_only: bool = commands.Param(
            default=False, description="Show timers for this channel only?")):
    if all_users:
        timer_list = timer_model.get_timers()
    elif channel_only:
        timer_list = timer_model.get_timers_for_channel(inter.channel_id)
    else:
        timer_list = timer_model.get_timers_for_user(inter.user.id)
    timer_embeds = []
    for ut in timer_list:
        timer_embeds.append(make_timer_embed(ut))

    if timer_embeds:
        await inter.response.send_message(
            embeds=timer_embeds
        )
    else:
        await inter.response.send_message(
            "No timers found.", ephemeral=True, delete_after=60)


def make_timer_embed(timer_obj: timer_model.Timer) -> disnake.Embed:
    emb = disnake.Embed(
        title=timer_obj.name
    )
    emb.add_field(name="Duration",
                  value="{:0>8}".format(
                      str(datetime.timedelta(seconds=timer_obj.seconds))))
    if timer_obj.first_run != timer_obj.next_run:
        emb.add_field(name="First Run",
                      value=f"<t:{timer_obj.first_run}:R>")
    emb.add_field(name="Next Run",
                  value=f"<t:{timer_obj.next_run}:R>")
    emb.add_field(name="Channel",
                  value=f"<#{timer_obj.channel_id}>")
    emb.add_field(name="User",
                  value=f"<@{timer_obj.user_id}>")
    emb.add_field(name="Repeating",
                  value=f"{timer_obj.repeating}")
    emb.set_footer(text=f"Timer ID: <{timer_obj.id}>")

    return emb


async def send_no_timer_message(
        inter: disnake.ApplicationCommandInteraction,
        timer_id: str):
    await inter.response.send_message(
        f"No such timer: *{timer_id}*.", ephemeral=True, delete_after=60)


@timer.sub_command(description="Show Timer Info")
async def show(
        inter: disnake.ApplicationCommandInteraction,
        timer_id: str):
    user_timer = timer_model.get_timer(timer_id)
    if timer:
        await inter.response.send_message(embed=make_timer_embed(user_timer))
    else:
        await send_no_timer_message(inter, timer_id)


@timer.sub_command(description="Start Timer")
async def start(inter: disnake.ApplicationCommandInteraction,
                name: str,
                hours: int = commands.Param(default=0),
                minutes: int = commands.Param(default=0),
                seconds: int = commands.Param(default=0),
                delay_hours: int = commands.Param(
                    default=0,
                    description="Hours to delay before starting the timer. "
                                "Can be negative."),
                delay_minutes: int = commands.Param(
                    default=0,
                    description="Minutes to delay before starting the timer. "
                                "Can be negative."),
                delay_seconds: int = commands.Param(
                    default=0,
                    description="Seconds to delay before starting the timer. "
                                "Can be negative."),
                repeating: bool = commands.Param(
                    default=False, description="Repeat until stopped?")):
    timer_seconds = hours * 60 * 60 + minutes * 60 + seconds
    delay_seconds = delay_hours * 60 * 60 + delay_minutes * 60 + delay_seconds
    if timer_seconds < MIN_TIMER:
        await inter.response.send_message(
            f"Sorry, timers must be at least {MIN_TIMER} seconds.",
            ephemeral=True, delete_after=60)
        return
    timer_id = secrets.token_hex(4)
    while timer_id in TIMERS:
        timer_id = secrets.token_hex(4)

    first_time_int = int(time.time() + timer_seconds + delay_seconds)
    timer_db = timer_model.Timer(
        timer_id=timer_id,
        channel_id=inter.channel_id,
        user_id=inter.user.id,
        name=name,
        seconds=timer_seconds,
        first_run=first_time_int,
        next_run=first_time_int,
        guild_id=inter.guild_id,
        repeating=repeating
    )
    timer_db.store()
    TIMERS[timer_id] = asyncio.create_task(
        repeat_every_x_seconds(
            tid=timer_id,
            name=name,
            timeout=timer_seconds,
            repeat=repeating,
            func=inter.channel.send,
            first_time_int=first_time_int
        ))
    await inter.response.send_message(embed=make_timer_embed(timer_db))
    await TIMERS[timer_id]


@timer.sub_command(description="Stop Timer")
async def stop(
        inter: disnake.ApplicationCommandInteraction,
        timer_id: str):
    user_timer = timer_model.get_timer(timer_id)
    if user_timer:
        user_timer.delete()

    try:
        TIMERS[timer_id].cancel()
        del TIMERS[timer_id]
        await inter.response.send_message(
            f"Stopped timer: *<{timer_id}>*.")
    except KeyError:
        await send_no_timer_message(inter, timer_id)


# On load, set up all timers once
async def load_timers(store={}):
    if 'loaded' in store:
        return
    store['loaded'] = True

    all_timers = timer_model.get_timers()
    timer_messages = {}
    for timer_obj in all_timers:
        channel = await base.DISCORD_CLIENT.fetch_channel(timer_obj.channel_id)
        next_datetime = datetime.datetime.fromtimestamp(timer_obj.next_run)
        delay_seconds = next_datetime - datetime.datetime.now()

        if delay_seconds.total_seconds() < 0 and not timer_obj.repeating:
            timer_obj.delete()
            continue
        while delay_seconds.total_seconds() < 0:
            # Add the timer seconds until the next run is in the future
            next_datetime += datetime.timedelta(seconds=timer_obj.seconds)
            delay_seconds = next_datetime - datetime.datetime.now()

        timer_obj.next_run = int(next_datetime.timestamp())
        timer_obj.store()
        TIMERS[timer_obj.id] = asyncio.create_task(
            repeat_every_x_seconds(
                tid=timer_obj.id,
                name=timer_obj.name,
                timeout=timer_obj.seconds,
                repeat=timer_obj.repeating,
                func=channel.send,
                first_time_int=timer_obj.next_run
            ))
        asyncio.ensure_future(TIMERS[timer_obj.id])
        if timer_obj.channel_id in timer_messages:
            timer_messages[timer_obj.channel_id].append(
                make_timer_embed(timer_obj))
        else:
            timer_messages[timer_obj.channel_id] = [
                make_timer_embed(timer_obj)]
    for channel_id, messages in timer_messages.items():
        channel = await base.DISCORD_CLIENT.fetch_channel(channel_id)
        await channel.send(embeds=messages)
