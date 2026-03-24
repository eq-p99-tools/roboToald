"""EQ log line parser. Port of batphone-bot player_parser.rb."""

from __future__ import annotations

import re
from dataclasses import dataclass

from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.character import Character

GUILDS = ["good guys"]

EQ_LINE_RE = re.compile(
    r"^(\[)?(.*?)(\])?"
    r" ( AFK )?( <LINKDEAD>)?"
    r"\[(.*?)\] (\w+)\s?(\(.*?\))?( <.*?>)?"
)

NL_LINE_RE = re.compile(
    r"^\[(.*?)\] \[ANONYMOUS\] (\w+)\s(<.*?>) (\{.*?\})"
)


@dataclass
class ParsedPlayer:
    name: str
    guild: str
    race: str
    level: str
    klass: str


def parse_players_from_content(
    content: str,
    guild_id: int,
) -> tuple[list[ParsedPlayer], list[ParsedPlayer]]:
    """Parse EQ log content, returning (known_players, anonymous_players)."""
    found_names: set[str] = set()
    players: list[ParsedPlayer] = []
    anonymous_players: list[ParsedPlayer] = []

    with get_raid_session(guild_id) as session:
        for line in content.split("\n"):
            line = line.strip()
            guild = ""
            level = ""
            klass = ""
            name = ""
            race = ""

            m = EQ_LINE_RE.match(line)
            nl_m = NL_LINE_RE.match(line) if not m else None

            if m:
                guild = m.group(9) or ""
                level_klass = m.group(6) or ""
                parts = level_klass.split(" ", 1)
                level = parts[0] if parts else ""
                klass = parts[1] if len(parts) > 1 else ""
                name = (m.group(7) or "").strip().capitalize()
                race = (m.group(8) or "").strip("() ")
            elif nl_m:
                guild = (nl_m.group(3) or "").strip()
                raw_lk = (nl_m.group(4) or "").strip("{} ")
                parts = raw_lk.split(" ", 1)
                level = parts[0] if parts else ""
                klass = parts[1] if len(parts) > 1 else ""
                name = (nl_m.group(2) or "").strip().capitalize()
            else:
                continue

            guild = guild.strip("<> ")
            if guild == "None":
                guild = ""

            player = ParsedPlayer(
                name=name, guild=guild, race=race, level=level, klass=klass,
            )

            existing = (
                session.query(Character)
                .filter(Character.name.ilike(name))
                .first()
            )
            in_guild = guild.lower() in GUILDS

            if (
                not existing
                and not in_guild
                and not guild
                and level == "ANONYMOUS"
            ):
                anonymous_players.append(player)
            elif (in_guild or existing) and name.lower() not in found_names:
                players.append(player)
                found_names.add(name.lower())

    players.sort(key=lambda p: p.name)
    seen = set()
    unique_anon = []
    for p in anonymous_players:
        if p.name.lower() not in seen:
            unique_anon.append(p)
            seen.add(p.name.lower())
    unique_anon.sort(key=lambda p: p.name)

    return players, unique_anon
