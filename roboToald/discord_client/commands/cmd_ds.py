import asyncio
import collections
import datetime
import logging
import math
import time
from typing import Tuple

import disnake
from dateutil import parser
from disnake.ext import commands

from roboToald import config
from roboToald import constants
from roboToald.db.models import points as points_model
from roboToald.db.models import timer as timer_model
from roboToald.discord_client import base
from roboToald.discord_client.commands import cmd_timer
from roboToald import utils

logger = logging.getLogger(__name__)

DS_GUILDS = config.guilds_for_command("ds")

# Per-guild override for the effective last-POP time. When set, point ramp
# calculations use this instead of the real POP event from the database.
# Cleared when /ds tod records a real POP. Restored on startup from the
# DS Spawn timer's first_run field.
SPAWN_OVERRIDE: dict[int, datetime.datetime] = {}


def get_effective_pop_time(guild_id: int) -> datetime.datetime:
    if guild_id in SPAWN_OVERRIDE:
        return SPAWN_OVERRIDE[guild_id]
    return points_model.get_last_pop_time()


async def rectify_ds_active_role(guild: disnake.Guild) -> None:
    """Silently add/remove ds_active_role based on rolling points_earned.

    Enabled only when ``ds_active_role`` is set and ``ds_active_role_threshold`` > 0.
    Uses earned ledger only (urn spends in points_spent do not count). Failures are
    logged and never raised to the caller.
    """
    settings = config.GUILD_SETTINGS.get(guild.id, {})
    role_id = settings.get("ds_active_role") or 0
    threshold = settings.get("ds_active_role_threshold") or 0
    days = settings.get("ds_active_role_days") or 14
    if role_id <= 0 or threshold <= 0:
        return

    role = guild.get_role(role_id)
    if role is None:
        logger.warning("ds_active_role %s not found in guild %s", role_id, guild.id)
        return

    try:
        rolling = points_model.get_rolling_points_earned(guild.id, days=days)
    except Exception:
        logger.exception("Failed to load rolling points for guild %s", guild.id)
        return

    candidate_ids = set(rolling.keys()) | {member.id for member in role.members}
    for user_id in candidate_ids:
        member = guild.get_member(user_id)
        if member is None:
            continue
        earned = rolling.get(user_id, 0)
        has_role = role in member.roles
        try:
            if earned >= threshold and not has_role:
                await member.add_roles(role, reason="DS active role: rolling SKP threshold met")
            elif earned < threshold and has_role:
                await member.remove_roles(role, reason="DS active role: rolling SKP below threshold")
        except disnake.Forbidden:
            logger.warning(
                "Missing permission to manage ds_active_role %s for member %s in guild %s",
                role_id,
                user_id,
                guild.id,
            )
        except Exception:
            logger.exception(
                "Failed to update ds_active_role for member %s in guild %s",
                user_id,
                guild.id,
            )


async def reconcile_ds_active_roles() -> None:
    """Rectify ds_active_role membership for all DS-enabled guilds (e.g. on startup)."""
    for guild_id in DS_GUILDS:
        guild = base.DISCORD_CLIENT.get_guild(guild_id)
        if guild is None:
            logger.warning("DS guild %s not available for active role reconcile", guild_id)
            continue
        await rectify_ds_active_role(guild)


async def restore_spawn_overrides():
    """Derive SPAWN_OVERRIDE from persisted DS Spawn timers on startup."""
    for guild_id in DS_GUILDS:
        timer_channel_id = config.GUILD_SETTINGS.get(guild_id, {}).get("ds_tod_channel")
        if not timer_channel_id:
            continue
        timers = timer_model.get_timers_for_channel(timer_channel_id)
        for t in timers:
            if t.name != "DS Spawn":
                continue
            implied_pop = datetime.datetime.fromtimestamp(t.first_run - 86400).astimezone()
            real_pop = points_model.get_last_pop_time()
            if abs((implied_pop - real_pop).total_seconds()) > 300:
                SPAWN_OVERRIDE[guild_id] = implied_pop
            break


