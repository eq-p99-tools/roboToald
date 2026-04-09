"""Event management slash commands, $text commands, and message handlers.

Port of batphone-bot event.rb, kill.rb, nokill.rb, dkp.rb, submit.rb,
delete_event.rb, clear.rb, target.rb, targets.rb, add_player.rb,
remove_record.rb, send_batphone.rb, on_message.rb, loot.rb, unloot.rb,
fte.rb, unfte.rb, help.rb, reload.rb, register.rb.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import zoneinfo
from datetime import datetime, timedelta, timezone

import disnake
import disnake.ext.commands
import sqlalchemy as sa

from roboToald import config
from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.raid import Event, Attendee, Removal, Fte, EqdkpEvent
from roboToald.db.raid_models.target import Target, TargetAlias, Tier
from roboToald.db.raid_models.tracking import Tracking
from roboToald.db.raid_models.loot import EventLoot, Loot, Item, LootTable
from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.permission import Permission
from roboToald.discord_client import base
from roboToald.eqdkp.client import EqdkpClient
from roboToald.raid import permissions as perms
from roboToald.raid.event_helpers import (
    resolve_target,
    get_shortest_alias,
    rte_tracking_creator,
    build_target_loot_table_lines,
    build_raid_status_embed,
)
from roboToald.raid.event_kill_mark import (
    apply_kill_state_to_event,
    event_channel_name_with_kill_prefix,
    rename_event_channel_for_kill_name,
)
from roboToald.raid.player_parser import parse_players_from_content
from roboToald.raid.pushsafer import send_batphone

logger = logging.getLogger(__name__)
ET = zoneinfo.ZoneInfo("America/New_York")

RAID_GUILDS = config.guilds_for_command("raid")

# ---------------------------------------------------------------------------
# /event slash command group
# ---------------------------------------------------------------------------


@base.DISCORD_CLIENT.slash_command(description="Event management", guild_ids=RAID_GUILDS)
async def event(inter: disnake.ApplicationCommandInteraction):
    pass


@event.sub_command(description="Create a new raid event channel.")
async def create(
    inter: disnake.ApplicationCommandInteraction,
    target_name: str = disnake.ext.commands.Param(description="Target name or alias", autocomplete=True),
):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "create_event", guild_id):
        await inter.response.send_message(
            "```diff\n- You do not have permission to access that command.```", ephemeral=True
        )
        return

    await inter.response.defer(ephemeral=True)

    with get_raid_session(guild_id) as session:
        targets, _ = resolve_target(target_name, session)
        target = targets[0] if len(targets) == 1 else None

        if len(targets) > 1:
            names = ", ".join(t.name for t in targets)
            await inter.followup.send(f"```diff\n- Multiple targets found ({names}). Please be more specific.```")
            return

        if _is_locked_out(target, session):
            await inter.followup.send(
                "```diff\n- An event for this target was created recently (lockout). Skipping.```"
            )
            return

        children = []
        if target:
            children = session.query(Target).filter_by(parent=target.name).all()

        display_name = target_name
        if target:
            display_name = get_shortest_alias(target, session)

        async def _send_error(msg):
            await inter.followup.send(msg)

        created_channels = []
        if children:
            for child in children:
                ch = await _perform_create_event(
                    inter.guild,
                    inter.author.display_name,
                    _send_error,
                    session,
                    f"{display_name} - {child.name}",
                    target=target,
                    channel_name=f"{display_name} {child.name}",
                    dkp_value=child.value,
                    dkp_nokill_value=child.nokill_value or child.value,
                    child_target=child,
                )
                if ch:
                    created_channels.append(ch)
        else:
            ch = await _perform_create_event(
                inter.guild,
                inter.author.display_name,
                _send_error,
                session,
                display_name,
                target=target,
                targets=targets,
            )
            if ch:
                created_channels.append(ch)

    if not created_channels:
        return
    links = " ".join(ch.mention for ch in created_channels)
    if target:
        await inter.followup.send(f"Event channel created for **{display_name}**: {links}")
    else:
        await inter.followup.send(f"Event created (no target matched): {links}")

    create_event_ch_id = config.get_raid_setting(guild_id, "create_event_channel_id")
    if create_event_ch_id:
        audit_ch = inter.guild.get_channel(create_event_ch_id)
        if audit_ch:
            try:
                await audit_ch.send(
                    f"```diff\n+ {inter.author.display_name} created event for {display_name}```{links}"
                )
            except disnake.HTTPException:
                pass


def _is_locked_out(target: Target | None, session) -> bool:
    """Return True if a recent event exists within the target's lockout window."""
    if not target or not target.lockout_hrs or target.lockout_hrs <= 0:
        return False
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=target.lockout_hrs)
    return (
        session.query(Event)
        .filter(Event.target_id == target.id, Event.created_at >= cutoff)
        .order_by(Event.created_at.desc())
        .first()
    ) is not None


async def _perform_create_event(
    guild: disnake.Guild,
    started_by: str,
    send_error,
    session,
    target_name: str,
    *,
    target: Target | None = None,
    channel_name: str | None = None,
    dkp_value: int | None = None,
    dkp_nokill_value: int | None = None,
    targets: list[Target] | None = None,
    child_target: Target | None = None,
):
    guild_id = guild.id
    now = datetime.now(timezone.utc)
    et_now = now.astimezone(ET)
    ch_name = f"{channel_name or target_name} {et_now.strftime('%b-%d-%I%p').lower()}"

    channel = None
    for cat_id in config.get_raid_setting(guild_id, "event_category_ids") or []:
        try:
            category = guild.get_channel(cat_id)
            if category is None:
                continue
            channel = await guild.create_text_channel(
                name=f"\u23f2\ufe0f{ch_name}",
                category=category,
            )
            await channel.edit(sync_permissions=True)
            break
        except disnake.HTTPException as exc:
            if "Maximum number of channels" in str(exc):
                continue
            raise

    if channel is None:
        await send_error("```diff\n- Could not create event channel (all categories full).```")
        return

    evt = Event(
        channel_id=str(channel.id),
        target_id=target.id if target else None,
        name=target_name,
        created_at=now.replace(tzinfo=None),
        dkp=dkp_value or (target.value if target else 0) or 0,
        nokill_dkp=dkp_nokill_value or (target.nokill_value if target else 0) or 0,
    )
    session.add(evt)
    session.flush()

    tracking_msgs = rte_tracking_creator(evt, target, child_target, session, target_name=target_name)

    output_lines: list[str] = []
    if target:
        output_lines.extend(build_target_loot_table_lines(evt, target, session))
    else:
        msg = "This event has no target currently set."
        if targets and len(targets) > 1:
            msg = f"Multiple targets found ({', '.join(t.name for t in targets)})"
        output_lines.append(f"```diff\n- {msg} Please use /event target to set the proper target.```")

    output_lines.extend(
        [
            "> **What's next?**",
            ">   - Check out available commands using `$help`.",
            ">   - Submit logs to add attendees by pasting or uploading files.",
            ">   - Add individual players using `+Player` or `+Player reason`.",
            ">      - Indicate a bot with `+Player on Bot`",
            ">   - Record loot using `$loot <item> <character> <dkp>`",
            "",
            f"Started By: {started_by}",
        ]
    )

    msg_obj = await channel.send("\n".join(output_lines))
    evt.first_message_id = str(msg_obj.id)
    session.commit()

    tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
    for tmsg in tracking_msgs:
        tracking_ch = guild.get_channel(tracking_ch_id) if tracking_ch_id else None
        if tracking_ch:
            await tracking_ch.send(tmsg)

    return channel


