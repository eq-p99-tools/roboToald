import asyncio
import collections
import datetime
import math
import time
from typing import Tuple

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald import constants
from roboToald.db.models import points as points_model
from roboToald.db.models import timer as timer_model
from roboToald.discord_client import base
from roboToald.discord_client.commands import cmd_timer
from roboToald import utils

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
    if last and start_time < last.time:
        await inter.send("Cannot backdate prior to the player's latest entry.",
                         ephemeral=True)
        return
    last_tod = points_model.get_last_pop_time()
    if last_tod and start_time.astimezone() < last_tod:
        await inter.send("Cannot backdate prior to the last ToD.",
                         ephemeral=True)
        return
    start_event = points_model.PointsAudit(
        user_id=player.id, guild_id=inter.guild_id, event=constants.Event.IN,
        time=start_time, active=True)
    points_model.start_event(start_event)
    discord_ent_time = int(time.mktime(start_time.timetuple()))
    backdate_message = f", backdated {backdate} minutes" if backdate > 0 else ""
    start_message = (f"<@{player.id}> entered camp at <t:{discord_ent_time}> "
                     f"(<t:{discord_ent_time}:R>{backdate_message}).")
    await inter.send(start_message,
                     allowed_mentions=disnake.AllowedMentions(users=False))


def calculate_points_for_session(
        guild_id: int, stop_time: datetime.datetime
) -> dict[int, dict[int, int]]:
    # Get all start/stop event pairs since the last pop
    event_pairs = points_model.get_event_pairs_since_last_pop(guild_id)

    ### Normalize all event times
    start_time = points_model.get_last_pop_time()
    time_at_camp = stop_time.astimezone() - start_time
    standard_minutes = math.ceil(time_at_camp.total_seconds() / 60)

    # Normalize member event windows to start_time = 0
    normalized_member_windows = {}
    for member, m_event_windows in event_pairs.items():
        normalized_member_windows[member] = []
        for start_window, stop_window in m_event_windows.items():
            norm_start = round(
                (start_window.astimezone() - start_time).total_seconds() / 60)
            norm_stop = round(
                (stop_window.astimezone() - start_time).total_seconds() / 60)
            normalized_member_windows[member].append((
                max(0, norm_start),
                min(standard_minutes, norm_stop)
            ))
    # end up with:
    # {member1: [(start1, stop1), (start2, stop2)], member2: []}

    # Normalize contested windows to start_time = 0
    contested_windows = points_model.get_competitive_windows(
        guild_id, start_time, stop_time)
    normalized_windows = []
    for start_window, stop_window in contested_windows:
        norm_start = round((start_window - start_time).total_seconds() / 60)
        norm_stop = round((stop_window - start_time).total_seconds() / 60)
        normalized_windows.append((
            max(0, norm_start),
            min(standard_minutes, norm_stop)
        ))

    points_earned_by_rate = {}
    for minute in range(standard_minutes):
        # Start with a standard value for one minute of time
        point_value = config.POINTS_PER_MINUTE

        # Check if contested
        for c_start_window, c_stop_window in normalized_windows:
            if c_start_window <= minute <= c_stop_window:
                point_value *= config.CONTESTED_MULTIPLIER
                break

        # Iterate through event pairs and find active ones
        active_players = []
        for member, m_norm_windows in normalized_member_windows.items():
            for m_start_window, m_stop_window in m_norm_windows:
                if m_start_window <= minute <= m_stop_window:
                    active_players.append(member)

        # Point value is the minute-rate divided by active members, lowest=1
        if active_players:
            point_value = max(1, point_value / len(active_players))

        # Ensure member exists and add points
        for member in active_players:
            if member not in points_earned_by_rate:
                points_earned_by_rate[member] = {}
            points_earned_by_rate[member][point_value] = (
                    1 + points_earned_by_rate[member].get(point_value, 0)
            )

    return points_earned_by_rate


def close_event(
        start_event: points_model.PointsAudit,
        stop_time: datetime.datetime) -> None:
    start_event.active = False
    stop_event = points_model.PointsAudit(
        user_id=start_event.user_id, guild_id=start_event.guild_id,
        event=constants.Event.OUT, time=stop_time, active=False,
        start_id=start_event.id)
    points_model.close_event(start_event, stop_event)


