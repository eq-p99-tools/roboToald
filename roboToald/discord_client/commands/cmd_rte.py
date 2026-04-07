"""RTE (Ready-To-Engage) tracking slash commands and handlers.

Port of batphone-bot rte.rb, rte_command.rb, unrte.rb, trackers.rb, pending.rb,
and the DM button handler (originally a reaction handler from on_reaction_add.rb).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import disnake
import disnake.ext.commands

import sqlalchemy as sa

from roboToald import config
from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.target import Target, TargetAlias
from roboToald.db.raid_models.tracking import Tracking, RTE_ROLES
from roboToald.db.raid_models.character import Character
from roboToald.discord_client import base
from roboToald.raid import permissions as perms
from roboToald.raid.dkp_calculator import dkp_from_duration
from roboToald.raid.event_helpers import resolve_target, _time_ago_in_words

logger = logging.getLogger(__name__)

RAID_GUILDS = config.guilds_for_command("raid")

# ---------------------------------------------------------------------------
# /rte slash command group
# ---------------------------------------------------------------------------


@base.DISCORD_CLIENT.slash_command(description="RTE tracking", guild_ids=RAID_GUILDS)
async def rte(inter: disnake.ApplicationCommandInteraction):
    pass


@rte.sub_command(description="Start RTEing a target.")
async def start(
    inter: disnake.ApplicationCommandInteraction,
    role: str = disnake.ext.commands.Param(
        description="Your RTE role",
        choices=[v["name"] for v in RTE_ROLES.values()],
    ),
    character: str = disnake.ext.commands.Param(description="Your character name", autocomplete=True),
    target_name: str = disnake.ext.commands.Param(description="Target name", name="target", autocomplete=True),
    on_character: str = disnake.ext.commands.Param(
        description="Character you are on (if different)", default=None, autocomplete=True
    ),
):
    guild_id = inter.guild.id
    await inter.response.defer(ephemeral=True)

    role_id = next((k for k, v in RTE_ROLES.items() if v["name"].lower() == role.lower()), None)

    with get_raid_session(guild_id) as session:
        char = session.query(Character).filter(Character.name.ilike(character)).first()
        if not char:
            char = Character(name=character.capitalize())
            session.add(char)
            session.flush()

        on_char = None
        if on_character:
            on_char = session.query(Character).filter(Character.name.ilike(on_character)).first()
            if not on_char:
                on_char = Character(name=on_character.capitalize())
                session.add(on_char)
                session.flush()

        targets, _ = resolve_target(target_name, session)
        if len(targets) > 1:
            names = ", ".join(t.name for t in targets)
            await inter.followup.send(f"```diff\n- Multiple targets found ({names}). Be more specific.```")
            return
        if not targets:
            await inter.followup.send(f"```diff\n- Target {target_name} not found.```")
            return

        tgt = targets[0]
        if not tgt.can_rte:
            await inter.followup.send("```diff\n- That target cannot be RTE'd.```")
            return

        existing = session.query(Tracking).filter_by(character_id=char.id, end_time=None).first()
        if existing:
            ex_target = session.query(Target).get(existing.target_id)
            await inter.followup.send(
                f"```diff\n- {char.name} is already RTEing {ex_target.name if ex_target else '?'} as {existing.role_name}```",
            )
            return

        tracking = Tracking(
            role_id=role_id,
            is_rte=True,
            is_racing=False,
            target_id=tgt.id,
            character_id=char.id,
            user_id=str(inter.author.id),
            start_time=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        if on_char:
            tracking.on_character_id = on_char.id
        session.add(tracking)
        session.flush()

        rate = tracking.rate_per_hour
        msg_text = f"+ {char.name} started RTEing {tgt.name}"
        if on_char:
            msg_text += f" on {on_char.name}"
        msg_text += f" as {tracking.role_name} (DKP Per Hour: {rate}, ID: {tracking.id})"

        chan_text = f"+ {char.name} started RTEing {tgt.name}"
        if on_char:
            chan_text += f" on {on_char.name}"
        chan_text += (
            f" as {tracking.role_name} by {inter.author.display_name} (DKP Per Hour: {rate}, ID: {tracking.id})"
        )

        tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
        tracking_ch = inter.guild.get_channel(tracking_ch_id) if tracking_ch_id else None
        if tracking_ch:
            resp = await tracking_ch.send(f"```diff\n{chan_text}```")
            tracking.message_id = str(resp.id)
        await inter.followup.send(f"```diff\n{msg_text}```")

        try:
            dm_text = (
                f"```diff\n+ You have started RTEing {tgt.name} on "
                f"{(on_char or char).name} as {tracking.role_name}. "
                f"Use the button below when finished. (DKP Per Hour: {rate}, ID: {tracking.id})```"
            )
            dm_msg = await inter.author.send(dm_text, view=_make_stop_rte_view(guild_id, tracking.id))
            tracking.user_pm_message_id = str(dm_msg.id)
        except (disnake.Forbidden, disnake.HTTPException):
            logger.warning("Could not DM user %s for RTE", inter.author.id)

        session.commit()


def _rte_target_choices(query: str, guild_id: int) -> dict[str, str]:
    query = query.strip().lower()
    with get_raid_session(guild_id) as session:
        q = (
            session.query(Target)
            .filter(Target.can_rte.is_(True))
            .filter(sa.func.length(Target.name) > 0)
            .filter(sa.or_(Target.parent == "", Target.parent.is_(None)))
            .order_by(Target.name)
        )
        if query:
            alias_ids = (
                session.query(TargetAlias.target_id).filter(sa.func.lower(TargetAlias.name).startswith(query)).all()
            )
            alias_target_ids = [a[0] for a in alias_ids]
            q = q.filter(
                sa.or_(
                    sa.func.lower(Target.name).startswith(query),
                    Target.id.in_(alias_target_ids),
                )
            )
        return {t.name: t.name for t in q.limit(25).all()}


def _character_choices(query: str, guild_id: int) -> dict[str, str]:
    query = query.strip().lower()
    with get_raid_session(guild_id) as session:
        q = session.query(Character).filter(sa.func.length(Character.name) > 0).order_by(Character.name)
        if query:
            q = q.filter(sa.func.lower(Character.name).startswith(query))
        return {c.name: c.name for c in q.limit(25).all()}


@start.autocomplete("target")
async def _ac_start_target(inter: disnake.ApplicationCommandInteraction, query: str):
    return _rte_target_choices(query, inter.guild.id)


@start.autocomplete("character")
@start.autocomplete("on_character")
async def _ac_start_character(inter: disnake.ApplicationCommandInteraction, query: str):
    return _character_choices(query, inter.guild.id)


@rte.sub_command(description="End RTE manually.")
async def stop(
    inter: disnake.ApplicationCommandInteraction,
    character: str = disnake.ext.commands.Param(description="Character name", autocomplete=True),
    target_name: str = disnake.ext.commands.Param(description="Target name", name="target", autocomplete=True),
):
    guild_id = inter.guild.id
    with get_raid_session(guild_id) as session:
        char = session.query(Character).filter(Character.name.ilike(character)).first()
        if not char:
            await inter.response.send_message(f"```diff\n- Character {character} not found.```", ephemeral=True)
            return

        targets, _ = resolve_target(target_name, session)
        if not targets:
            await inter.response.send_message(f"```diff\n- Target {target_name} not found.```", ephemeral=True)
            return

        tgt = targets[0] if len(targets) == 1 else None
        if not tgt:
            await inter.response.send_message(
                f"```diff\n- Multiple targets found for {target_name}, be more specific.```", ephemeral=True
            )
            return

        tracking = session.query(Tracking).filter_by(character_id=char.id, target_id=tgt.id, end_time=None).first()
        if not tracking:
            await inter.response.send_message(
                "```diff\n- No active RTE found for that character/target.```", ephemeral=True
            )
            return

        tracking.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()

        dur = tracking.duration
        time_diff = _time_ago_in_words(tracking.start_time) if tracking.start_time else _fmt_duration(dur)
        dkp_earned = tracking.dkp_amount
        on_char = session.query(Character).get(tracking.on_character_id) if tracking.on_character_id else None

        chan_msg = f"+ {char.name} is no longer RTEing {tgt.name}"
        if on_char:
            chan_msg += f" on {on_char.name}"
        chan_msg += f" as {tracking.role_name} due to manual end by {inter.author.display_name}. Total time was about {time_diff} (DKP Award: {dkp_earned}, ID: {tracking.id})"

        reply_ref = None
        if tracking.message_id:
            try:
                reply_ref = inter.channel.get_partial_message(int(tracking.message_id))
            except (ValueError, AttributeError):
                pass

        if reply_ref:
            await inter.response.defer()
            await inter.channel.send(f"```diff\n{chan_msg}```", reference=reply_ref)
            await inter.delete_original_response()
        else:
            await inter.response.send_message(f"```diff\n{chan_msg}```")

        if tracking.user_id:
            try:
                user = await base.DISCORD_CLIENT.fetch_user(int(tracking.user_id))
                dm_msg = f"+ You are no longer RTEing {tgt.name} on {char.name}"
                if on_char:
                    dm_msg += f" on {on_char.name}"
                dm_msg += f" as {tracking.role_name} due to manual end. Total time was about {time_diff} (DKP Award: {dkp_earned}, ID: {tracking.id})"

                dm_ref = None
                if tracking.user_pm_message_id:
                    try:
                        dm_channel = user.dm_channel or await user.create_dm()
                        dm_ref = dm_channel.get_partial_message(int(tracking.user_pm_message_id))
                    except (ValueError, AttributeError):
                        pass

                await user.send(f"```diff\n{dm_msg}```", reference=dm_ref)
            except (disnake.Forbidden, disnake.HTTPException):
                pass


@rte.sub_command(description="Show current RTE status.")
async def status(inter: disnake.ApplicationCommandInteraction):
    guild_id = inter.guild.id
    with get_raid_session(guild_id) as session:
        trackings = session.query(Tracking).filter_by(end_time=None).all()
        tracks: dict[str, list[dict]] = {}
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for t in trackings:
            tgt = session.query(Target).get(t.target_id) if t.target_id else None
            char = session.query(Character).get(t.character_id) if t.character_id else None
            if not tgt or not char:
                continue
            on_char = session.query(Character).get(t.on_character_id) if t.on_character_id else None
            dur = (now - t.start_time).total_seconds() if t.start_time else 0
            key = tgt.name
            tracks.setdefault(key, []).append(
                {
                    "id": t.id,
                    "role": t.role_name,
                    "player": char.name,
                    "on": on_char.name if on_char else None,
                    "duration": _fmt_duration(dur),
                }
            )

        embed = disnake.Embed(title="Current Tracking & Readiness Status")
        for tgt_name, players in tracks.items():
            lines = ["```diff"]
            by_role: dict[str, list] = {}
            for p in players:
                r = p["role"] or "Unknown"
                by_role.setdefault(r, []).append(p)
            for role_name, group in by_role.items():
                parts = ", ".join(
                    f"{p['on'] or p['player']} ({p['player'] + ', ' if p['on'] else ''}{p['duration']}, ID: {p['id']})"
                    for p in group
                )
                lines.append(f"+ {role_name}({len(group)}) - {parts}")
            lines.append("```")
            embed.add_field(name=tgt_name, value="\n".join(lines), inline=False)

        if not embed.fields:
            await inter.response.send_message("No active RTE sessions.", ephemeral=True)
            return

        await inter.response.send_message(embed=embed)


@rte.sub_command(description="Show closed trackings not yet submitted.")
async def pending(inter: disnake.ApplicationCommandInteraction):
    guild_id = inter.guild.id
    with get_raid_session(guild_id) as session:
        trackings = (
            session.query(Tracking).filter(Tracking.adjustment_id.is_(None), Tracking.end_time.isnot(None)).all()
        )
        if not trackings:
            await inter.response.send_message("No pending trackings.", ephemeral=True)
            return

        tracks: dict[str, dict[str, list[dict]]] = {}
        for t in trackings:
            char = session.query(Character).get(t.character_id) if t.character_id else None
            tgt = session.query(Target).get(t.target_id) if t.target_id else None
            if not char or not tgt:
                continue
            dkp = t.dkp_amount
            if dkp <= 0 and char.eqdkp_member_id:
                continue
            tracks.setdefault(tgt.name, {}).setdefault(char.name, []).append(
                {
                    "id": t.id,
                    "role": t.role_name,
                    "duration": _fmt_duration(t.duration),
                    "dkp": dkp,
                }
            )

        if not tracks:
            await inter.response.send_message("No pending trackings.", ephemeral=True)
            return

        embed = disnake.Embed(title="Pending Tracking & Readiness for Submit")
        for tgt_name, char_tracks in tracks.items():
            lines = []
            for char_name, items in char_tracks.items():
                lines.append(char_name.upper())
                for item in items:
                    lines.append(f"+ {item['role']} - {item['duration']}, DKP:{item['dkp']} (ID:{item['id']})")
            text = "\n".join(lines)
            if len(text) > 900:
                buf = ""
                for line in lines:
                    if len(buf + line + "\n") > 900:
                        embed.add_field(name=tgt_name, value=f"```diff\n{buf}```", inline=False)
                        buf = ""
                    buf += line + "\n"
                if buf:
                    embed.add_field(name=tgt_name, value=f"```diff\n{buf}```", inline=False)
            else:
                embed.add_field(name=tgt_name, value=f"```diff\n{text}```", inline=False)

        await inter.response.send_message(embed=embed)


@rte.sub_command(description="Submit closed RTE trackings for a target to EQdkp.")
async def submit(
    inter: disnake.ApplicationCommandInteraction,
    target_name: str = disnake.ext.commands.Param(description="Target name", name="target", autocomplete=True),
):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "submit", guild_id):
        await inter.response.send_message("```diff\n- No permission.```", ephemeral=True)
        return

    await inter.response.defer()
    with get_raid_session(guild_id) as session:
        targets, _ = resolve_target(target_name, session)
        if len(targets) != 1:
            await inter.followup.send("```diff\n- Target not found or ambiguous.```", ephemeral=True)
            return

        tgt = targets[0]
        try:
            from roboToald.eqdkp.client import EqdkpClient

            eqdkp = EqdkpClient(guild_id)

            trackings = (
                session.query(Tracking)
                .filter_by(adjustment_id=None, target_id=tgt.id)
                .filter(Tracking.end_time.isnot(None))
                .all()
            )

            groups: dict[tuple, list[Tracking]] = {}
            for t in trackings:
                char = session.query(Character).get(t.character_id)
                if not char:
                    continue
                key = (char.id, tgt.id, t.rate_per_hour)
                groups.setdefault(key, []).append(t)

            for (char_id, _, rate), items in groups.items():
                char = session.query(Character).get(char_id)
                if not char:
                    continue
                char = await eqdkp.create_member(char, session=session)
                if not char.eqdkp_member_id:
                    continue

                total_duration = sum(i.duration or 0 for i in items)
                total_dkp = dkp_from_duration(rate, total_duration)

                role_names = ", ".join(set(i.role_name for i in items if i.role_name))
                min_start = min(i.start_time for i in items if i.start_time)
                max_end = max(i.end_time for i in items if i.end_time)
                reason = f"RTE {tgt.name} as {role_names} for {_fmt_duration(total_duration)} (Start: {min_start.strftime('%Y-%m-%d %I:%M %p')})"

                adj_id = await eqdkp.add_adjustment(
                    char.eqdkp_member_id,
                    total_dkp,
                    reason,
                    time=max_end,
                )
                for i in items:
                    i.adjustment_id = adj_id

            session.commit()
            await inter.followup.send("```diff\n+ RTE submitted to EQdkp.```")
        except Exception as exc:
            logger.exception("RTE submission failed")
            await inter.followup.send(f"```diff\n- Error submitting RTE: {exc}```")


# ---------------------------------------------------------------------------
# Persistent button view: DM "Stop RTE" button
# ---------------------------------------------------------------------------


def _make_stop_rte_view(guild_id: int, tracking_id: int) -> disnake.ui.View:
    """Create a persistent Stop RTE button view with guild and tracking IDs in the custom_id."""
    view = disnake.ui.View(timeout=None)
    view.add_item(
        disnake.ui.Button(
            label="Stop RTE",
            style=disnake.ButtonStyle.danger,
            custom_id=f"stop_rte:{guild_id}:{tracking_id}",
        )
    )
    return view


@base.DISCORD_CLIENT.listen("on_button_click")
async def on_stop_rte_button(inter: disnake.MessageInteraction):
    custom_id = inter.component.custom_id or ""
    if not custom_id.startswith("stop_rte:"):
        return

    parts = custom_id.split(":")
    guild_id = int(parts[1])
    tracking_id = int(parts[2])

    with get_raid_session(guild_id) as session:
        tracking = session.get(Tracking, tracking_id)
        if not tracking or tracking.end_time is not None:
            await inter.response.send_message("```diff\n- No active RTE found for this message.```", ephemeral=True)
            return

        tracking.end_time = datetime.now(timezone.utc).replace(tzinfo=None)
        session.flush()

        char = session.query(Character).get(tracking.character_id)
        tgt = session.query(Target).get(tracking.target_id)
        on_char = session.query(Character).get(tracking.on_character_id) if tracking.on_character_id else None
        dur = tracking.duration
        time_diff = _time_ago_in_words(tracking.start_time) if tracking.start_time else _fmt_duration(dur)
        dkp_earned = tracking.dkp_amount
        char_name = char.name if char else "?"
        tgt_name = tgt.name if tgt else "?"
        on_char_name = on_char.name if on_char else None
        role_name = tracking.role_name
        tracking_id = tracking.id
        tracking_message_id = tracking.message_id

        session.commit()

    dm_summary = f"+ You are no longer RTEing {tgt_name} on {char_name}"
    if on_char_name:
        dm_summary += f" on {on_char_name}"
    dm_summary += f" as {role_name} due to button end. Total time was about {time_diff} (DKP Award: {dkp_earned}, ID: {tracking_id})"

    stopped_view = disnake.ui.View()
    stopped_view.add_item(
        disnake.ui.Button(
            label="RTE Stopped",
            style=disnake.ButtonStyle.secondary,
            disabled=True,
            custom_id=custom_id,
        )
    )
    await inter.response.edit_message(view=stopped_view)
    await inter.followup.send(f"```diff\n{dm_summary}```")

    chan_summary = f"+ {char_name} is no longer RTEing {tgt_name}"
    if on_char_name:
        chan_summary += f" on {on_char_name}"
    chan_summary += f" as {role_name} due to button end by {inter.author.display_name}. Total time was about {time_diff} (DKP Award: {dkp_earned}, ID: {tracking_id})"

    tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
    tracking_ch = None
    if tracking_ch_id:
        for guild in base.DISCORD_CLIENT.guilds:
            if guild.id == guild_id:
                tracking_ch = guild.get_channel(tracking_ch_id)
                break
    if tracking_ch:
        try:
            reply_ref = None
            if tracking_message_id:
                try:
                    reply_ref = tracking_ch.get_partial_message(int(tracking_message_id))
                except (ValueError, AttributeError):
                    pass
            await tracking_ch.send(f"```diff\n{chan_summary}```", reference=reply_ref)
        except disnake.HTTPException:
            pass


# ---------------------------------------------------------------------------
# Message handlers: +/- tracking time in tracking channel
# ---------------------------------------------------------------------------


@base.DISCORD_CLIENT.listen("on_message")
async def on_tracking_message(message: disnake.Message):
    if not message.guild or message.author.bot:
        return
    guild_id = message.guild.id
    if guild_id not in config.raid_guild_ids():
        return
    tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
    if not tracking_ch_id or message.channel.id != tracking_ch_id:
        return

    content = message.content or ""
    if content.startswith("+"):
        await _handle_add_tracking_time(message)
    elif content.startswith("-"):
        await _handle_remove_tracking_time(message)


async def _handle_add_tracking_time(message: disnake.Message):
    guild_id = message.guild.id
    if not perms.can(message.author, "add_rte_time", guild_id):
        await message.channel.send("```diff\n- No permission.```")
        return
    parts = message.content.lstrip("+").strip().split()
    if len(parts) < 2:
        await message.channel.send("```diff\n- Usage: +<tracking_id> <minutes>```")
        return
    try:
        tracking_id = int(parts[0])
        mins = int(parts[1])
    except ValueError:
        return

    with get_raid_session(guild_id) as session:
        tracking = session.query(Tracking).get(tracking_id)
        if not tracking:
            await message.channel.send("```diff\n- Tracking not found.```")
            return
        tracking.start_time = tracking.start_time - __import__("datetime").timedelta(minutes=mins)
        session.commit()
        char = session.query(Character).get(tracking.character_id)
        tgt = session.query(Target).get(tracking.target_id)
        await message.channel.send(
            f"```diff\n+ RTE start for {char.name if char else '?'} on {tgt.name if tgt else '?'} pushed back {mins} min by Admin.```"
        )


async def _handle_remove_tracking_time(message: disnake.Message):
    guild_id = message.guild.id
    if not perms.can(message.author, "remove_rte_time", guild_id):
        await message.channel.send("```diff\n- No permission.```")
        return
    parts = message.content.lstrip("-").strip().split()
    if not parts:
        return
    try:
        tracking_id = int(parts[0])
    except ValueError:
        return
    mins = int(parts[1]) if len(parts) > 1 else None

    with get_raid_session(guild_id) as session:
        tracking = session.query(Tracking).get(tracking_id)
        if not tracking:
            await message.channel.send("```diff\n- Tracking not found.```")
            return

        char = session.query(Character).get(tracking.character_id)
        tgt = session.query(Target).get(tracking.target_id)
        char_name = char.name if char else "?"
        tgt_name = tgt.name if tgt else "?"

        if mins is not None and tracking.end_time:
            tracking.end_time = tracking.end_time - __import__("datetime").timedelta(minutes=mins)
            session.commit()
            await message.channel.send(
                f"```diff\n+ RTE end for {char_name} on {tgt_name} pushed back {mins} min by Admin.```"
            )
        else:
            from roboToald.db.raid_models.raid import Attendee

            session.query(Attendee).filter_by(tracking_id=str(tracking_id)).delete()
            session.delete(tracking)
            session.commit()
            await message.channel.send(f"```diff\n+ {char_name} tracking on {tgt_name} deleted by Admin. (DKP: 0)```")

            if tracking.user_id:
                try:
                    user = await base.DISCORD_CLIENT.fetch_user(int(tracking.user_id))
                    await user.send(f"```diff\n+ Your RTE on {tgt_name} was removed by Admin. (DKP: 0)```")
                except (disnake.Forbidden, disnake.HTTPException):
                    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return "0m"
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


# ---------------------------------------------------------------------------
# Autocomplete handlers (registered after all subcommands are defined)
# ---------------------------------------------------------------------------


@stop.autocomplete("target")
@submit.autocomplete("target")
async def _ac_unrte_submit_target(inter: disnake.ApplicationCommandInteraction, query: str):
    return _rte_target_choices(query, inter.guild.id)


@stop.autocomplete("character")
async def _ac_unrte_character(inter: disnake.ApplicationCommandInteraction, query: str):
    return _character_choices(query, inter.guild.id)