def is_ds_tod_channel(guild_id: int, channel_id: int) -> bool:
    """True if ``channel_id`` may run ``/ds tod`` (any channel when unset)."""
    tod_channel_id = config.GUILD_SETTINGS.get(guild_id, {}).get("ds_tod_channel") or 0
    return not tod_channel_id or channel_id == tod_channel_id


# Ask for quake confirmation when expected spawn is still this far away (default;
# override per guild with ds_tod_quake_confirm_minutes).
TOD_QUAKE_CONFIRM_MINUTES_DEFAULT = 60


def time_until_expected_spawn(guild_id: int, now: datetime.datetime | None = None) -> datetime.timedelta:
    """Remaining time until the next expected DS spawn (24h after effective pop)."""
    if now is None:
        now = datetime.datetime.now().astimezone()
    elif now.tzinfo is None:
        now = now.astimezone()
    expected_spawn = get_effective_pop_time(guild_id) + datetime.timedelta(hours=24)
    return expected_spawn - now


def quake_confirm_threshold(guild_id: int) -> datetime.timedelta:
    """How early a ToD must be before we prompt for quake confirmation."""
    minutes = config.GUILD_SETTINGS.get(guild_id, {}).get("ds_tod_quake_confirm_minutes")
    if minutes is None:
        minutes = TOD_QUAKE_CONFIRM_MINUTES_DEFAULT
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = TOD_QUAKE_CONFIRM_MINUTES_DEFAULT
    return datetime.timedelta(minutes=max(0, minutes))


def should_confirm_quake(guild_id: int, is_quake: bool, now: datetime.datetime | None = None) -> bool:
    """True when ToD looks early and the caller did not already mark it a quake."""
    if is_quake:
        return False
    threshold = quake_confirm_threshold(guild_id)
    if threshold <= datetime.timedelta(0):
        return False
    return time_until_expected_spawn(guild_id, now) > threshold


def recent_pop_minutes(now: datetime.datetime | None = None) -> float | None:
    """Minutes since last POP if within the 5-minute duplicate window, else None."""
    if now is None:
        now = datetime.datetime.now()
    time_since_pop = now.astimezone() - points_model.get_last_pop_time()
    if time_since_pop < datetime.timedelta(minutes=5):
        return abs(round(time_since_pop.total_seconds() / 60, 1))
    return None