@event.sub_command(description="Set the target for the current event.")
async def target(
    inter: disnake.ApplicationCommandInteraction,
    name: str = disnake.ext.commands.Param(description="Target name", autocomplete=True),
):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "target", guild_id):
        await inter.response.send_message("```diff\n- You do not have permission.```", ephemeral=True)
        return

    await inter.response.defer()
    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel.id)).first()
        if not evt:
            await inter.followup.send("```diff\n- No event found for this channel.```", ephemeral=True)
            return

        targets, _ = resolve_target(name, session)
        if len(targets) > 1:
            names = ", ".join(t.name for t in targets)
            await inter.followup.send(
                f"```diff\n- Multiple targets found ({names}). Be more specific.```", ephemeral=True
            )
            return
        if not targets:
            await inter.followup.send(
                "```diff\n- Target not found. Use /event targets to see available targets.```", ephemeral=True
            )
            return

        tgt = targets[0]
        old_target_id = evt.target_id
        display_name = get_shortest_alias(tgt, session)

        evt.name = display_name
        evt.target_id = tgt.id
        evt.dkp = tgt.value
        evt.nokill_dkp = tgt.nokill_value
        session.flush()

        emoji = "\U0001f480" if evt.killed is True else ("\u26d4" if evt.killed is False else "\u23f2\ufe0f")

        try:
            output = build_target_loot_table_lines(evt, tgt, session)
            if evt.first_message_id:
                try:
                    first_msg = await inter.channel.fetch_message(int(evt.first_message_id))
                    await first_msg.edit(content="\n".join(output))
                except (disnake.NotFound, disnake.HTTPException):
                    pass
        except Exception:
            logger.exception("Failed to update first message")

        if old_target_id:
            session.query(Attendee).filter(Attendee.event_id == evt.id, Attendee.tracking_id.isnot(None)).delete(
                synchronize_session="fetch"
            )

        tracking_msgs = rte_tracking_creator(evt, tgt, None, session, target_name=display_name)
        session.commit()

        try:
            await inter.channel.edit(name=f"{emoji}{evt.channel_name}")
        except disnake.HTTPException:
            pass

        await inter.followup.send(
            f"```diff\n+ Target is changed to {tgt.name}. DKP value is {tgt.dkp_value(True)}. No kill value is {tgt.dkp_value(False)}.```"
        )

        tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
        tracking_ch = inter.guild.get_channel(tracking_ch_id) if tracking_ch_id else None
        if tracking_ch:
            for tmsg in tracking_msgs:
                await tracking_ch.send(tmsg)


@event.sub_command(description="List all available targets.")
async def targets(inter: disnake.ApplicationCommandInteraction):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "targets", guild_id):
        await inter.response.send_message(
            "```diff\n- You do not have permission to access that command.```", ephemeral=True
        )
        return
    with get_raid_session(guild_id) as session:
        all_targets = session.query(Target).filter_by(parent="").all()
        lines = []
        for tgt in all_targets:
            aliases = session.query(TargetAlias).filter_by(target_id=tgt.id).all()
            out = tgt.name
            if aliases:
                out += f" ({', '.join(a.name for a in aliases)})"
            if tgt.value is not None:
                out += f", DKP: {tgt.value}, Nokill: {tgt.nokill_value}"
            lines.append(out)

        if not lines:
            await inter.response.send_message("No targets configured.", ephemeral=True)
            return

        embed = disnake.Embed(title="Target List")
        buf, texts = "", []
        for line in lines:
            if len(buf + line + "\n") > 900:
                texts.append(buf)
                buf = ""
            buf += line + "\n"
        if buf:
            texts.append(buf)
        for i, text in enumerate(texts):
            embed.add_field(
                name="Targets" if i == 0 else "Targets (cont.)",
                value=f"```diff\n{text}```",
                inline=False,
            )

        await inter.response.send_message(embed=embed, ephemeral=True)


def _count_pinned_in(category, pinned_ids: set) -> int:
    return sum(1 for ch in category.channels if ch.id in pinned_ids)


@event.sub_command(description="Reorder event channels across categories.")
async def reorder(inter: disnake.ApplicationCommandInteraction):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "reorder", guild_id):
        await inter.response.send_message(
            "```diff\n- You do not have permission to access that command.```", ephemeral=True
        )
        return

    event_category_ids = config.get_raid_setting(guild_id, "event_category_ids") or []
    if not event_category_ids:
        await inter.response.send_message("```diff\n- No event categories configured.```", ephemeral=True)
        return

    await inter.response.defer()

    pinned_channel_ids = {
        cid
        for cid in (
            config.get_raid_setting(guild_id, "tracking_channel_id"),
            config.get_raid_setting(guild_id, "create_event_channel_id"),
            config.get_raid_setting(guild_id, "uploaded_events_channel_id"),
            config.get_raid_setting(guild_id, "batphone_channel_id"),
            config.get_raid_setting(guild_id, "register_channel_id"),
            config.get_raid_setting(guild_id, "loot_channel_id"),
        )
        if cid
    }

    categories = []
    event_channels = []
    for cat_id in event_category_ids:
        category = inter.guild.get_channel(cat_id)
        if category is None:
            continue
        categories.append(category)
        event_channels.extend(
            sorted(
                [
                    ch
                    for ch in category.channels
                    if isinstance(ch, disnake.TextChannel) and ch.id not in pinned_channel_ids
                ],
                key=lambda c: c.position,
            )
        )

    if not categories:
        await inter.followup.send("```diff\n- No valid event categories found.```", ephemeral=True)
        return

    DISCORD_CATEGORY_LIMIT = 50
    cat_idx = 0
    position_in_cat = _count_pinned_in(categories[0], pinned_channel_ids)

    for channel in event_channels:
        if position_in_cat >= DISCORD_CATEGORY_LIMIT:
            cat_idx += 1
            if cat_idx >= len(categories):
                break
            position_in_cat = _count_pinned_in(categories[cat_idx], pinned_channel_ids)

        target_category = categories[cat_idx]
        needs_move = channel.category_id != target_category.id
        needs_reposition = channel.position != position_in_cat

        if needs_move or needs_reposition:
            try:
                kwargs = {"position": position_in_cat}
                if needs_move:
                    kwargs["category"] = target_category
                    kwargs["sync_permissions"] = True
                await channel.edit(**kwargs)
            except disnake.HTTPException as exc:
                logger.warning("Failed to reorder channel %s: %s", channel.name, exc)
            await asyncio.sleep(0.05)

        position_in_cat += 1

    await inter.followup.send("```diff\n+ Events have successfully been reordered.```")


# ---------------------------------------------------------------------------
# Message handlers: +Player, -Player, log paste, batphone
# ---------------------------------------------------------------------------


def _is_events_category(channel) -> bool:
    return hasattr(channel, "category") and channel.category and channel.category.name.startswith("Events")


@base.DISCORD_CLIENT.listen("on_message")
async def on_raid_message(message: disnake.Message):
    if not message.guild:
        return
    guild_id = message.guild.id
    if guild_id not in config.raid_guild_ids():
        return

    content = message.content or ""

    # Batphone trigger
    batphone_ch_id = config.get_raid_setting(guild_id, "batphone_channel_id")
    if batphone_ch_id and message.channel.id == batphone_ch_id and message.mention_everyone:
        await _handle_batphone(message)
        return

    # !register in the registration channel
    register_ch_id = config.get_raid_setting(guild_id, "register_channel_id")
    if content.strip().lower() == "!register" and register_ch_id and message.channel.id == register_ch_id:
        await _handle_register(message)
        return

    if not _is_events_category(message.channel):
        return

    if content.startswith("$"):
        await _handle_dollar_command(message)
        return

    if content.startswith(("!", "/")):
        return

    if content.startswith("+"):
        await _handle_add_player(message)
    elif content.startswith("-"):
        await _handle_remove_player(message)
    else:
        await _handle_log_parse(message)


