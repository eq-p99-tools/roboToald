"""History slash command. Port of batphone-bot history.rb.

The original command ran only in DMs. The slash-command version works
anywhere and displays results ephemerally.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import disnake
import disnake.ext.commands
import sqlalchemy as sa

from roboToald import config
from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.raid import Event, Attendee
from roboToald.db.raid_models.tracking import Tracking
from roboToald.db.raid_models.target import Target
from roboToald.db.raid_models.loot import EventLoot, Item
from roboToald.discord_client import base

logger = logging.getLogger(__name__)

RAID_GUILDS = config.guilds_for_command("raid")


@base.DISCORD_CLIENT.slash_command(description="Look up history", guild_ids=RAID_GUILDS)
async def history(inter: disnake.ApplicationCommandInteraction):
    pass


@history.sub_command(description="Character attendance / DKP history")
async def character(
    inter: disnake.ApplicationCommandInteraction,
    name: str = disnake.ext.commands.Param(description="Character name", autocomplete=True),
):
    guild_id = inter.guild.id
    await inter.response.defer(ephemeral=True)
    with get_raid_session(guild_id) as session:
        chars = session.query(Character).filter(Character.name.ilike(f"%{name.lower()}%")).all()
        if len(chars) > 1:
            exact = [c for c in chars if c.name.lower() == name.lower()]
            if exact:
                chars = exact

        if len(chars) > 1:
            lines = ["```", "- Multiple characters found (first 10):"]
            for c in chars[:10]:
                lines.append(f"- {c.name} (ID: {c.id})")
            lines.append("```")
            await inter.followup.send("\n".join(lines), ephemeral=True)
            return

        if not chars:
            # Try item search instead
            await _item_search(inter, name, session)
            return

        char = chars[0]
        if not char.eqdkp_user_id:
            await _item_search(inter, name, session)
            return

        from roboToald.eqdkp.client import EqdkpClient

        eqdkp = EqdkpClient(guild_id)

        all_chars = session.query(Character).filter_by(eqdkp_user_id=char.eqdkp_user_id).all()
        all_char_ids = [str(c.id) for c in all_chars]

        embed = disnake.Embed(title=f"Status for {char.name}")

        # DKP points
        try:
            raw_dkp = await eqdkp.find_points(char.eqdkp_user_id)
            if raw_dkp is not None:
                val = float(raw_dkp)
                dkp_amount = int(val) if abs(val - round(val)) < 0.0001 else val
            else:
                dkp_amount = "?"
        except Exception:
            logger.exception("EQdkp point lookup failed for user_id=%s", char.eqdkp_user_id)
            dkp_amount = "?"

        char_lines = [f"+ {c.name} (ID: {c.id})" for c in all_chars]
        embed.add_field(
            name=f"Estimated DKP: {dkp_amount}",
            value=f"```diff\n{chr(10).join(char_lines)}```",
            inline=False,
        )

        # Recent attendance (joined via events that have been submitted)
        att_rows = (
            session.query(
                Event.name.label("event_name"),
                Event.created_at.label("created_at"),
                Attendee.character_id,
                Attendee.on_character_id,
                Attendee.tracking_id,
                Attendee.reason,
            )
            .join(Event, Event.id == Attendee.event_id)
            .filter(Attendee.character_id.in_(all_char_ids), Event.eqdkp_raid_id.isnot(None))
            .order_by(Event.created_at.desc())
            .limit(20)
            .all()
        )

        att_lines = []
        for row in att_rows:
            c = session.query(Character).filter_by(id=int(row.character_id)).first() if row.character_id else None
            on_str = ""
            tracking_str = ""
            reason_str = ""

            if row.tracking_id:
                tracking = session.query(Tracking).get(int(row.tracking_id))
                if tracking:
                    tgt = session.query(Target).get(tracking.target_id)
                    if tgt:
                        tracking_str = f" tracking {tgt.name}"

            if row.on_character_id:
                on_c = session.query(Character).filter_by(id=int(row.on_character_id)).first()
                if on_c:
                    on_str = f" on {on_c.name}"

            if row.reason:
                reason_str = f", {row.reason}"

            date_str = row.created_at.strftime("%Y-%m-%d") if row.created_at else "?"
            char_name = c.name if c else "?"
            att_lines.append(f"+ {date_str}: {row.event_name} ({char_name}{on_str}{reason_str}){tracking_str}")

        if att_lines:
            embed.add_field(
                name="Recent Attendance:",
                value=f"```diff\n{chr(10).join(att_lines)}```",
                inline=False,
            )

        # Recent loot
        loot_rows = (
            session.query(
                EventLoot.dkp,
                EventLoot.created_at,
                EventLoot.character_id,
                EventLoot.item_id,
            )
            .join(Event, Event.id == EventLoot.event_id)
            .filter(EventLoot.character_id.in_([c.id for c in all_chars]), Event.eqdkp_raid_id.isnot(None))
            .order_by(EventLoot.created_at.desc())
            .limit(10)
            .all()
        )

        loot_lines = []
        for row in loot_rows:
            c = session.query(Character).get(row.character_id) if row.character_id else None
            item = session.query(Item).get(row.item_id) if row.item_id else None
            date_str = row.created_at.strftime("%Y-%m-%d") if row.created_at else "?"
            loot_lines.append(
                f"+ {date_str}: {str(row.dkp or 0).ljust(7)} {item.name if item else '?'} ({c.name if c else '?'})"
            )

        if loot_lines:
            embed.add_field(
                name="Recent Loot History:",
                value=f"```diff\n{chr(10).join(loot_lines)}```",
                inline=False,
            )

        await inter.followup.send(embed=embed, ephemeral=True)


@history.sub_command(description="Item loot history and 60-day average")
async def item(
    inter: disnake.ApplicationCommandInteraction,
    name: str = disnake.ext.commands.Param(description="Item name"),
):
    guild_id = inter.guild.id
    await inter.response.defer(ephemeral=True)
    with get_raid_session(guild_id) as session:
        await _item_search(inter, name, session)


async def _item_search(inter, criteria: str, session):
    items = session.query(Item).filter(Item.name.ilike(f"%{criteria.lower()}%")).all()
    if len(items) > 1:
        exact = [i for i in items if i.name.lower() == criteria.lower()]
        if exact:
            items = exact

    if len(items) > 1:
        lines = ["```", "- Multiple items found (first 10):"]
        for i in items[:10]:
            lines.append(f"- {i.name} (ID: {i.id})")
        lines.append("```")
        await inter.followup.send("\n".join(lines), ephemeral=True)
        return

    if not items:
        await inter.followup.send(f"```diff\n- No character or item found for [{criteria}].```", ephemeral=True)
        return

    it = items[0]
    loots = session.query(EventLoot).filter_by(item_id=it.id).order_by(EventLoot.created_at.desc()).all()

    cutoff = datetime.utcnow() - timedelta(days=60)
    recent = [el for el in loots if el.created_at and el.created_at >= cutoff]
    avg_60 = sum(el.dkp or 0 for el in recent) // max(len(recent), 1) if recent else 0

    lines = ["```", f"{it.name} History", "", f"60 Day Avg: {avg_60}", "", "- Most recent items looted:", ""]
    for el in loots[:20]:
        c = session.query(Character).get(el.character_id) if el.character_id else None
        date_str = el.created_at.strftime("%Y-%m-%d") if el.created_at else "?"
        lines.append(f"{date_str}: {str(el.dkp or 0).ljust(7)} {c.name if c else '?'}")
    lines.append("```")

    await inter.followup.send("\n".join(lines), ephemeral=True)


# ---------------------------------------------------------------------------
# Autocomplete handlers
# ---------------------------------------------------------------------------


@character.autocomplete("name")
async def _ac_character(inter: disnake.ApplicationCommandInteraction, query: str):
    guild_id = inter.guild.id
    query = query.strip().lower()
    with get_raid_session(guild_id) as session:
        q = session.query(Character).filter(sa.func.length(Character.name) > 0).order_by(Character.name)
        if query:
            q = q.filter(sa.func.lower(Character.name).startswith(query))
        return {c.name: c.name for c in q.limit(25).all()}