class TodQuakeConfirmView(disnake.ui.View):
    """Ephemeral Yes/No prompt when /ds tod is run more than an hour before spawn."""

    def __init__(self, *, invoker_id: int, timeout_seconds: float = 120.0):
        super().__init__(timeout=timeout_seconds)
        self.invoker_id = invoker_id
        self._resolved = False
        self.message: disnake.Message | None = None

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.user.id != self.invoker_id:
            await inter.response.send_message(
                "This confirmation is for someone else. Run `/ds tod` yourself.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self._resolved or self.message is None:
            return
        for child in self.children:
            if isinstance(child, disnake.ui.Button):
                child.disabled = True
        try:
            await self.message.edit(
                content="⌛ ToD cancelled (confirmation timed out). Re-run `/ds tod` if DS is down.",
                view=self,
            )
        except Exception:
            pass

    def _disable_all(self) -> None:
        for child in self.children:
            if isinstance(child, disnake.ui.Button):
                child.disabled = True

    async def _resolve(self, inter: disnake.MessageInteraction, is_quake: bool) -> None:
        self._resolved = True
        self.stop()
        self._disable_all()
        label = "quake" if is_quake else "not a quake"
        await inter.response.edit_message(content=f"Recording ToD ({label})…", view=self)
        await _execute_ds_tod(inter, is_quake=is_quake, via_channel=True)

    @disnake.ui.button(label="Yes, quake", style=disnake.ButtonStyle.danger)
    async def confirm_quake(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._resolve(inter, is_quake=True)

    @disnake.ui.button(label="No, not a quake", style=disnake.ButtonStyle.secondary)
    async def decline_quake(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        await self._resolve(inter, is_quake=False)


async def _publish_tod_result(inter, message: str, *, via_channel: bool) -> None:
    allowed = disnake.AllowedMentions(users=False)
    if via_channel:
        chunks = utils.split_message(message) if len(message) >= 2000 else [message]
        for chunk in chunks:
            await inter.channel.send(content=chunk, allowed_mentions=allowed)
    else:
        await utils.send_and_split(inter, message)


async def _execute_ds_tod(inter, is_quake: bool, *, via_channel: bool = False) -> None:
    """Record ToD, award points, restart spawn timer. Shared by /ds tod and confirm buttons."""
    now_time = datetime.datetime.now()
    stop_time = now_time

    recent = recent_pop_minutes(now_time)
    if recent is not None:
        message = (
            f"Someone just ran the ToD command {recent} "
            f"minutes ago. Please try again after 5 minutes."
        )
        if via_channel:
            await inter.followup.send(message, ephemeral=True)
        else:
            await inter.send(message, ephemeral=True)
        return

    message = "DS ToD recorded. Stopped camp time for the following members:\n"

    active_events = points_model.get_active_events(inter.guild_id)
    active_members = 0
    for event in active_events:
        close_event(event, stop_time)
        message += f"<@{event.user_id}>\n"
        active_members += 1

    if active_members < 1:
        message = "DS ToD recorded. No members active.\n"

    all_points_for_session = calculate_points_for_session(guild_id=inter.guild_id, stop_time=stop_time)

    if all_points_for_session:
        message += "\nPoints earned in this session:\n"

    summed_points = sum_points_by_member(all_points_for_session)
    for member, session_points in summed_points.items():
        points_earned = points_model.PointsEarned(member, inter.guild_id, session_points[0], stop_time)
        points_earned.store()
        message += f"<@{member}>: {session_points[0]}\n"

    if is_quake and active_members > 0:
        message += f"\nQuake Bonus of {config.QUAKE_BONUS} granted to active members: "
        for event in active_events:
            bonus_points = points_model.PointsEarned(
                user_id=event.user_id,
                guild_id=inter.guild_id,
                points=config.QUAKE_BONUS,
                time=stop_time,
                notes="Automatic Quake Bonus",
                adjustor=inter.user.id,
            )
            bonus_points.store()
            message += f"<@{event.user_id}>, "
        message = message[:-2] + ".\n"

    SPAWN_OVERRIDE.pop(inter.guild_id, None)
    pop_event = points_model.PointsAudit(
        user_id=0, guild_id=inter.guild_id, event=constants.Event.POP, time=stop_time, active=False
    )
    points_model.start_event(pop_event)

    await _publish_tod_result(inter, message, via_channel=via_channel)

    await rectify_ds_active_role(inter.guild)

    timer_channel_id = config.GUILD_SETTINGS.get(inter.guild_id, {}).get("ds_tod_channel")
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
        delay_minutes=-1,
        repeating=True,
    )


@base.DISCORD_CLIENT.slash_command(description="DS Camp Time Auditing", guild_ids=DS_GUILDS)
async def ds(inter: disnake.ApplicationCommandInteraction):
    pass


@ds.sub_command(description="Start recording time in camp.")
async def start(
    inter: disnake.ApplicationCommandInteraction,
    player: disnake.Member = commands.Param(
        default=None, description="Member entering camp (default: current member)."
    ),
    backdate: int = commands.Param(default=0, ge=0, description="Backdate entry by <X> minutes."),
):
    if player is None:
        player = inter.user
    last = points_model.get_last_event(player.id, guild_id=inter.guild_id)
    if last and last.active and not backdate:
        await inter.send("Player already active at camp.", ephemeral=True)
        return
    start_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    if last and (last.event != constants.Event.IN or not last.active) and start_time < last.time:
        await inter.send("Cannot backdate prior to the player's latest entry.", ephemeral=True)
        return
    last_tod = points_model.get_last_pop_time()
    if last_tod and start_time.astimezone() < last_tod:
        await inter.send(
            f"Cannot backdate prior to the last ToD (<t:{int(time.mktime(last_tod.timetuple()))}:R>).", ephemeral=True
        )
        return

    discord_ent_time = int(time.mktime(start_time.timetuple()))
    backdate_message = f", backdated {backdate} minutes" if backdate > 0 else ""

    if last and last.active:
        start_event = last
        last.time = start_time
        points_model.update_event(start_event)
        start_message = (
            f"Previous start time for <@{player.id}> updated to <t:{discord_ent_time}> "
            f"(<t:{discord_ent_time}:R>{backdate_message})."
        )
    else:
        start_event = points_model.PointsAudit(
            user_id=player.id, guild_id=inter.guild_id, event=constants.Event.IN, time=start_time, active=True
        )
        points_model.start_event(start_event)
        start_message = (
            f"<@{player.id}> entered camp at <t:{discord_ent_time}> (<t:{discord_ent_time}:R>{backdate_message})."
        )

    await inter.send(start_message, allowed_mentions=disnake.AllowedMentions(users=False))


def get_point_value(minute: int) -> float:
    SKPs: int = config.SKP_STARTTIME
    SKPb: int = config.SKP_BASELINE
    SKPm: int = config.SKP_MINIMUM
    SKPp: int = config.SKP_PLATEAU_MINUTE

    if minute < SKPs:
        return float(SKPm)
    elif minute >= SKPp:
        return float(SKPb)
    else:
        return round(SKPm + (SKPb - SKPm) * (minute - SKPs) / (SKPp - SKPs), 1)


def calculate_points_for_session(guild_id: int, stop_time: datetime.datetime) -> dict[int, dict[int, int]]:
    # Real POP defines the session boundary (which events to include)
    real_pop = points_model.get_last_pop_time()
    event_pairs = points_model.get_event_pairs_since_last_pop(guild_id)

    # Effective POP controls where we are on the point ramp curve
    effective_pop = get_effective_pop_time(guild_id)
    ramp_offset = round((real_pop - effective_pop).total_seconds() / 60)

    ### Normalize all event times relative to the real POP
    start_time = real_pop
    time_at_camp = stop_time.astimezone() - start_time
    standard_minutes = math.ceil(time_at_camp.total_seconds() / 60)

    # Normalize member event windows to start_time = 0
    normalized_member_windows = {}
    for member, m_event_windows in event_pairs.items():
        normalized_member_windows[member] = []
        for start_window, stop_window in m_event_windows.items():
            norm_start = round((start_window.astimezone() - start_time).total_seconds() / 60)
            norm_stop = round((stop_window.astimezone() - start_time).total_seconds() / 60)
            normalized_member_windows[member].append((max(0, norm_start), min(standard_minutes, norm_stop)))
    # end up with:
    # {member1: [(start1, stop1), (start2, stop2)], member2: []}

    points_earned_by_rate = {}
    for minute in range(standard_minutes):
        point_value = get_point_value((minute + ramp_offset) % (24 * 60))

        # Iterate through event pairs and find active ones
        active_players = []
        for member, m_norm_windows in normalized_member_windows.items():
            for m_start_window, m_stop_window in m_norm_windows:
                if m_start_window <= minute <= m_stop_window:
                    active_players.append(member)

        # Point value is the minute-rate divided by active members, lowest=1
        if active_players:
            point_value = round(max(1.0, point_value / len(active_players)), 1)

        # Ensure member exists and add points
        for member in active_players:
            if member not in points_earned_by_rate:
                points_earned_by_rate[member] = {}
            points_earned_by_rate[member][point_value] = 1 + points_earned_by_rate[member].get(point_value, 0)

    return points_earned_by_rate


def close_event(start_event: points_model.PointsAudit, stop_time: datetime.datetime) -> None:
    start_event.active = False
    stop_event = points_model.PointsAudit(
        user_id=start_event.user_id,
        guild_id=start_event.guild_id,
        event=constants.Event.OUT,
        time=stop_time,
        active=False,
        start_id=start_event.id,
    )
    points_model.close_event(start_event, stop_event)


@ds.sub_command(description="Stop recording time in camp.")
async def stop(
    inter: disnake.ApplicationCommandInteraction,
    player: disnake.Member = commands.Param(default=None, description="Member exiting camp (default: current member)."),
    backdate: int = commands.Param(
        default=None, ge=0, description="Backdate exit by <X> minutes. If already stopped, update the last stop time."
    ),
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
            minutes_since_start = int((datetime.datetime.now() - start_event.time).total_seconds() / 60)
            await inter.send(
                f"Cannot backdate to before start time ({minutes_since_start} minutes ago).", ephemeral=True
            )
            return
        last.time = stop_time
        points_model.update_event(last)
        discord_exit_time = int(time.mktime(last.time.timetuple()))
        backdate_message = f", backdated {backdate} minutes"
        await inter.send(
            f"Previous stop time for <@{player.id}> updated to"
            f" <t:{discord_exit_time}> (<t:{discord_exit_time}:R>{backdate_message}).",
            allowed_mentions=disnake.AllowedMentions(users=False),
        )
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
        f"<@{player.id}> exited camp at <t:{discord_exit_time}> (<t:{discord_exit_time}:R>{backdate_message}).",
        allowed_mentions=disnake.AllowedMentions(users=False),
    )


@ds.sub_command(description="Show current camp status.")
async def status(
    inter: disnake.ApplicationCommandInteraction,
    verbose: bool = commands.Param(default=False, description="Show detailed point data."),
):
    await inter.response.defer()
    active_events = points_model.get_active_events(inter.guild_id)
    now = datetime.datetime.now().replace(second=0)

    points_for_session = calculate_points_for_session(guild_id=inter.guild_id, stop_time=now)
    points_per_member = sum_points_by_member(points_for_session)

    start_time = get_effective_pop_time(inter.guild_id)
    time_at_camp = datetime.datetime.now().astimezone() - start_time
    minute = math.ceil(time_at_camp.total_seconds() / 60) % (60 * 24)
    current_rate = get_point_value(minute)

    # TODO: Make sure active_events can't be more than active_members below
    # and if it can, clean this up so the rate is based on active_members, or
    # so that the code below doesn't create an extra random Set for no reason
    if len(active_events) > 0:
        # Point value is the minute-rate divided by active members, lowest=1
        current_rate_str = str(max(1.0, round(current_rate / len(active_events), 1)))
    else:
        current_rate_str = f"0 of {current_rate}"

    message = f"Current camp status: `{1440 - minute} minutes to spawn` ({current_rate_str} SKP/min)\n"
    active_members = set()
    if active_events:
        message += "\nMembers in camp:\n"
    for event in active_events:
        active_members.add(event.user_id)
        time_spent = max(round((now - event.time).total_seconds()), 0)
        display_time = "{:0>8}".format(str(datetime.timedelta(seconds=time_spent)))
        if event.user_id in points_per_member:
            total_minutes = points_per_member[event.user_id][1]
            display_total = "{:0>8}".format(str(datetime.timedelta(minutes=total_minutes)))
        else:
            display_total = display_time
        session_points = points_per_member.get(event.user_id, (0,))[0]
        message += f"<@{event.user_id}>: {display_total} ({session_points} points"
        if verbose:
            session_rates = points_for_session.get(event.user_id, 0)
            message += f"; rates: {session_rates}"
        message += ")\n"

    # If more players were in the session, list them
    if len(set(points_per_member).difference(active_members)) > 0:
        message += "\nOther contributing members this session:\n"
        for member, member_points in points_per_member.items():
            if member not in active_members:
                total_minutes = points_per_member[member][1]
                display_total = "{:0>8}".format(str(datetime.timedelta(minutes=total_minutes)))
                session_points = points_per_member[member][0]
                message += f"<@{member}>: {display_total} ({session_points} points"
                if verbose:
                    session_rates = points_for_session.get(member, 0)
                    message += f"; rates: {session_rates}"
                message += ")\n"

    await utils.send_and_split(inter, message)


def sum_points_by_member(points_dict: dict[int, dict[float, int]]) -> dict[int, (int, int)]:
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
    earned_events = points_model.get_points_earned_by_member(user_id, guild_id)
    spent_events = points_model.get_points_spent_by_member(user_id, guild_id)
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
        default=None, description="Member for balance check (default: all players)."
    ),
    show_all: bool = commands.Param(default=False, description="Show points for ALL users (default: false)."),
):
    # Defer the response to avoid timeouts
    await inter.response.defer(ephemeral=player is not None)

    if player is None:
        if show_all:
            message = "**Point Balances:**\n"
            earned_points = points_model.get_points_earned(inter.guild_id)
        else:
            message = "**Point Balances (for players active in the last 14 days):**\n"
            earned_points = points_model.get_points_earned_recently(inter.guild_id, days=14)
        member_totals = []
        for member in earned_points:
            spent_events = points_model.get_points_spent_by_member(member.user_id, inter.guild_id)
            spent = 0
            for se in spent_events:
                spent += se.points
            member_totals.append((member.points - spent, spent, member.user_id))

        sorted_totals = sorted(member_totals, key=lambda tup: tup[0])
        for current_points, spent_points, user_id in reversed(sorted_totals):
            message += (
                f"<@{user_id}>: {current_points} (Earned {current_points + spent_points}, Spent {spent_points})\n"
            )
        if not sorted_totals:
            message += f"No points earned{'' if show_all else ' in the last 14 days'}."
        await utils.send_and_split(inter, message)
        return

    earned, spent = get_point_data_for_member(player.id, inter.guild_id)
    await inter.send(
        f"<@{player.id}> has {earned - spent} points (earned: {earned}, spent: {spent}).",
        ephemeral=True,
        allowed_mentions=disnake.AllowedMentions(users=False),
    )


