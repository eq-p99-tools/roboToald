import asyncio
import secrets
import time

from disnake.ext import commands

from roboToald.discord_client import base

MIN_TIMER = 5
TIMERS = {}


async def repeat_every_x_seconds(tid, name, timeout, repeat, func, delay=0):
    run = True
    while run:
        await asyncio.sleep(timeout + delay)
        delay = 0
        next_time = (
            f"Next: <t:{int(time.time() + timeout)}:R>. " if repeat else "")
        timer_string = f":timer: [**{name}**] :timer: {next_time}<ID={tid}>"
        await func(timer_string)
        if not repeat:
            run = False
    try:
        del TIMERS[tid]
    except KeyError:
        pass


@base.DISCORD_CLIENT.slash_command(description="Timer Registration")
async def timer(inter):
    pass


@timer.sub_command(description="Start Timer")
async def start(inter,
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
            ephemeral=True)
        return
    timer_id = secrets.token_hex(4)
    while timer_id in TIMERS:
        timer_id = secrets.token_hex(4)
    TIMERS[timer_id] = asyncio.create_task(
        repeat_every_x_seconds(
            tid=timer_id,
            name=name,
            timeout=timer_seconds,
            repeat=repeating,
            func=inter.channel.send,
            delay=delay_seconds
        ))
    first_time = f"<t:{int(time.time() + timer_seconds + delay_seconds)}:R>"
    await inter.response.send_message(
        f"Starting timer: [**{name}**] for {timer_seconds} seconds "
        f"(repeating: {'yes' if repeating else 'no'}, "
        f"delay: {delay_seconds} seconds). First run: {first_time}. "
        f"*<ID={timer_id}>*")
    await TIMERS[timer_id]


@timer.sub_command(description="Stop Timer")
async def stop(inter, timer_id: str):
    try:
        TIMERS[timer_id].cancel()
        del TIMERS[timer_id]
        await inter.response.send_message(
            f"Stopped timer: *{timer_id}*.")
    except KeyError:
        await inter.response.send_message(
            f"No such timer: *{timer_id}*.", ephemeral=True)
