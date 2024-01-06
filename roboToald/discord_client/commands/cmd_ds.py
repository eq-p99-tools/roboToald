"""
/dscontest on/off - Toggle the status of the DS camp from contested to uncontested
/dsstart $playername - This player has begun a DS camp, start tracking SKP
/dsend  $playername - This player has ended a DS camp
/dslist - Show current players on the DS camp
/dspointlist - Show current players SKP balance
/dsbid  $playername $amount - This player has purchased an urn, deduct the value from their wallet
"""
import datetime
import time
from typing import Tuple

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald import constants
from roboToald.db.models import points as points_model
from roboToald.discord_client import base

DS_GUILDS = config.guilds_for_command('ds')
CONTESTED = False


@base.DISCORD_CLIENT.slash_command(
    description="DS Camp Time Auditing",
    guild_ids=DS_GUILDS)
async def ds(inter: disnake.ApplicationCommandInteraction):
    pass


@ds.sub_command(description="Set camp status as competitive or not.")
async def competitive(
        inter: disnake.ApplicationCommandInteraction,
        contested: bool = commands.Param(
            description="Is the camp contested?"),
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate entry by <X> minutes.")
):
    last = points_model.get_last_event(0, inter.guild_id)
    event_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    if contested:
        if last and last.active:
            await inter.send("Camp already competitive.", ephemeral=True)
            return
        start_event = points_model.PointsAudit(
            user_id=0, guild_id=inter.guild_id, event=constants.Event.COMP_START,
            time=event_time, active=True)
        points_model.start_event(start_event)
    else:
        if not last or not last.active:
            await inter.send("Camp is already noncompetitive.", ephemeral=True)
            return
        last.active = False
        stop_event = points_model.PointsAudit(
            user_id=0, guild_id=inter.guild_id, event=constants.Event.COMP_END,
            time=event_time, active=False, start_id=last.id)
        points_model.close_event(last, stop_event)

    discord_time = int(time.mktime(event_time.timetuple()))
    await inter.send(f"`Competitive -> {contested}` at <t:{discord_time}>.")


@ds.sub_command(description="Start recording time in camp.")
async def start(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            default=None,
            description="Member entering camp (default: current member)."),
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate entry by <X> minutes.")
):
    if player is None:
        player = inter.user
    last = points_model.get_last_event(player.id, guild_id=inter.guild_id)
    if last and last.active:
        await inter.send("Player already active at camp.", ephemeral=True)
        return
    start_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    start_event = points_model.PointsAudit(
        user_id=player.id, guild_id=inter.guild_id, event=constants.Event.IN,
        time=start_time, active=True)
    points_model.start_event(start_event)
    discord_ent_time = int(time.mktime(start_time.timetuple()))
    await inter.send(f"<@{player.id}> entered camp at <t:{discord_ent_time}>.",
                     allowed_mentions=disnake.AllowedMentions(users=False))


def close_event_and_record_points(
        start_event: points_model.PointsAudit,
        stop_time: datetime.datetime) -> Tuple[int, int, int]:
    start_time = start_event.time

    start_event.active = False
    stop_event = points_model.PointsAudit(
        user_id=start_event.user_id, guild_id=start_event.guild_id,
        event=constants.Event.OUT, time=stop_time, active=False,
        start_id=start_event.id)

    # Calculate points!
    time_at_camp = stop_time - start_time
    standard_minutes = round(time_at_camp.total_seconds() / 60)

    contested_minutes = 0
    windows = points_model.get_competitive_windows(
        start_event.guild_id, start_time, stop_time)
    for start_window, stop_window in windows:
        delta = datetime.timedelta(seconds=0)

        # If the contested time started before this session, what was overlap?
        if start_window < start_time and stop_window < stop_time:
            delta = stop_window - start_time

        # Was the contested time entirely within this session?
        elif start_window > start_time and stop_window < stop_time:
            delta = stop_window - start_window

        # If the contested time ended after this session, what was overlap?
        elif start_window > start_time and stop_window > stop_time:
            delta = stop_time - start_window

        # Window is outside our time range entirely
        else:
            continue

        contested_minutes += round(delta.total_seconds() / 60)

    total_points = standard_minutes + contested_minutes * 2
    points_earned = points_model.PointsEarned(
        user_id=start_event.user_id, guild_id=start_event.guild_id,
        points=total_points, time=stop_time)

    points_earned.store()
    points_model.close_event(start_event, stop_event)

    return total_points, standard_minutes, contested_minutes