@ds.sub_command(description="Run this when DS dies to stop all tracking.")
async def tod(
    inter: disnake.ApplicationCommandInteraction,
    is_quake: bool = commands.Param(default=False, description="Grant quake bonus to active members?"),
):
    if not is_ds_tod_channel(inter.guild_id, inter.channel_id):
        tod_channel_id = config.GUILD_SETTINGS.get(inter.guild_id, {}).get("ds_tod_channel")
        await inter.send(
            f"This command can only be used in <#{tod_channel_id}>.",
            ephemeral=True,
        )
        return

    recent = recent_pop_minutes()
    if recent is not None:
        await inter.send(
            f"Someone just ran the ToD command {recent} "
            f"minutes ago. Please try again after 5 minutes. "
            f"Deleting this interaction.",
            ephemeral=True,
        )
        return

    if should_confirm_quake(inter.guild_id, is_quake):
        remaining = time_until_expected_spawn(inter.guild_id)
        total_minutes = max(0, int(remaining.total_seconds() // 60))
        hours, minutes = divmod(total_minutes, 60)
        if hours and minutes:
            remaining_str = f"{hours}h {minutes}m"
        elif hours:
            remaining_str = f"{hours}h"
        else:
            remaining_str = f"{minutes}m"
        view = TodQuakeConfirmView(invoker_id=inter.user.id)
        await inter.send(
            f"Expected spawn is still about **{remaining_str}** away — this is often a quake.\n"
            f"Was this a quake? (Grants the {config.QUAKE_BONUS} SKP quake bonus to active campers.)",
            view=view,
            ephemeral=True,
        )
        try:
            view.message = await inter.original_message()
        except Exception:
            view.message = None
        return

    await _execute_ds_tod(inter, is_quake=is_quake)


@ds.sub_command(description="Player has won an urn with SKP.")
async def urn(
    inter: disnake.ApplicationCommandInteraction,
    player: disnake.Member = commands.Param(description="Member who won the urn."),
    price: int = commands.Param(gt=0, description="Number of SKP spent."),
    backdate: int = commands.Param(default=0, ge=0, description="Backdate purchase by <X> minutes."),
):
    user_points_earned, user_points_spent = get_point_data_for_member(player.id, inter.guild_id)
    if user_points_earned - user_points_spent < price:
        await inter.send("Not enough points for purchase.", ephemeral=True)
        return
    buy_time = datetime.datetime.now() - datetime.timedelta(minutes=backdate)
    purchase = points_model.PointsSpent(user_id=player.id, guild_id=inter.guild_id, points=price, time=buy_time)
    purchase.store()
    earned, spent = get_point_data_for_member(player.id, inter.guild_id)
    await inter.send(
        f"<@{player.id}> won an urn for {price} SKP! They have {earned - spent} SKP remaining.",
        allowed_mentions=disnake.AllowedMentions(users=False),
    )


@ds.sub_command(description="Adjust points for a member.")
async def adjust(
    inter: disnake.ApplicationCommandInteraction,
    player: disnake.Member = commands.Param(description="Member to adjust points."),
    points: int = commands.Param(default=0, description="Number of points to adjust (relative +/-)."),
    notes: str = commands.Param(default=None, description="Optional notes / reason for adjustment."),
):

    # Check if the user has the correct role to adjust points
    admin_role = config.GUILD_SETTINGS.get(inter.guild_id, {}).get("ds_admin_role")
    if admin_role != 0 and admin_role not in (role.id for role in inter.user.roles):
        await inter.send("You do not have permission to adjust points.", ephemeral=True)
        return

    points_earned = points_model.PointsEarned(
        user_id=player.id,
        guild_id=inter.guild_id,
        points=points,
        time=datetime.datetime.now(),
        notes=notes,
        adjustor=inter.user.id,
    )

    points_earned.store()
    message = f"Adjustment applied: {points} SKP for <@{player.id}>"
    if notes:
        message += f" with notes: `{notes}`"
    message += "."
    await inter.send(message, allowed_mentions=disnake.AllowedMentions(users=False))


@ds.sub_command(description="Override the next DS spawn time.")
async def set_spawn(
    inter: disnake.ApplicationCommandInteraction,
    hours: int = commands.Param(default=0, ge=0, description="Hours until next spawn."),
    minutes: int = commands.Param(default=0, ge=0, description="Minutes until next spawn."),
    timestamp: str = commands.Param(default=None, description="Absolute next-spawn time (assumes ET)."),
):

    admin_role = config.GUILD_SETTINGS.get(inter.guild_id, {}).get("ds_admin_role")
    if admin_role != 0 and admin_role not in (role.id for role in inter.user.roles):
        await inter.send("You do not have permission to use this command.", ephemeral=True)
        return

    if timestamp:
        try:
            parsed = parser.parse(timestamp, tzinfos=constants.TIMEZONES)
        except parser.ParserError:
            await inter.send("Could not parse that timestamp.", ephemeral=True)
            return
        if not parsed.tzname():
            parsed = parsed.replace(tzinfo=constants.TIMEZONES["ET"])
        next_spawn_time = parsed.astimezone()
    elif hours or minutes:
        next_spawn_time = datetime.datetime.now().astimezone() + datetime.timedelta(hours=hours, minutes=minutes)
    else:
        await inter.send("Provide hours/minutes until spawn, or a timestamp.", ephemeral=True)
        return

    if next_spawn_time <= datetime.datetime.now().astimezone():
        await inter.send("Next spawn time must be in the future.", ephemeral=True)
        return

    old_pop = get_effective_pop_time(inter.guild_id)
    implied_pop = next_spawn_time - datetime.timedelta(hours=24)
    SPAWN_OVERRIDE[inter.guild_id] = implied_pop

    old_spawn = old_pop + datetime.timedelta(hours=24)
    old_ts = int(old_spawn.timestamp())
    new_ts = int(next_spawn_time.timestamp())
    message = (
        f"Spawn override applied.\nOld spawn: <t:{old_ts}> (<t:{old_ts}:R>)\nNew spawn: <t:{new_ts}> (<t:{new_ts}:R>)"
    )

    active_events = points_model.get_active_events(inter.guild_id)
    if active_events:
        message += f"\n⚠ {len(active_events)} active camper(s) — point rates will shift."

    await inter.send(message)

    # Restart the DS Spawn timer to match
    timer_channel_id = config.GUILD_SETTINGS.get(inter.guild_id, {}).get("ds_tod_channel")
    if not timer_channel_id:
        return
    timers = timer_model.get_timers_for_channel(timer_channel_id)
    timer_channel = inter.guild.get_channel(timer_channel_id)
    if timers:
        for t in timers:
            await cmd_timer._stop(t.id, timer_channel.send)

    delay_seconds = int((next_spawn_time - datetime.datetime.now().astimezone()).total_seconds())
    await cmd_timer._start(
        timer_channel.send,
        timer_channel,
        base.DISCORD_CLIENT.user.id,
        inter.guild_id,
        name="DS Spawn",
        hours=24,
        minutes=1,
        delay_minutes=0,
        delay_seconds=delay_seconds - (24 * 3600 + 60),
        repeating=True,
    )


@ds.sub_command(description="Show audit logs for a member's DS events.")
async def audit(
    inter: disnake.ApplicationCommandInteraction,
    player: disnake.Member = commands.Param(description="Member to audit."),
):
    # Defer the response to avoid timeouts
    await inter.response.defer(ephemeral=True)

    # Fetch all the audit events for the player
    events = points_model.get_events_for_member(player.id, inter.guild_id)
    # Also fetch Earned/Spent entries
    points_earned = points_model.get_points_earned_by_member(player.id, inter.guild_id)
    points_spent = points_model.get_points_spent_by_member(player.id, inter.guild_id)

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
        message += f"<t:{int(event_start.timestamp())}> -> <t:{int(event_end.timestamp())}> ({minutes} minutes)\n"

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

    if earned_spent_messages and message.count("\n") > 2:
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

    await inter.send(content=f"Sent audit data for <@{player.id}> via DM: {dm.jump_url}", ephemeral=True)


async def schedule_messages():
    for guild_id in DS_GUILDS:
        channel_id = config.GUILD_SETTINGS.get(guild_id, {}).get("ds_schedule_channel")
        if channel_id:
            channel = await base.DISCORD_CLIENT.fetch_channel(channel_id)
            if not channel:
                logger.warning("Could not find channel with ID %s for guild %s", channel_id, guild_id)
                return

            task = asyncio.create_task(_schedule_message_repeating(channel))
            asyncio.ensure_future(task)


async def _schedule_message_repeating(channel: disnake.TextChannel):
    # Get all messages from today
    today = (
        datetime.datetime.now().astimezone(constants.TIMEZONES["ET"]).replace(hour=0, minute=0, second=0, microsecond=0)
    )
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
        now = datetime.datetime.now().astimezone(constants.TIMEZONES["ET"])
        tomorrow = now + datetime.timedelta(days=1)
        noon_tomorrow = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)

        # Sleep until the next noon
        await asyncio.sleep((noon_tomorrow - now).total_seconds())
        await _schedule_message(channel)


async def _schedule_message(channel: disnake.TextChannel):
    # Get the current time
    current_datetime = datetime.datetime.now().astimezone(constants.TIMEZONES["ET"])
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
            return "th"
        else:
            return {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")

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
"""

    message_object = await channel.send(message, allowed_mentions=disnake.AllowedMentions(everyone=True))
    for emoji in "🇦🇧🇨🇩🇪🇫🇬🇭🇮":
        await message_object.add_reaction(emoji)
