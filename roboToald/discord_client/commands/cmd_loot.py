"""Loot slash commands (/loot add kept for autocomplete). Text commands in cmd_event.py."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import disnake
import disnake.ext.commands
import sqlalchemy as sa

from roboToald import config
from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.raid import Event, Attendee
from roboToald.db.raid_models.loot import EventLoot, Loot, Item, LootTable
from roboToald.db.raid_models.character import Character
from roboToald.discord_client import base
from roboToald.raid import permissions as perms

logger = logging.getLogger(__name__)

RAID_GUILDS = config.guilds_for_command("raid")

# ---------------------------------------------------------------------------
# /loot slash command group
# ---------------------------------------------------------------------------


@base.DISCORD_CLIENT.slash_command(description="Loot management", guild_ids=RAID_GUILDS)
async def loot(inter: disnake.ApplicationCommandInteraction):
    pass


@loot.sub_command(description="Record loot for a character.")
async def add(
    inter: disnake.ApplicationCommandInteraction,
    item: str = disnake.ext.commands.Param(description="Item name, ID, or wiki URL", autocomplete=True),
    character: str = disnake.ext.commands.Param(description="Character name", autocomplete=True),
    dkp_value: int = disnake.ext.commands.Param(description="DKP value", name="dkp"),
):
    guild_id = inter.guild.id
    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel.id)).first()
        if not evt:
            await inter.response.send_message("```diff\n- No event found for this channel.```", ephemeral=True)
            return

        # Resolve item
        item_record = None
        item_name = item.strip()

        if item_name.isdigit():
            item_record = session.query(Item).get(int(item_name))
        else:
            wiki_match = re.match(r"https?://wiki\.project1999\.com/(.*)", item_name)
            if wiki_match:
                item_name = wiki_match.group(1).replace("_", " ")

            candidates = session.query(Item).filter(Item.name.ilike(f"%{item_name.lower()}%")).all()
            if len(candidates) == 1:
                item_record = candidates[0]
            elif len(candidates) > 1:
                exact = [c for c in candidates if c.name.lower() == item_name.lower()]
                if exact:
                    item_record = exact[0]
                else:
                    lines = ["```diff", "- Multiple items found (showing first 10):"]
                    for c in candidates[:10]:
                        lines.append(f"- {c.name} (ID: {c.id})")
                    lines.append("```")
                    await inter.response.send_message("\n".join(lines), ephemeral=True)
                    return

        if not item_record:
            await inter.response.send_message(
                f"```diff\n- Item '{item}' not found. Use an item ID or more specific name.```",
                ephemeral=True,
            )
            return

        # Resolve character
        char = session.query(Character).filter(Character.name.ilike(character)).first()
        if not char:
            await inter.response.send_message(
                f"```diff\n- {character} not found. Add them with +Player first.```",
                ephemeral=True,
            )
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
        await inter.response.send_message("\n".join(out))


@loot.sub_command(description="Remove a loot entry from this event.")
async def remove(
    inter: disnake.ApplicationCommandInteraction,
    entry: str = disnake.ext.commands.Param(
        description="Loot entry to remove",
        autocomplete=True,
    ),
):
    guild_id = inter.guild.id
    if not perms.can(inter.author, "unloot", guild_id):
        await inter.response.send_message("```diff\n- No permission.```", ephemeral=True)
        return

    loot_id_str = entry.strip()
    if not loot_id_str.isdigit():
        await inter.response.send_message(
            "```diff\n- Please select an entry from the autocomplete list.```",
            ephemeral=True,
        )
        return
    loot_id = int(loot_id_str)

    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel.id)).first()
        if not evt:
            await inter.response.send_message(
                "```diff\n- No event found for this channel.```",
                ephemeral=True,
            )
            return
        el = session.query(EventLoot).filter_by(event_id=evt.id, id=loot_id).first()
        if not el:
            await inter.response.send_message(
                f"```diff\n- Loot ID {loot_id} not found.```",
                ephemeral=True,
            )
            return
        item_rec = session.query(Item).get(el.item_id) if el.item_id else None
        char = session.query(Character).get(el.character_id) if el.character_id else None
        item_name = item_rec.name if item_rec else "?"
        char_name = char.name if char else "?"
        el_dkp = el.dkp or 0
        session.delete(el)
        session.commit()
        await inter.response.send_message(
            f"```diff\n+ Loot ID {loot_id} removed. ({item_name}, {char_name}, {el_dkp})```"
        )


# ---------------------------------------------------------------------------
# Autocomplete handlers
# ---------------------------------------------------------------------------


def _character_choices(query: str, guild_id: int) -> dict[str, str]:
    query = query.strip().lower()
    with get_raid_session(guild_id) as session:
        q = session.query(Character).filter(sa.func.length(Character.name) > 0).order_by(Character.name)
        if query:
            q = q.filter(sa.func.lower(Character.name).startswith(query))
        return {c.name: c.name for c in q.limit(25).all()}


@add.autocomplete("item")
async def _ac_item(inter: disnake.ApplicationCommandInteraction, query: str):
    query = query.strip().lower()
    guild_id = inter.guild.id
    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel.id)).first()
        target_id = evt.target_id if evt else None

        if target_id:
            q = (
                session.query(Item)
                .join(LootTable, LootTable.item_id == Item.id)
                .filter(LootTable.target_id == target_id)
                .order_by(Item.name)
            )
        else:
            q = session.query(Item).filter(sa.func.length(Item.name) > 0).order_by(Item.name)

        if query:
            q = q.filter(sa.func.lower(Item.name).contains(query))
        return {i.name: i.name for i in q.limit(25).all()}


@remove.autocomplete("entry")
async def _ac_remove_entry(inter: disnake.ApplicationCommandInteraction, query: str):
    query = query.strip().lower()
    with get_raid_session(inter.guild.id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel.id)).first()
        if not evt:
            return {}
        entries = session.query(EventLoot).filter_by(event_id=evt.id).all()
        choices: dict[str, str] = {}
        for el in entries:
            item_rec = session.query(Item).get(el.item_id) if el.item_id else None
            char = session.query(Character).get(el.character_id) if el.character_id else None
            item_name = item_rec.name if item_rec else "?"
            char_name = char.name if char else "?"
            label = f"{item_name} ({char_name}, {el.dkp or 0} DKP)"
            if not query or query in label.lower():
                choices[label] = str(el.id)
            if len(choices) >= 25:
                break
        return choices


@add.autocomplete("character")
async def _ac_character(inter: disnake.ApplicationCommandInteraction, query: str):
    return _character_choices(query, inter.guild.id)