async def _handle_add_player(message: disnake.Message):
    guild_id = message.guild.id
    lines = message.content.strip().split("\n")
    out = ["```diff"]

    eqdkp_client: EqdkpClient | None = None
    if config.eqdkp_is_configured(guild_id):
        eqdkp_client = EqdkpClient(guild_id)

    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(message.channel.id)).first()
        if not evt:
            return

        for line in lines:
            cleaned = re.sub(r"^\+", "", line).strip()
            if not cleaned:
                continue
            parts = cleaned.split(" ", 1)
            player_name = re.sub(r"[^A-Za-z]", "", parts[0]).capitalize()
            reason = parts[1].strip("() ") if len(parts) > 1 else ""

            if not player_name:
                continue

            char = session.query(Character).filter(Character.name.ilike(player_name)).first()
            if not char:
                char = Character(name=player_name)
                session.add(char)
                session.flush()

            # batphone-bot add_player.rb: only allow names that exist in EQdkp (lookup only; no auto-create).
            if eqdkp_client and not char.eqdkp_member_id:
                try:
                    member = await eqdkp_client.find_character(char.name)
                except Exception as exc:
                    logger.exception("EQdkp find_character failed for %s", char.name)
                    out.append(f"- {char.name}: EQdkp lookup failed ({exc}). Try again later.")
                    continue
                if member:
                    char.eqdkp_member_id = member.get("id")
                    char.eqdkp_user_id = member.get("user_id")
                    char.eqdkp_main_id = member.get("main_id")
                    session.flush()
                else:
                    out.append(
                        f"- Unable to locate the character {player_name} on EQDKP Site. "
                        "Please make sure that character exists there first."
                    )
                    continue

            existing = session.query(Attendee).filter_by(event_id=evt.id, character_id=str(char.id)).first()

            on_character = None
            on_match = re.match(r"^on\s+(.+)$", reason, re.IGNORECASE)
            if on_match:
                on_name = on_match.group(1).strip().capitalize()
                on_character = session.query(Character).filter(Character.name.ilike(on_name)).first()

            if on_character:
                on_existing = (
                    session.query(Attendee).filter_by(event_id=evt.id, on_character_id=str(on_character.id)).first()
                )
                if on_existing:
                    c = session.query(Character).filter_by(id=int(on_existing.character_id)).first()
                    out.append(f"- {c.name if c else '?'} is already on {on_character.name}")
                    continue

            if existing:
                out.append(f"- {char.name} already exists in this event")
                continue

            att = Attendee(event_id=evt.id, character_id=str(char.id), reason=reason)
            if on_character:
                att.on_character_id = str(on_character.id)
            session.add(att)
            session.flush()

            msg_text = f"+ {char.name} was added to this event"
            if reason:
                msg_text += f" (Reason: {reason})"
            out.append(msg_text)

            if on_character:
                dup = (
                    session.query(Attendee)
                    .filter_by(event_id=evt.id, character_id=str(on_character.id))
                    .filter(Attendee.on_character_id.is_(None))
                    .first()
                )
                if dup:
                    session.delete(dup)
                    out.append(f"- {on_character.name} was removed from this event")

        session.commit()
    out.append("```")
    await message.channel.send("\n".join(out))


async def _handle_remove_player(message: disnake.Message):
    guild_id = message.guild.id
    cleaned = re.sub(r"^-", "", message.content).strip()
    parts = cleaned.split(" ", 1)
    player_name = parts[0].strip()
    reason = parts[1].strip() if len(parts) > 1 else ""

    if not player_name:
        return

    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(message.channel.id)).first()
        if not evt:
            return

        char = session.query(Character).filter(Character.name.ilike(player_name)).first()
        if not char:
            await message.channel.send(f"```fix\n{player_name} does not exist```")
            return

        attendee = session.query(Attendee).filter_by(event_id=evt.id, character_id=str(char.id)).first()

        if attendee:
            session.delete(attendee)
            session.add(Removal(event_id=evt.id, character_id=char.id, reason=reason))
            session.commit()
            await message.channel.send(f"```diff\n+ {char.name} was removed from this event```")
        else:
            await message.channel.send(f"```fix\n{player_name} was not found on this event```")


async def _handle_log_parse(message: disnake.Message):
    guild_id = message.guild.id
    content = message.content or ""
    all_content = content

    for att in message.attachments:
        try:
            data = await att.read()
            all_content += "\n" + data.decode("utf-8", errors="replace")
        except Exception:
            logger.exception("Failed to read attachment")

    if not all_content.strip():
        return

    players, anon_players = parse_players_from_content(all_content, guild_id)
    if not players:
        return

    eqdkp_client: EqdkpClient | None = None
    if config.eqdkp_is_configured(guild_id):
        eqdkp_client = EqdkpClient(guild_id)

    not_in_eqdkp: list[str] = []
    eqdkp_lookup_errors: list[str] = []

    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(message.channel.id)).first()
        if not evt:
            return

        num_added = 0
        for p in players:
            member = None
            char = session.query(Character).filter(Character.name.ilike(p.name)).first()
            if not char:
                if eqdkp_client:
                    try:
                        member = await eqdkp_client.find_character(p.name)
                    except Exception as exc:
                        logger.exception("EQdkp find_character failed for %s", p.name)
                        eqdkp_lookup_errors.append(f"{p.name} ({exc})")
                        continue
                    if not member:
                        not_in_eqdkp.append(p.name)
                        continue
                char = Character(name=p.name, klass=p.klass)
                if member:
                    char.eqdkp_member_id = member.get("id")
                    char.eqdkp_user_id = member.get("user_id")
                    char.eqdkp_main_id = member.get("main_id")
                session.add(char)
                session.flush()
            else:
                if not char.klass and p.klass:
                    char.klass = p.klass
                if eqdkp_client and not char.eqdkp_member_id:
                    try:
                        member = await eqdkp_client.find_character(char.name)
                    except Exception as exc:
                        logger.exception("EQdkp find_character failed for %s", char.name)
                        eqdkp_lookup_errors.append(f"{char.name} ({exc})")
                        continue
                    if member:
                        char.eqdkp_member_id = member.get("id")
                        char.eqdkp_user_id = member.get("user_id")
                        char.eqdkp_main_id = member.get("main_id")
                        session.flush()
                    else:
                        not_in_eqdkp.append(char.name)
                        continue

            existing = session.query(Attendee).filter_by(event_id=evt.id, character_id=str(char.id)).first()
            if not existing:
                on_existing = session.query(Attendee).filter_by(event_id=evt.id, on_character_id=str(char.id)).first()
                if not on_existing:
                    session.add(Attendee(event_id=evt.id, character_id=str(char.id)))
                    num_added += 1

        session.commit()

    out = ["```diff", f"+ Log Parsed. {num_added} players added."]
    if not_in_eqdkp:
        out.extend(["", "- The following were not found on EQdkp and were skipped:", ""])
        for name in not_in_eqdkp:
            out.append(f"-  {name}")
    if eqdkp_lookup_errors:
        out.extend(["", "- EQdkp lookup failed for (try again later):", ""])
        for line in eqdkp_lookup_errors:
            out.append(f"-  {line}")
    if anon_players:
        out.extend(
            [
                "",
                "- The following players were not added (anonymous and never seen before):",
                "",
            ]
        )
        for p in anon_players:
            out.append(f"-  {p.name}")
    out.append("```")
    await message.channel.send("\n".join(out))