@ds.sub_command(description="Stop recording time in camp.")
async def stop(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            default=None,
            description="Member exiting camp (default: current member)."),
        backdate: int = commands.Param(
            default=None,
            ge=0,
            description="Backdate exit by <X> minutes. If already stopped, "
                        "update the last stop time.")
):
    if player is None:
        player = inter.user
    last = points_model.get_last_event(player.id, guild_id=inter.guild_id)
    stop_time = datetime.datetime.now()
    if backdate:
        stop_time -= datetime.timedelta(minutes=backdate)
    last_pop = points_model.get_last_pop_time()
    # If there is an event, it is closed, it is after the last pop,
    # and backdate is set, then update the last event's stop time
    if last and not last.active and last.time.astimezone() > last_pop and backdate is not None:
        # Update the last event to be backdated
        start_event = points_model.get_event(last.start_id)
        if stop_time < start_event.time:
            minutes_since_start = int(
                (datetime.datetime.now() - start_event.time).total_seconds() / 60)
            await inter.send(
                f"Cannot backdate to before start time ({minutes_since_start} minutes ago).",
                ephemeral=True)
            return
        last.time = stop_time
        points_model.update_event(last)
        discord_exit_time = int(time.mktime(last.time.timetuple()))
        await inter.send(f"Previous stop time for <@{player.id}> updated to"
                         f" <t:{discord_exit_time}>.",
                         allowed_mentions=disnake.AllowedMentions(users=False))
        return
    if not last or not last.active:
        await inter.send("No active event to stop.", ephemeral=True)
        return
    close_event(last, stop_time)

    discord_exit_time = int(time.mktime(stop_time.timetuple()))
    backdate_message = ""
    if backdate is not None:
        backdate_message = f", backdated {backdate} minutes"
    await inter.send(
        f"<@{player.id}> exited camp at <t:{discord_exit_time}> "
        f"(<t:{discord_exit_time}:R>{backdate_message}).",
        allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Show current camp status.")
async def status(
        inter: disnake.ApplicationCommandInteraction,
        verbose: bool = commands.Param(
            default=False,
            description="Show detailed point data.")):
    await inter.response.defer()
    active_events = points_model.get_active_events(inter.guild_id)
    last_window = points_model.get_last_event(
        user_id=0, guild_id=inter.guild_id)
    is_comp = last_window and last_window.active
    now = datetime.datetime.now().replace(second=0)

    points_for_session = calculate_points_for_session(
        guild_id=inter.guild_id, stop_time=now)
    points_per_member = sum_points_by_member(points_for_session)
    current_rate = config.POINTS_PER_MINUTE
    if is_comp:
        current_rate *= config.CONTESTED_MULTIPLIER
    # TODO: Make sure active_events can't be more than active_members below
    # and if it can, clean this up so the rate is based on active_members, or
    # so that the code below doesn't create an extra random Set for no reason
    if len(active_events) > 0:
        # Point value is the minute-rate divided by active members, lowest=1
        current_rate = max(1, current_rate / len(active_events))
    else:
        current_rate = f"0 of {current_rate}"

    message = f"Current camp status: `{'' if is_comp else 'non'}competitive` ({current_rate} SKP/min)\n"
    active_members = set()
    if active_events:
        message += "\nMembers in camp:\n"
    for event in active_events:
        active_members.add(event.user_id)
        time_spent = max(round((now - event.time).total_seconds()), 0)
        display_time = "{:0>8}".format(
            str(datetime.timedelta(seconds=time_spent)))
        if event.user_id in points_per_member:
            total_minutes = points_per_member[event.user_id][1]
            display_total = "{:0>8}".format(
                str(datetime.timedelta(minutes=total_minutes)))
        else:
            display_total = display_time
        session_points = points_per_member.get(event.user_id, (0,))[0]
        message += f"<@{event.user_id}>: {display_total} ({session_points} points"
        if verbose:
            session_rates = points_for_session.get(event.user_id, 0)
            message += f"; rates: {session_rates}"
        message += f")\n"

    # If more players were in the session, list them
    if len(set(points_per_member).difference(active_members)) > 0:
        message += "\nOther contributing members this session:\n"
        for member, member_points in points_per_member.items():
            if member not in active_members:
                total_minutes = points_per_member[member][1]
                display_total = "{:0>8}".format(
                    str(datetime.timedelta(minutes=total_minutes)))
                session_points = points_per_member[member][0]
                message += f"<@{member}>: {display_total} ({session_points} points"
                if verbose:
                    session_rates = points_for_session.get(member, 0)
                    message += f"; rates: {session_rates}"
                message += f")\n"

    await inter.send(
        message, allowed_mentions=disnake.AllowedMentions(users=False))


def sum_points_by_member(
        points_dict: dict[int, dict[float, int]]) -> dict[int, (int, int)]:
    total_points_by_member = {}
    for member, points_by_rate in points_dict.items():
        total_points = 0
        total_minutes = 0
        for rate, points in points_by_rate.items():
            total_points += rate * points
            total_minutes += points
        total_points_by_member[member] = (round(total_points), total_minutes)
    return total_points_by_member


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
            default=True,
            description="Show points for ALL users (default: true).")
):
    if player is not None:
        show_all = False
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
            member_totals.append(
                (member.points - spent, spent, member.user_id))

        sorted_totals = sorted(member_totals, key=lambda tup: tup[0])
        for current_points, spent_points, user_id in reversed(sorted_totals):
            message += (
                f"<@{user_id}>: {current_points} "
                f"(Earned {current_points + spent_points},"
                f" Spent {spent_points})\n")
        await utils.send_and_split(inter, message)
        return

    if player is None:
        player = inter.user
    earned, spent = get_point_data_for_member(player.id, inter.guild_id)
    await inter.send(
        f"<@{player.id}> has {earned - spent} points "
        f"(earned: {earned}, spent: {spent}).",
        ephemeral=True, allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Run this when DS dies to stop all tracking.")
async def tod(
        inter: disnake.ApplicationCommandInteraction,
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate DS pop by <X> minutes."),
        quake: bool = commands.Param(
            default=False,
            description="Quake?"
        )
):
    message = "DS ToD recorded"
    if backdate > 0:
        message += f" (backdated {backdate} minutes ago)"
    message += ". Stopped camp time for the following members:\n"

    stop_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    active_events = points_model.get_active_events(
        inter.guild_id, include_0=True)
    active_members = 0
    for event in active_events:
        if event.user_id == 0:
            event.active = False
            stop_event = points_model.PointsAudit(
                user_id=0, guild_id=inter.guild_id, event=constants.Event.COMP_END,
                time=stop_time, active=False, start_id=event.id)
            points_model.close_event(event, stop_event)
            continue
        close_event(event, stop_time)
        message += f"<@{event.user_id}> stopped.\n"
        active_members += 1

    if active_members < 1:
        message = "DS ToD recorded"
        if backdate > 0:
            message += f" (backdated {backdate} minutes)"
        message += ". No members active.\n"

    all_points_for_session = calculate_points_for_session(
        guild_id=inter.guild_id, stop_time=stop_time)

    if all_points_for_session:
        message += "\nPoints earned in this session:\n"

    summed_points = sum_points_by_member(all_points_for_session)
    for member, session_points in summed_points.items():
        points_earned = points_model.PointsEarned(
            member, inter.guild_id, session_points[0], stop_time)
        points_earned.store()
        message += f"<@{member}>: {session_points[0]}\n"

    # Grant adjustment to active members for quake bonus
    if quake and active_members > 0:
        message += f"\nQuake Bonus of {config.QUAKE_BONUS} granted to active members: "
        for event in active_events:
            if event.user_id == 0:
                continue
            bonus_points = points_model.PointsEarned(
                user_id=event.user_id, guild_id=inter.guild_id,
                points=config.QUAKE_BONUS, time=stop_time,
                notes='Automatic Quake Bonus', adjustor=inter.user.id)
            bonus_points.store()
            message += f"<@{event.user_id}>, "
        message = message[:-2] + ".\n"

    await utils.send_and_split(inter, message)

    recent_ds = None
    time_since_pop = stop_time.astimezone() - points_model.get_last_pop_time()
    if time_since_pop < datetime.timedelta(minutes=5):
        recent_ds = abs(round(time_since_pop.total_seconds() / 60, 1))

    if recent_ds and active_members < 1:
        # There's already a POP recorded within 5 min, likely duplicate
        message = (f"Someone just ran the ToD command {recent_ds} "
                   f"minutes ago. Deleting this interaction.")
        await inter.edit_original_response(content=message)
        await inter.delete_original_response(delay=5)
        return

    # Record the POP event
    pop_event = points_model.PointsAudit(
        user_id=0, guild_id=inter.guild_id, event=constants.Event.POP,
        time=stop_time, active=False)
    points_model.start_event(pop_event)

    # Restart the ToD Timer
    timer_channel_id = config.GUILD_SETTINGS.get(inter.guild_id, {}).get('ds_tod_channel')
    if not timer_channel_id:
        return
    timers = timer_model.get_timers_for_channel(timer_channel_id)
    timer_channel = inter.guild.get_channel(timer_channel_id)
    if timers:
        for timer in timers:
            await cmd_timer._stop(timer.id, timer_channel.send)

    await cmd_timer._start(
        timer_channel.send,
        timer_channel,
        base.DISCORD_CLIENT.user.id,
        inter.guild_id,
        name="DS Spawn",
        hours=24,
        minutes=1,
        delay_minutes=backdate * -1 - 1,
        repeating=True)


@ds.sub_command(description="Player has won an urn with SKP.")
async def urn(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            description="Member who won the urn."),
        price: int = commands.Param(
            gt=0,
            description="Number of SKP spent."),
        backdate: int = commands.Param(
            default=0,
            ge=0,
            description="Backdate purchase by <X> minutes.")
):
    user_points_earned, user_points_spent = get_point_data_for_member(
        player.id, inter.guild_id)
    if user_points_earned - user_points_spent < price:
        await inter.send("Not enough points for purchase.", ephemeral=True)
        return
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