@ds.sub_command(description="Stop recording time in camp.")
async def stop(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            default=None,
            description="Member exiting camp (default: current member)."),
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate exit by <X> minutes.")
):
    if player is None:
        player = inter.user
    last = points_model.get_last_event(player.id, guild_id=inter.guild_id)
    if not last or not last.active:
        await inter.send("No active event to stop.", ephemeral=True)
        return
    stop_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)

    total_points, standard_minutes, contested_minutes = (
        close_event_and_record_points(last, stop_time))

    discord_exit_time = int(time.mktime(stop_time.timetuple()))
    await inter.send(
        f"<@{player.id}> exited camp at <t:{discord_exit_time}>. "
        f"Points earned: {total_points} "
        f"(total minutes: {standard_minutes},"
        f" contested minutes: {contested_minutes}).",
        allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Show current camp status.")
async def status(inter: disnake.ApplicationCommandInteraction):
    active_events = points_model.get_active_events(inter.guild_id)
    last_window = points_model.get_last_event(
        user_id=0, guild_id=inter.guild_id)
    is_comp = last_window and last_window.active
    now = datetime.datetime.now()

    message = f"Current camp status: `{'' if is_comp else 'non'}competitive`\n"
    if active_events:
        message += "Players present: "
    for event in active_events:
        time_spent = (now - event.time).total_seconds() / 60
        message += f"<@{event.user_id}> ({round(time_spent)} minutes), "
    message = message.rstrip(", ")

    await inter.send(
        message, allowed_mentions=disnake.AllowedMentions(users=False))


def get_point_data_for_member(user_id: int, guild_id: int) -> Tuple[int, int]:
    earned_events = points_model.get_points_earned_by_member(
        user_id, guild_id)
    spent_events = points_model.get_points_spent_by_member(
        user_id, guild_id)
    earned, spent = 0, 0
    for ee in earned_events:
        earned += ee.points
    for se in spent_events:
        spent += se.points
    return earned, spent


@ds.sub_command(description="Show point balance for one or all user(s).")
async def points(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            default=None,
            description="Member for balance check (default: current member)."),
        show_all: bool = commands.Param(
            default=False,
            description="Show points for ALL users.")
):
    if show_all:
        message = "Point Balances:\n"
        earned_points = points_model.get_points_earned(inter.guild_id)
        member_totals = []
        for member in earned_points:
            spent_events = points_model.get_points_spent_by_member(
                member.user_id, inter.guild_id)
            spent = 0
            for se in spent_events:
                spent += se.points
            member_totals.append((member.points - spent, member.user_id))

        sorted_totals = sorted(member_totals, key=lambda tup: tup[0])
        for total_points, user_id in reversed(sorted_totals):
            message += f"<@{user_id}>: {total_points}\n"
        await inter.send(
            message, allowed_mentions=disnake.AllowedMentions(users=False))
        return

    if player is None:
        player = inter.user
    earned, spent = get_point_data_for_member(player.id, inter.guild_id)
    await inter.send(
        f"<@{player.id}> has {earned - spent} points "
        f"(earned: {earned}, spent: {spent}).",
        ephemeral=True, allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Run this when DS pops to stop all tracking.")
async def pop(
        inter: disnake.ApplicationCommandInteraction,
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate DS pop by <X> minutes.")
):
    message = "DS Pop recorded. Stopped camp time for the following members:\n"

    stop_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    active_events = points_model.get_active_events(
        inter.guild_id, include_0=True)
    for event in active_events:
        if event.user_id == 0:
            event.active = False
            stop_event = points_model.PointsAudit(
                user_id=0, guild_id=inter.guild_id, event=constants.Event.COMP_END,
                time=stop_time, active=False, start_id=event.id)
            points_model.close_event(event, stop_event)
            continue
        total_points, standard_minutes, contested_minutes = (
            close_event_and_record_points(event, stop_time))
        message += (f"<@{event.user_id}> "
                    f"Points earned: {total_points} "
                    f"(total minutes: {standard_minutes},"
                    f" contested minutes: {contested_minutes}).\n")

    await inter.send(
        message, allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Player has won an urn with SKP.")
async def urn(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            description="Member for balance check (default: current member)."),
        price: int = commands.Param(
            gt=0,
            description="Number of SKP spent."),
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate purchase by <X> minutes.")
):
    buy_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    purchase = points_model.PointsSpent(
        user_id=player.id, guild_id=inter.guild_id, points=price, time=buy_time
    )
    purchase.store()
    earned, spent = get_point_data_for_member(player.id, inter.guild_id)
    await inter.send(
        f"<@{player.id}> won an urn for {price} SKP! "
        f"They have {earned - spent} SKP remaining.",
        allowed_mentions=disnake.AllowedMentions(users=False))