async def _handle_batphone(message: disnake.Message):
    guild_id = message.guild.id
    content = message.content or ""
    channel_name = re.sub(r"@everyone", "", content)
    channel_name = re.sub(r"!alert", "", channel_name).strip()
    parts = re.split(r"[\r\n]", channel_name)
    if len(parts) > 1:
        channel_name = parts[0]

    opts: dict = {"s": 18}
    if "!alert" in content:
        opts["pr"] = 2
        opts["v"] = 3

    with get_raid_session(guild_id) as session:
        # Pass 1: exact per-word match (matches original Ruby send_batphone.rb)
        tgt = None
        for fragment in channel_name.split():
            fragment_lower = fragment.lower()
            alias_match = session.query(TargetAlias).filter(TargetAlias.name.ilike(fragment_lower)).all()
            name_match = session.query(Target).filter(Target.name.ilike(fragment_lower)).all()
            combined = name_match[:]
            if alias_match:
                alias_ids = [a.target_id for a in alias_match]
                combined.extend(session.query(Target).filter(Target.id.in_(alias_ids)).all())
            unique = list({t.id: t for t in combined}.values())
            if len(unique) == 1:
                tgt = unique[0]
                break

        # Pass 2: substring match on full channel_name (matches Ruby create_event.rb fallback)
        if tgt is None:
            targets, _ = resolve_target(channel_name, session)
            if len(targets) == 1:
                tgt = targets[0]

        should_send = True
        if tgt and tgt.last_batphone_at:
            if (datetime.now(timezone.utc).replace(tzinfo=None) - tgt.last_batphone_at).total_seconds() < 30:
                should_send = False

        if should_send and config.get_raid_setting(guild_id, "send_batphone"):
            send_batphone(
                config.get_pushsafer_setting(guild_id, "title") or "Batphone",
                str(message.content),
                guild_id,
                opts=opts,
            )

        if tgt and should_send:
            tgt.last_batphone_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session.commit()

        if config.get_raid_setting(guild_id, "create_channels"):
            if _is_locked_out(tgt, session):
                logger.info("Batphone for %s skipped (lockout)", channel_name)
                return

            display_name = channel_name
            if tgt:
                display_name = get_shortest_alias(tgt, session)

            children = []
            if tgt:
                children = session.query(Target).filter_by(parent=tgt.name).all()

            if children:
                for child in children:
                    await _perform_create_event(
                        message.guild,
                        message.author.display_name,
                        message.channel.send,
                        session,
                        f"{display_name} - {child.name}",
                        target=tgt,
                        channel_name=f"{display_name} {child.name}",
                        dkp_value=child.value,
                        dkp_nokill_value=child.nokill_value or child.value,
                        child_target=child,
                    )
            else:
                await _perform_create_event(
                    message.guild,
                    message.author.display_name,
                    message.channel.send,
                    session,
                    display_name,
                    target=tgt,
                    targets=[tgt] if tgt else [],
                )


# ---------------------------------------------------------------------------
# $command text handlers for event channels
# ---------------------------------------------------------------------------

_DOLLAR_COMMANDS: dict[str, object] = {}


async def _handle_dollar_command(message: disnake.Message):
    content = (message.content or "").strip()
    parts = content[1:].split(None, 1)
    if not parts:
        return
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    handler = _DOLLAR_COMMANDS.get(cmd)
    if handler:
        await handler(message, args)


def _dollar(name):
    """Decorator to register a $command handler."""

    def decorator(func):
        _DOLLAR_COMMANDS[name] = func
        return func

    return decorator


def _get_event(session, channel_id: str) -> Event | None:
    return session.query(Event).filter_by(channel_id=channel_id).first()


