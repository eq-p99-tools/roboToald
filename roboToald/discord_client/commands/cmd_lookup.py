"""EQDKP lookup slash command.

Look up characters on EQDKP by Discord user or character name.
"""

from __future__ import annotations

import logging

import disnake
from disnake.ext import commands

from roboToald import config
from roboToald.discord_client import base

logger = logging.getLogger(__name__)

EQDKP_GUILDS = list(config.EQDKP_SETTINGS.keys())


@base.DISCORD_CLIENT.slash_command(
    description="Look up EQDKP characters", guild_ids=EQDKP_GUILDS
)
async def lookup(inter: disnake.ApplicationCommandInteraction):
    pass


def _format_dkp(raw_dkp: str | None) -> str | int:
    if raw_dkp is None:
        return "?"
    val = float(raw_dkp)
    return int(val) if abs(val - round(val)) < 0.0001 else val


def _char_line(member: dict) -> str:
    name = member.get("name", "?")
    race = member.get("racename", "")
    cls = member.get("classname", "")
    detail = f"{race} {cls}".strip()
    if detail:
        return f"+ {name} ({detail})"
    return f"+ {name}"


@lookup.sub_command(description="List EQDKP characters for a Discord user")
async def user(
    inter: disnake.ApplicationCommandInteraction,
    member: disnake.Member = commands.Param(description="Discord user to look up"),
):
    guild_id = inter.guild.id
    await inter.response.defer(ephemeral=True)

    from roboToald.eqdkp.client import EqdkpClient
    eqdkp = EqdkpClient(guild_id)

    characters = await eqdkp.find_characters_by_discord_id(member.id)
    if not characters:
        await inter.followup.send(
            f"No characters found on EQDKP for {member.mention}.",
            ephemeral=True,
        )
        return

    dkp_amount: str | int = "?"
    user_id = characters[0].get("user_id")
    if user_id and str(user_id) != "0":
        try:
            dkp_amount = _format_dkp(await eqdkp.find_points(user_id))
        except Exception:
            logger.exception(
                "EQdkp point lookup failed for user_id=%s", user_id
            )

    embed = disnake.Embed(
        title=f"EQDKP Characters for {member.display_name}"
    )
    char_lines = [_char_line(c) for c in characters]
    embed.add_field(
        name=f"DKP: {dkp_amount}",
        value=f"```diff\n{chr(10).join(char_lines)}```",
        inline=False,
    )
    await inter.followup.send(embed=embed, ephemeral=True)


@lookup.sub_command(description="Look up a character on EQDKP")
async def character(
    inter: disnake.ApplicationCommandInteraction,
    name: str = commands.Param(
        description="Character name", autocomplete=True,
    ),
):
    guild_id = inter.guild.id
    await inter.response.defer(ephemeral=True)

    from roboToald.eqdkp.client import EqdkpClient
    eqdkp = EqdkpClient(guild_id)

    result = await eqdkp.find_character(name)
    if not result:
        await inter.followup.send(
            f"```diff\n- No character found for [{name}].```",
            ephemeral=True,
        )
        return

    char_name = result.get("name", name)
    auth_account = result.get("auth_account", "")
    user_id = result.get("user_id")

    embed = disnake.Embed(title=f"EQDKP: {char_name}")

    race = result.get("racename", "")
    cls = result.get("classname", "")
    detail = f"{race} {cls}".strip()
    if detail:
        embed.add_field(name="Race/Class", value=detail, inline=True)

    if auth_account and str(auth_account).isdigit():
        discord_val = f"<@{auth_account}>"
        embed.add_field(
            name="Discord", value=discord_val, inline=True
        )
    else:
        embed.add_field(name="Discord", value="Not linked", inline=True)

    dkp_amount: str | int = "?"
    if user_id and str(user_id) != "0":
        try:
            dkp_amount = _format_dkp(await eqdkp.find_points(user_id))
        except Exception:
            logger.exception(
                "EQdkp point lookup failed for user_id=%s", user_id
            )
    embed.add_field(name="DKP", value=str(dkp_amount), inline=True)

    if auth_account and str(auth_account).isdigit():
        all_chars = await eqdkp.find_characters_by_discord_id(auth_account)
        if len(all_chars) > 1:
            char_lines = [_char_line(c) for c in all_chars]
            embed.add_field(
                name="All Characters",
                value=f"```diff\n{chr(10).join(char_lines)}```",
                inline=False,
            )

    await inter.followup.send(embed=embed, ephemeral=True)


@character.autocomplete("name")
async def _ac_character(
    inter: disnake.ApplicationCommandInteraction, query: str,
):
    guild_id = inter.guild.id
    query = query.strip().lower()
    try:
        from roboToald.db.raid_base import get_raid_session
        from roboToald.db.raid_models.character import Character
        import sqlalchemy as sa
        with get_raid_session(guild_id) as session:
            q = (
                session.query(Character)
                .filter(sa.func.length(Character.name) > 0)
                .order_by(Character.name)
            )
            if query:
                q = q.filter(
                    sa.func.lower(Character.name)
                    .startswith(query)
                )
            return {
                c.name: c.name
                for c in q.limit(25).all()
            }
    except Exception:
        return {}