@ds.sub_command(description="Adjust points for a member.")
async def adjust(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            description="Member to adjust points."),
        points: int = commands.Param(
            default=0,
            description="Number of points to adjust (relative +/-)."),
        notes: str = commands.Param(
            default=None,
            description="Optional notes / reason for adjustment.")):
    points_earned = points_model.PointsEarned(
        user_id=player.id, guild_id=inter.guild_id,
        points=points, time=datetime.datetime.now(),
        notes=notes, adjustor=inter.user.id)

    points_earned.store()
    message = f"Adjustment applied: {points} SKP for <@{player.id}>"
    if notes:
        message += f" with notes: `{notes}`"
    message += "."
    await inter.send(
        message, allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Show audit logs for a member's DS events.")
async def audit(
        inter: disnake.ApplicationCommandInteraction,
        player: disnake.Member = commands.Param(
            description="Member to audit.")):
    # Fetch all the audit events for the player
    events = points_model.get_events_for_member(player.id, inter.guild_id)
    # Also fetch Earned/Spent entries
    points_earned = points_model.get_points_earned_by_member(
        player.id, inter.guild_id)
    points_spent = points_model.get_points_spent_by_member(
        player.id, inter.guild_id)

    if events or points_earned or points_spent:
        message = f"Audit events for <@{player.id}>:\n\n"
    else:
        message = f"No events found for <@{player.id}>."

    # Pair up events
    event_pairs = points_model.get_event_pairs(events)

    for event_start, event_end in event_pairs.items():
        # Add each audit event to the response
        if event_end == datetime.datetime.max:
            event_end = datetime.datetime.now()
        minutes = round((event_end - event_start).total_seconds() / 60)
        message += (
            f"<t:{int(event_start.timestamp())}> -> "
            f"<t:{int(event_end.timestamp())}> ({minutes} minutes)\n"
        )

    earned_spent_messages = collections.OrderedDict()
    for earned in points_earned:
        # Add all the EARNED events to the ordered dict by time
        em = f"**Earned**: {earned.points} at <t:{int(earned.time.timestamp())}>"
        if earned.adjustor:
            em += f" (by <@{earned.adjustor}>)"
        if earned.notes:
            em += f". **Notes:** `{earned.notes}`"
        em += ".\n"
        earned_spent_messages[int(earned.time.timestamp())] = em

    for spent in points_spent:
        # Add all the SPENT events to the ordered dict by time
        sm = f"**Spent**: {spent.points} at <t:{int(spent.time.timestamp())}>.\n"
        earned_spent_messages[int(spent.time.timestamp())] = sm

    if earned_spent_messages and message.count('\n') > 2:
        # Add an extra newline to split up audit events and point records
        message += "\n"

    # Add the ordered records to the response
    for esm in earned_spent_messages.values():
        message += esm

    # Messages can only be 2000 chars so break it up if necessary
    if len(message) < 2000:
        dm = await inter.user.send(message)
    else:
        messages = utils.split_message(message)

        dm = None
        for one_message in messages:
            one_dm = await inter.user.send(one_message)
            if not dm:
                dm = one_dm

    await inter.send(
        content=f"Sent audit data for <@{player.id}> via DM: {dm.jump_url}",
        ephemeral=True
    )


async def schedule_messages():
    for guild_id in DS_GUILDS:
        channel_id = config.GUILD_SETTINGS.get(guild_id, {}).get('ds_schedule_channel')
        if channel_id:
            channel = await base.DISCORD_CLIENT.fetch_channel(channel_id)
            if not channel:
                print(f"Could not find channel with ID {channel_id} for guild {guild_id}")
                return

            task = asyncio.create_task(_schedule_message_repeating(channel))
            asyncio.ensure_future(task)


async def _schedule_message_repeating(channel: disnake.TextChannel):
    # Get all messages from today
    today = datetime.datetime.now().astimezone(
        constants.TIMEZONES['ET']).replace(
        hour=0, minute=0, second=0, microsecond=0)
    existing_message = None
    async for message in channel.history(after=today):
        if message.author.id == base.DISCORD_CLIENT.user.id:
            existing_message = message
            break

    while True:
        # If no existing message today, send one
        if not existing_message:
            await _schedule_message(channel)
            existing_message = True

        # We should now be past first run, so calculate noon tomorrow
        now = datetime.datetime.now().astimezone(constants.TIMEZONES['ET'])
        tomorrow = now + datetime.timedelta(days=1)
        noon_tomorrow = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

        # Sleep until the next noon
        await asyncio.sleep((noon_tomorrow - now).total_seconds())
        await _schedule_message(channel)


async def _schedule_message(channel: disnake.TextChannel):
    # Get the current time
    current_datetime = datetime.datetime.now().astimezone(constants.TIMEZONES['ET'])
    # Get the current day of the week
    day_of_week = current_datetime.strftime("%A")
    # Get the current month
    month = current_datetime.strftime("%B")
    # Get the current date, ie "18th" or "2nd"
    date = int(current_datetime.strftime("%d"))
    tomorrow = current_datetime + datetime.timedelta(days=1)
    tomorrow_date = int(tomorrow.strftime("%d"))

    def get_ordinal(i):
        # Adapted from https://gist.github.com/FlantasticDan/3eb192fac85ab5efa2002fb7165e4f35
        if 10 <= i % 100 <= 20:
            return 'th'
        else:
            return {1: 'st', 2: 'nd', 3: 'rd'}.get(i % 10, 'th')

    title_dates = f"{day_of_week} {month} {date}{get_ordinal(date)} -> {tomorrow_date}{get_ordinal(tomorrow_date)}"
    midnight = current_datetime.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    midnight_timestamp = int(midnight.timestamp())
    message = f"""**{title_dates} - Late Shift Availability**
We usually have thinner numbers during the night in Eastern Time.
If you're able to commit to those hours for this spawn cycle, please mark the appropriate emoji here.
You may select multiple emoji, one for each hour you're available. 

Please only add an emoji if you're definitely going to be there.

🇦 <t:{midnight_timestamp}:f> - <t:{midnight_timestamp + 3600 * 1}:t>
🇧 <t:{midnight_timestamp + 3600 * 1}:f> - <t:{midnight_timestamp + 3600 * 2}:t>
🇨 <t:{midnight_timestamp + 3600 * 2}:f> - <t:{midnight_timestamp + 3600 * 3}:t>
🇩 <t:{midnight_timestamp + 3600 * 3}:f> - <t:{midnight_timestamp + 3600 * 4}:t>
🇪 <t:{midnight_timestamp + 3600 * 4}:f> - <t:{midnight_timestamp + 3600 * 5}:t>
🇫 <t:{midnight_timestamp + 3600 * 5}:f> - <t:{midnight_timestamp + 3600 * 6}:t>
🇬 <t:{midnight_timestamp + 3600 * 6}:f> - <t:{midnight_timestamp + 3600 * 7}:t>
🇭 <t:{midnight_timestamp + 3600 * 7}:f> - <t:{midnight_timestamp + 3600 * 8}:t>
🇮 <t:{midnight_timestamp + 3600 * 8}:f> - <t:{midnight_timestamp + 3600 * 9}:t>
@everyone"""

    message_object = await channel.send(
        message, allowed_mentions=disnake.AllowedMentions(everyone=True))
    for emoji in "🇦🇧🇨🇩🇪🇫🇬🇭🇮":
        await message_object.add_reaction(emoji)