@_dollar("kill")
async def _cmd_kill(message: disnake.Message, _args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "kill", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    dkp_val: int | None = None
    rename_name: str | None = None
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        result = apply_kill_state_to_event(evt, True, set_tod_if_missing=False)
        if not result.status_changed:
            await message.channel.send("```diff\n+ No change: the target is already marked as killed.```")
            return
        session.commit()
        dkp_val = result.dkp_value
        if dkp_val is not None:
            rename_name = event_channel_name_with_kill_prefix(evt, True)
    if dkp_val is None:
        await message.channel.send(
            "```diff\n- Must specify a target or dkp value using the `/event target` or $dkp command before you can mark as killed.```"
        )
        return
    await message.channel.send(f"```diff\n+ Target was marked as a kill. DKP reward will be {dkp_val}.```")
    if rename_name is not None:
        await rename_event_channel_for_kill_name(message.channel, rename_name)


@_dollar("nokill")
async def _cmd_nokill(message: disnake.Message, _args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "nokill", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    dkp_val: int | None = None
    rename_name: str | None = None
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        result = apply_kill_state_to_event(evt, False, set_tod_if_missing=False)
        if not result.status_changed:
            await message.channel.send("```diff\n+ No change: the target is already marked as not killed.```")
            return
        session.commit()
        dkp_val = result.dkp_value
        if dkp_val is not None:
            rename_name = event_channel_name_with_kill_prefix(evt, False)
    if dkp_val is None:
        await message.channel.send(
            "```diff\n- Must specify a target or dkp value using the `/event target` or $dkp command before you can mark as not killed.```"
        )
        return
    await message.channel.send(f"```diff\n+ Target was marked as not killed. DKP reward will be {dkp_val}.```")
    if rename_name is not None:
        await rename_event_channel_for_kill_name(message.channel, rename_name)


@_dollar("dkp")
async def _cmd_dkp(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "dkp", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    parts = args.split()
    if not parts or not parts[0].lstrip("-").isdigit():
        await message.channel.send("```diff\n- Usage: $dkp <value> [nokill_value]```")
        return
    value = int(parts[0])
    nokill_value = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else value
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        evt.dkp = value
        evt.nokill_dkp = nokill_value
        session.commit()
        await message.channel.send(f"```diff\n+ DKP set to {value}, no-kill DKP set to {nokill_value}.```")


@_dollar("status")
async def _cmd_status(message: disnake.Message, _args: str):
    guild_id = message.guild.id
    with get_raid_session(guild_id) as session:
        if not _get_event(session, str(message.channel.id)):
            return
    embed = build_raid_status_embed(str(message.channel.id), guild_id)
    await message.channel.send(embed=embed)


@_dollar("submit")
async def _cmd_submit(message: disnake.Message, args: str):
    guild_id = message.guild.id
    args_lower = args.strip().lower()
    if args_lower == "reset":
        await _cmd_submit_reset(message)
        return

    if not perms.can(message.author, "submit", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return

    force = args_lower == "force"
    async with message.channel.typing():
        from roboToald.eqdkp.client import EqdkpClient

        eqdkp = EqdkpClient(guild_id)

        with get_raid_session(guild_id) as session:
            evt = _get_event(session, str(message.channel.id))
            if not evt:
                await message.channel.send("```diff\n- No event here.```")
                return
            if evt.eqdkp_event_id and evt.eqdkp_raid_id:
                await message.channel.send("```diff\n- Already submitted. Use $submit reset first.```")
                return
            if evt.killed is None:
                await message.channel.send("```diff\n- Use $kill or $nokill first.```")
                return
            if evt.killed and not force and (evt.dkp or 0) == 0:
                await message.channel.send("```fix\nDKP is 0. Use $submit force or set DKP with $dkp.```")
                return

            try:
                tgt = session.query(Target).get(evt.target_id) if evt.target_id else None
                event_name = tgt.name if tgt else evt.name

                eqdkp_evt = session.query(EqdkpEvent).filter(EqdkpEvent.name.ilike(event_name)).first()
                if not eqdkp_evt or not eqdkp_evt.eqdkp_event_id:
                    new_id = await eqdkp.create_event(event_name, evt.dkp_value or 0)
                    if not eqdkp_evt:
                        eqdkp_evt = EqdkpEvent(name=event_name, eqdkp_event_id=str(new_id))
                        session.add(eqdkp_evt)
                    else:
                        eqdkp_evt.eqdkp_event_id = str(new_id)
                    session.flush()
                evt.eqdkp_event_id = int(eqdkp_evt.eqdkp_event_id)

                attendees = session.query(Attendee).filter_by(event_id=evt.id, tracking_id=None).all()
                characters = []
                for att in attendees:
                    char = (
                        session.query(Character).filter_by(id=int(att.character_id)).first()
                        if att.character_id
                        else None
                    )
                    if char:
                        char = await eqdkp.create_member(char, session=session)
                        characters.append(char)

                members_by_user = list({c.eqdkp_user_id: c for c in characters if c.eqdkp_member_id}.values())

                # batphone-bot eqdkp_publisher: if no attendees and DKP is 0, use loot buyers as raid members.
                if not members_by_user and (evt.dkp_value or 0) == 0:
                    for el in session.query(EventLoot).filter_by(event_id=evt.id).all():
                        char = (
                            session.query(Character).filter_by(id=int(el.character_id)).first()
                            if el.character_id
                            else None
                        )
                        if char:
                            char = await eqdkp.create_member(char, session=session)
                            characters.append(char)
                    members_by_user = list({c.eqdkp_user_id: c for c in characters if c.eqdkp_member_id}.values())

                raid_roster_from_fte_merge = False
                if not members_by_user:
                    for fte_rec in session.query(Fte).filter_by(event_id=evt.id).all():
                        char = session.query(Character).get(fte_rec.character_id) if fte_rec.character_id else None
                        if char:
                            char = await eqdkp.create_member(char, session=session)
                            characters.append(char)
                    members_by_user = list({c.eqdkp_user_id: c for c in characters if c.eqdkp_member_id}.values())
                    if members_by_user:
                        raid_roster_from_fte_merge = True

                if not members_by_user:
                    await message.channel.send(
                        "```diff\n- EQdkp requires at least one raid member. "
                        "Add attendees, loot with a buyer, or FTE before submitting.```"
                    )
                    return

                raid_value = 0 if raid_roster_from_fte_merge else (evt.dkp_value or 0)

                kill_msg = "Killed" if evt.killed else "Not Killed"
                raid_note = (
                    f"{evt.created_at.strftime('%Y%m%d-%I%M')}-{evt.name} {kill_msg}" if evt.created_at else evt.name
                )
                raid_id = await eqdkp.create_raid(
                    evt.eqdkp_event_id,
                    raid_value,
                    raid_note,
                    [c.eqdkp_member_id for c in members_by_user],
                )
                evt.eqdkp_raid_id = raid_id

                rte_attendees = (
                    session.query(Attendee).filter(Attendee.event_id == evt.id, Attendee.tracking_id.isnot(None)).all()
                )
                for att in rte_attendees:
                    char = (
                        session.query(Character).filter_by(id=int(att.character_id)).first()
                        if att.character_id
                        else None
                    )
                    if not char:
                        continue
                    char = await eqdkp.create_member(char, session=session)
                    other_chars = session.query(Character).filter_by(eqdkp_user_id=char.eqdkp_user_id).all()
                    other_ids = [str(c.id) for c in other_chars]
                    other_att = (
                        session.query(Attendee)
                        .filter(
                            Attendee.event_id == evt.id,
                            Attendee.id != att.id,
                            Attendee.character_id.in_(other_ids),
                        )
                        .first()
                    )
                    if not other_att and char.eqdkp_member_id:
                        await eqdkp.add_adjustment(
                            char.eqdkp_member_id,
                            evt.dkp_value or 0,
                            f"RTE {evt.target_name}",
                            raid_id=raid_id,
                        )

                ftes = session.query(Fte).filter_by(event_id=evt.id).all()
                for fte_rec in ftes:
                    char = session.query(Character).get(fte_rec.character_id) if fte_rec.character_id else None
                    if char:
                        char = await eqdkp.create_member(char, session=session)
                        if char.eqdkp_member_id:
                            await eqdkp.add_adjustment(
                                char.eqdkp_member_id,
                                fte_rec.dkp,
                                f"FTE {evt.target_name}",
                                raid_id=raid_id,
                            )

                event_loots = session.query(EventLoot).filter_by(event_id=evt.id).all()
                for el in event_loots:
                    if el.eqdkp_item_id:
                        continue
                    loot_rec = session.query(Loot).get(el.loot_id) if el.loot_id else None
                    char = session.query(Character).get(el.character_id) if el.character_id else None
                    if loot_rec and char:
                        char = await eqdkp.create_member(char, session=session)
                        if char.eqdkp_member_id:
                            item_id = await eqdkp.add_item(
                                loot_rec.name,
                                el.dkp or 0,
                                char.eqdkp_member_id,
                                raid_id,
                                item_date=el.created_at,
                            )
                            el.eqdkp_item_id = item_id

                session.commit()
                await message.channel.send("```diff\n+ Event submitted to EQdkp.```")

                uploaded_ch_id = config.get_raid_setting(guild_id, "uploaded_events_channel_id")
                uploaded_ch = message.guild.get_channel(uploaded_ch_id) if uploaded_ch_id else None
                if uploaded_ch:
                    emoji = "\U0001f480" if evt.killed else "\u26d4"
                    msg = await uploaded_ch.send(f"{emoji}{evt.channel_name}")
                    thread = await msg.create_thread(name=f"{emoji}{evt.channel_name}", auto_archive_duration=60)
                    embed = build_raid_status_embed(str(message.channel.id), guild_id)
                    await thread.send(embed=embed)

            except Exception as exc:
                logger.exception("EQdkp submission failed")
                await message.channel.send(f"```diff\n- Error submitting to EQdkp: {exc}```")


async def _cmd_submit_reset(message: disnake.Message):
    guild_id = message.guild.id
    if not perms.can(message.author, "submit", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if evt:
            evt.eqdkp_raid_id = None
            evt.eqdkp_event_id = None
            session.commit()
    await message.channel.send(
        "```diff\n+ Event reset. Make sure to delete the existing raid in EQdkp before resubmitting.```"
    )


@_dollar("delete-event")
async def _cmd_delete_event(message: disnake.Message, _args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "delete_event", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    with get_raid_session(guild_id) as session:
        if not _get_event(session, str(message.channel.id)):
            return
    await message.channel.send("Deleting channel...")
    await message.channel.delete()


@_dollar("clear")
async def _cmd_clear(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "clear", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    what = args.strip().lower()
    if what not in ("attendees", "loot", "rte"):
        await message.channel.send("```diff\n- Usage: $clear [attendees|loot|rte]```")
        return
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        if what == "attendees":
            session.query(Attendee).filter_by(event_id=evt.id).delete()
            session.commit()
            await message.channel.send("```diff\n+ Attendee list cleared.```")
        elif what == "loot":
            session.query(EventLoot).filter_by(event_id=evt.id).delete()
            session.commit()
            await message.channel.send("```diff\n+ Loot cleared.```")
        elif what == "rte":
            tgt = session.query(Target).get(evt.target_id) if evt.target_id else None
            if tgt:
                session.query(Tracking).filter_by(target_id=tgt.id, end_time=None).update(
                    {"end_time": datetime.now(timezone.utc)}
                )
                session.commit()
                await message.channel.send(f"```diff\n+ All active RTE for {tgt.name} closed.```")
            else:
                await message.channel.send("```diff\n- Set a target first.```")


@_dollar("target")
async def _cmd_target(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "target", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    name = args.strip()
    if not name:
        await message.channel.send("```diff\n- Usage: $target <name>```")
        return

    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event found for this channel.```")
            return

        targets, _ = resolve_target(name, session)
        if len(targets) > 1:
            names = ", ".join(t.name for t in targets)
            await message.channel.send(
                f"```diff\n- Multiple targets were found for this event ({names}). Please be more specific.```"
            )
            return
        if not targets:
            await message.channel.send(
                "```diff\n- We are sorry but that target was not found. Please try again or use `/event targets` to see the list.```"
            )
            return

        tgt = targets[0]
        old_target_id = evt.target_id
        display_name = get_shortest_alias(tgt, session)

        evt.name = display_name
        evt.target_id = tgt.id
        evt.dkp = tgt.value
        evt.nokill_dkp = tgt.nokill_value
        session.flush()

        emoji = "\U0001f480" if evt.killed is True else ("\u26d4" if evt.killed is False else "\u23f2\ufe0f")

        try:
            output = build_target_loot_table_lines(evt, tgt, session)
            if evt.first_message_id:
                try:
                    first_msg = await message.channel.fetch_message(int(evt.first_message_id))
                    await first_msg.edit(content="\n".join(output))
                except (disnake.NotFound, disnake.HTTPException):
                    pass
        except Exception:
            logger.exception("Failed to update first message")

        if old_target_id:
            session.query(Attendee).filter(Attendee.event_id == evt.id, Attendee.tracking_id.isnot(None)).delete(
                synchronize_session="fetch"
            )

        tracking_msgs = rte_tracking_creator(evt, tgt, None, session, target_name=display_name)
        session.commit()

        try:
            await message.channel.edit(name=f"{emoji}{evt.channel_name}")
        except disnake.HTTPException:
            pass

        await message.channel.send(
            f"```diff\n+ Target is changed to {tgt.name}. DKP value is {tgt.dkp_value(True)}. No kill value is {tgt.dkp_value(False)}.```"
        )

        tracking_ch_id = config.get_raid_setting(guild_id, "tracking_channel_id")
        tracking_ch = message.guild.get_channel(tracking_ch_id) if tracking_ch_id else None
        if tracking_ch:
            for tmsg in tracking_msgs:
                await tracking_ch.send(tmsg)


@_dollar("loot")
async def _cmd_loot(message: disnake.Message, args: str):
    """$loot <item name/ID> <player> <dkp> -- Ruby style: DKP last, then name, rest is item."""
    if not args.strip():
        await message.channel.send(
            "```\n$loot [item name/ID] [player name] [dkp value]\n\n"
            "Examples:\n\n$loot Shield of Awesome Sauce Nanae 10\n"
            "$loot 44572 Nanae 10\n"
            "$loot https://wiki.project1999.com/Scepter_of_the_Forlorn Nanae 100\n```"
        )
        return

    guild_id = message.guild.id
    # Ruby parsing: split from right -- dkp (last), player (second-to-last), item (rest)
    parts = args.rsplit(None, 2)
    if len(parts) < 3:
        await message.channel.send("```diff\n- Usage: $loot <item> <character> <dkp>```")
        return

    item_str, character, dkp_str = parts
    if not dkp_str.lstrip("-").isdigit():
        await message.channel.send("```diff\n- DKP value must be a number.```")
        return
    dkp_value = int(dkp_str)

    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event found for this channel.```")
            return

        item_record = _resolve_item(item_str, session)
        if isinstance(item_record, str):
            await message.channel.send(item_record)
            return

        char = session.query(Character).filter(Character.name.ilike(character)).first()
        if not char:
            await message.channel.send(f"```diff\n- {character} not found. Add them with +Player first.```")
            return

        attendee = session.query(Attendee).filter_by(event_id=evt.id, character_id=str(char.id)).first()

        loot_rec = session.query(Loot).filter_by(item_id=item_record.id).first()
        if not loot_rec:
            loot_rec = Loot(item_id=item_record.id, name=item_record.name)
            session.add(loot_rec)
            session.flush()

        el = EventLoot(
            event_id=evt.id,
            attendee_id=attendee.id if attendee else None,
            character_id=char.id,
            loot_id=loot_rec.id,
            item_id=item_record.id,
            dkp=dkp_value,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        session.add(el)
        session.commit()

        out = [f"```diff\n+ {item_record.name} won by {char.name} for {dkp_value} DKP. Grats!"]
        if not attendee:
            out.append(f"\n- Note: {char.name} is not on the attendee list for this event.")
        out.append("```")
        await message.channel.send("\n".join(out))


def _resolve_item(item_str: str, session) -> Item | str:
    """Resolve an item by ID, wiki URL, or name search. Returns Item or error string."""
    item_name = item_str.strip()
    if item_name.isdigit():
        record = session.query(Item).get(int(item_name))
        if record:
            return record
        return f"```diff\n- Item ID {item_name} not found.```"

    wiki_match = re.match(r"https?://wiki\.project1999\.com/(.*)", item_name)
    if wiki_match:
        item_name = wiki_match.group(1).replace("_", " ")

    candidates = session.query(Item).filter(Item.name.ilike(f"%{item_name.lower()}%")).all()
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        exact = [c for c in candidates if c.name.lower() == item_name.lower()]
        if exact:
            return exact[0]
        lines = ["```diff", "- Multiple items found (showing first 10):"]
        for c in candidates[:10]:
            lines.append(f"- {c.name} (ID: {c.id})")
        lines.append("```")
        return "\n".join(lines)

    return f"```diff\n- Item '{item_str}' not found. Use an item ID or more specific name.```"


@_dollar("unloot")
async def _cmd_unloot(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "unloot", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    loot_id_str = args.strip()
    if not loot_id_str.isdigit():
        await message.channel.send("```diff\n- Usage: $unloot <ID>```")
        return
    loot_id = int(loot_id_str)
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        el = session.query(EventLoot).filter_by(event_id=evt.id, id=loot_id).first()
        if not el:
            await message.channel.send(f"```diff\n- Loot ID {loot_id} not found.```")
            return
        item = session.query(Item).get(el.item_id) if el.item_id else None
        char = session.query(Character).get(el.character_id) if el.character_id else None
        item_name = item.name if item else "?"
        char_name = char.name if char else "?"
        el_dkp = el.dkp or 0
        session.delete(el)
        session.commit()
        await message.channel.send(f"```diff\n+ Loot ID {loot_id} removed. ({item_name}, {char_name}, {el_dkp})```")


@_dollar("fte")
async def _cmd_fte(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "fte", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    parts = args.strip().split()
    if len(parts) < 2 or not parts[-1].lstrip("-").isdigit():
        await message.channel.send("```diff\n- Usage: $fte <character> <dkp>```")
        return
    character = parts[0]
    dkp_value = int(parts[1])
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        char = session.query(Character).filter(Character.name.ilike(character)).first()
        if not char:
            await message.channel.send(f"```diff\n- Character {character} not found.```")
            return
        fte_rec = Fte(event_id=evt.id, character_id=char.id, dkp=dkp_value)
        session.add(fte_rec)
        session.commit()
        await message.channel.send(f"```diff\n+ {char.name} awarded {dkp_value} DKP for FTE on {evt.target_name}.```")


@_dollar("unfte")
async def _cmd_unfte(message: disnake.Message, args: str):
    guild_id = message.guild.id
    if not perms.can(message.author, "unfte", guild_id):
        await message.channel.send("```diff\n- You do not have permission to access that command.```")
        return
    fte_id_str = args.strip()
    if not fte_id_str.isdigit():
        await message.channel.send("```diff\n- Usage: $unfte <ID>```")
        return
    fte_id = int(fte_id_str)
    with get_raid_session(guild_id) as session:
        evt = _get_event(session, str(message.channel.id))
        if not evt:
            await message.channel.send("```diff\n- No event here.```")
            return
        fte_rec = session.query(Fte).filter_by(event_id=evt.id, id=fte_id).first()
        if not fte_rec:
            await message.channel.send(f"```diff\n- FTE ID {fte_id} not found.```")
            return
        char = session.query(Character).get(fte_rec.character_id)
        char_name = char.name if char else "?"
        fte_dkp = fte_rec.dkp or 0
        session.delete(fte_rec)
        session.commit()
        await message.channel.send(f"```diff\n+ FTE ID {fte_id} removed. ({char_name}, {fte_dkp})```")


# ---------------------------------------------------------------------------
# $help command
# ---------------------------------------------------------------------------

_HELP_TEXTS: dict[str, str] = {
    "kill": ("```\n$kill\n\nMarks the target as killed.\n```"),
    "nokill": ("```\n$nokill\n\nMarks the target as not killed.\n```"),
    "dkp": (
        "```\n$dkp [value] [nokill value:optional]\n\n"
        "Sets the dkp and nokill dkp value for this event.\n\n"
        "Examples:\n\n$dkp 10\n$dkp 10 5\n```"
    ),
    "status": ("```\n$status\n\nShow the current tracking and readiness status.\n\nExamples:\n\n$status\n```"),
    "submit": (
        "```\n$submit\n$submit reset\n$submit force\n\n"
        "Submits this event to EQdkp. Use 'reset' to clear EQdkp IDs for "
        "resubmission, or 'force' to submit even if DKP is 0.\n```"
    ),
    "delete-event": ("```\n$delete-event\n\nDeletes this event channel.\n```"),
    "clear": (
        "```\n$clear [attendees|loot|rte]\n\n"
        "This command will remove all of the objects for the given command value.\n\n"
        "Examples:\n\n$clear attendees\n$clear loot\n$clear rte\n```"
    ),
    "target": (
        "```\n$target [target name]\n\n"
        "Sets the target for this event to the specified target.\n\n"
        "Examples:\n\n$target Vulak\n```"
    ),
    "loot": (
        "```\n$loot [item name/ID] [player name] [dkp value]\n\n"
        "Registers that a specific player recieved a specific item for a specified value.\n\n"
        "Examples:\n\n$loot Shield of Awesome Sauce Nanae 10\n"
        "$loot 44572 Nanae 10\n"
        "$loot https://wiki.project1999.com/Scepter_of_the_Forlorn Nanae 100\n```"
    ),
    "unloot": (
        "```\n$unloot [ID]\n\n"
        "Removes specific loot from this event by the EventLoot ID. "
        "Use $status to see EventLoot IDs.\n\n"
        "Examples:\n\n$unloot 5\n```"
    ),
    "fte": (
        "```\n$fte [Character] [DKP]\n\n"
        "Award a specific character an amount of DKP for FTE.\n\n"
        "Examples:\n\n$fte Nanae 10\n```"
    ),
    "unfte": ("```\n$unfte [ID]\n\nRemoves an FTE by ID.\n\nExamples:\n\n$unfte 123\n```"),
    "+": (
        "```\n+[Character] [Reason:optional]\n+[Character] on [Bot]\n\n"
        "Adds a character to this event, with an optional reason or "
        "attending as an alternate character or bot.\n"
        "If EQdkp is configured for this guild, the character must already exist on the EQdkp site.\n\n"
        "Examples:\n\n+Nanae\n+Nanae on Healbox\n+Nanae porting everyone\n```"
    ),
    "-": ("```\n-[Character]\n\nRemoves a character from this event.\n\nExamples:\n\n-Nanae\n```"),
}

_HELP_OVERVIEW = (
    "```\nAvailable commands in event channels:\n\n"
    "  $kill             Mark target as killed\n"
    "  $nokill           Mark target as not killed\n"
    "  $dkp              Set DKP value\n"
    "  $status           Show raid status\n"
    "  $target           Change event target\n"
    "  $loot             Record loot\n"
    "  $unloot           Remove loot\n"
    "  $fte              Award FTE DKP\n"
    "  $unfte            Remove FTE\n"
    "  $submit           Submit to EQdkp\n"
    "  $clear            Clear attendees/loot/rte\n"
    "  $delete-event     Delete this channel\n"
    "  +Player           Add a player\n"
    "  -Player           Remove a player\n\n"
    "  Paste or upload EQ log to parse attendees.\n\n"
    "Use $help <command> for details.\n```"
)


@_dollar("help")
async def _cmd_help(message: disnake.Message, args: str):
    topic = args.strip().lower().lstrip("$")
    if topic and topic in _HELP_TEXTS:
        await message.channel.send(_HELP_TEXTS[topic])
    elif topic:
        await message.channel.send(
            "```diff\n- That command was not found. Please see available commands by using $help```"
        )
    else:
        await message.channel.send(_HELP_OVERVIEW)


# ---------------------------------------------------------------------------
# !register message command (matches Ruby bot behavior)
# ---------------------------------------------------------------------------


async def _handle_register(message: disnake.Message):
    guild_id = message.guild.id
    guest_id = config.get_pushsafer_setting(guild_id, "guest_id")
    if not guest_id:
        return

    try:
        import qrcode
    except ImportError:
        logger.warning("qrcode library not installed")
        return

    data = f"{guest_id}|{message.author.name}__{message.author.display_name}|"
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=6,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    instructions = (
        "** **\n"
        "1.) Download the PushSafer app.\n"
        "2.) Open app and use the in-app function to scan the following QR code.\n"
        "\n"
        "**It is not required to create a Pushsafer account. "
        "QR code is specific to you, so DO NOT share it.**\n"
        "\n"
        "Apple: <https://itunes.apple.com/app/pushsafer/id1096581405>\n"
        "\n"
        "Android: <https://play.google.com/store/apps/details?id=de.appzer.Pushsafer>"
    )

    try:
        await message.author.send(
            instructions,
            file=disnake.File(buf, filename="batphone.png"),
        )
    except disnake.Forbidden:
        pass

    try:
        await message.delete()
    except disnake.HTTPException:
        pass


# ---------------------------------------------------------------------------
# /event reload
# ---------------------------------------------------------------------------


def _get_gspread_client():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CONFIG_FILE,
        scopes=scopes,
    )
    return gspread.authorize(creds)


@event.sub_command(description="Reload config from Google Sheets")
async def reload(
    inter: disnake.ApplicationCommandInteraction,
    what: str = disnake.ext.commands.Param(
        description="What to reload",
        choices=["all", "targets", "aliases", "permissions", "loot_tables", "loot_groups"],
        default="all",
    ),
):
    guild_id = inter.guild.id
    is_allowed = perms.can(inter.author, "reload", guild_id) or str(inter.author.id) in (
        config.get_raid_setting(guild_id, "allowed_reload_ids") or []
    )
    if not is_allowed:
        await inter.response.send_message(
            "```diff\n- You do not have permission to access that command.```", ephemeral=True
        )
        return

    await inter.response.defer()

    try:
        gc = _get_gspread_client()
        spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_SPREADSHEET_ID)
        worksheets = spreadsheet.worksheets()
    except Exception as exc:
        logger.exception("Failed to connect to Google Sheets")
        await inter.followup.send(f"```diff\n- Google Sheets error: {exc}```")
        return

    do_targets = what in ("all", "targets")
    do_aliases = what in ("all", "aliases")
    do_permissions = what in ("all", "permissions")
    do_loot_tables = what in ("all", "loot_tables")
    do_loot_groups = what in ("all", "loot_groups")

    not_found: list[str] = []
    loot_stats = {"existing": 0, "new": 0, "deleted": 0}

    with get_raid_session(guild_id) as session:
        rte_start = 11

        if do_targets:
            ws = worksheets[0]
            rows = ws.get_all_values()
            session.query(Target).delete()
            session.flush()

            for row in rows[1:]:
                if len(row) < 2 or not row[1].strip():
                    continue

                target_id_str = row[0].strip()
                target_name = row[1].strip()
                tier_name = row[2].strip() if len(row) > 2 else ""

                tier = session.query(Tier).filter_by(name=tier_name).first() if tier_name else None
                if tier_name and not tier:
                    tier = Tier(name=tier_name)
                    session.add(tier)
                    session.flush()

                kwargs = {
                    "name": target_name,
                    "tier_id": tier.id if tier else None,
                    "parent": row[3].strip() if len(row) > 3 else "",
                    "value": int(row[4]) if len(row) > 4 and row[4].strip().isdigit() else 0,
                    "nokill_value": int(row[5]) if len(row) > 5 and row[5].strip().isdigit() else 0,
                    "can_rte": row[6].strip().upper() == "TRUE" if len(row) > 6 else False,
                    "rte_attendence": row[7].strip().upper() == "TRUE" if len(row) > 7 else False,
                    "pull_other_rte_in": row[8].strip().upper() == "TRUE" if len(row) > 8 else False,
                    "close_on_quake": row[9].strip().upper() == "TRUE" if len(row) > 9 else False,
                    "lockout_hrs": int(row[10]) if len(row) > 10 and row[10].strip().isdigit() else 0,
                }

                rte_cols = [
                    "rate_per_hour",
                    "rte_tank",
                    "rte_ramp",
                    "rte_kiter",
                    "rte_bumper",
                    "rte_puller",
                    "rte_racer",
                    "rte_tracker",
                    "rte_trainer",
                    "rte_tagger",
                    "rte_cother",
                    "rte_anchor",
                    "rte_sower",
                    "rte_dmf",
                    "rte_cleric",
                    "rte_enchanter",
                    "rte_shaman",
                    "rte_bard",
                ]
                for i, col_name in enumerate(rte_cols):
                    idx = rte_start + i
                    kwargs[col_name] = int(row[idx]) if len(row) > idx and row[idx].strip().isdigit() else 0

                tgt = Target(**kwargs)
                if target_id_str.isdigit():
                    tgt.id = int(target_id_str)
                session.add(tgt)

            session.flush()

        if do_aliases:
            ws = worksheets[1]
            rows = ws.get_all_values()
            session.query(TargetAlias).delete()
            session.flush()

            for row in rows[1:]:
                if len(row) < 2:
                    continue
                target_name = row[0].strip()
                alias_name = row[1].strip()
                tgt = session.query(Target).filter_by(name=target_name).first()
                if tgt:
                    session.add(TargetAlias(target_id=tgt.id, name=alias_name))

        if do_permissions:
            ws = worksheets[3]
            rows = ws.get_all_values()
            session.query(Permission).delete()
            session.flush()

            if rows:
                header = rows[0]
                for row in rows[1:]:
                    if len(row) < 2:
                        continue
                    role = row[0].strip().lower()
                    server = row[1].strip()
                    for col_idx in range(2, len(row)):
                        if row[col_idx].strip():
                            perm_name = header[col_idx].strip().lower() if col_idx < len(header) else ""
                            if perm_name:
                                session.add(Permission(role=role, server=server, permission=perm_name))

        if do_loot_tables:
            ws = worksheets[4]
            rows = ws.get_all_values()
            existing_ids = [lt.id for lt in session.query(LootTable).all()]
            found_ids: list[int] = []
            new_ids: list[int] = []

            target_cache: dict[str, Target | None] = {}
            for row in rows[1:]:
                if len(row) < 2:
                    continue
                target_name = row[0].strip().lower()
                item_name = row[1].strip()

                if target_name not in target_cache:
                    target_cache[target_name] = session.query(Target).filter(Target.name.ilike(target_name)).first()
                tgt = target_cache[target_name]

                item = session.query(Item).filter(Item.name.ilike(item_name)).first()
                if not item:
                    item = Item(name=item_name)
                    session.add(item)
                    session.flush()

                if tgt and item:
                    lt = session.query(LootTable).filter_by(target_id=tgt.id, item_id=item.id).first()
                    if lt:
                        found_ids.append(lt.id)
                    else:
                        lt = LootTable(target_id=tgt.id, item_id=item.id)
                        session.add(lt)
                        session.flush()
                        new_ids.append(lt.id)
                elif not tgt:
                    not_found.append(f"- Target: {target_name}")

            to_delete = set(existing_ids) - set(found_ids)
            if to_delete:
                session.query(LootTable).filter(LootTable.id.in_(to_delete)).delete(synchronize_session="fetch")

            loot_stats["existing"] = len(found_ids)
            loot_stats["new"] = len(new_ids)
            loot_stats["deleted"] = len(to_delete)

        if do_loot_groups and len(worksheets) > 5:
            ws = worksheets[5]
            rows = ws.get_all_values()
            buf = io.StringIO()
            writer = csv.writer(buf)
            for row in rows[1:]:
                if len(row) >= 2:
                    writer.writerow([row[0], row[1]])
            csv_bytes = buf.getvalue().encode("utf-8")

            loot_ch_id = config.get_raid_setting(guild_id, "loot_channel_id")
            loot_channel = inter.guild.get_channel(loot_ch_id) if loot_ch_id else None
            if loot_channel:
                async for msg in loot_channel.history(limit=1):
                    await msg.delete()
                await loot_channel.send(file=disnake.File(io.BytesIO(csv_bytes), filename="loot_groups.csv"))

        session.commit()

    out = ["```diff", "+ Config reloaded!"]
    if do_loot_tables:
        out.append("")
        out.append(
            f"Loot Tables: Existing({loot_stats['existing']}), "
            f"New({loot_stats['new']}), Deleted({loot_stats['deleted']})"
        )
        if not_found:
            out.append("")
            out.append("Not Found:")
            out.extend(not_found)
    out.append("```")
    await inter.followup.send("\n".join(out))


# ---------------------------------------------------------------------------
# Autocomplete handlers (registered after all subcommands are defined)
# ---------------------------------------------------------------------------


def _target_choices(query: str, guild_id: int) -> dict[str, str]:
    query = query.strip().lower()
    with get_raid_session(guild_id) as session:
        q = (
            session.query(Target)
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


@create.autocomplete("target_name")
@target.autocomplete("name")
async def _ac_event_target(inter: disnake.ApplicationCommandInteraction, query: str):
    return _target_choices(query, inter.guild.id)
