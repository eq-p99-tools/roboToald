"""Parse guild and officer chat lines from the log stream.

The provider sends one EQ-style line per SSE event. Only guild and officer
tells are recognized. Say, group, tell, and combat lines return None.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from roboToald.raidtargets.rt_service import parse_human_time

_STAMPED = re.compile(r"^\[(?P<stamp>[^\]]+)\] (?P<rest>.*)$")
_YOU_OFFICER = re.compile(r"^You say to your guild officers, '(?P<body>.*)'$")
_YOU_GUILD = re.compile(r"^You say to your guild, '(?P<body>.*)'$")
_TELL_OFFICER = re.compile(r"^(?P<speaker>.+) tells the guild officers, '(?P<body>.*)'$")
_TELL_GUILD = re.compile(r"^(?P<speaker>.+) tells the guild, '(?P<body>.*)'$")
_COMMAND = re.compile(r"^!(tod|bp)(?:\s+(.*))?$", re.IGNORECASE)


@dataclass(frozen=True)
class GuildCommand:
    kind: str  # "tod" or "bp"
    target: str


@dataclass(frozen=True)
class GuildLine:
    speaker: str
    body: str
    channel: str  # "guild" or "officer"
    stamp: str
    stamp_epoch: int | None
    stamp_error: str | None
    command: GuildCommand | None


def parse_guild_line(line: str, character: str = "", now_utc: int | None = None) -> GuildLine | None:
    """Return a guild/officer line, or None when the line is not one of those."""
    match = _STAMPED.match(line or "")
    if match is None:
        return None
    stamp = match.group("stamp")
    rest = match.group("rest")

    you_officer = _YOU_OFFICER.match(rest)
    you_guild = _YOU_GUILD.match(rest)
    tell_officer = _TELL_OFFICER.match(rest)
    tell_guild = _TELL_GUILD.match(rest)

    if you_officer is not None:
        channel = "officer"
        body = you_officer.group("body")
        speaker = character.strip() or "you"
    elif you_guild is not None:
        channel = "guild"
        body = you_guild.group("body")
        speaker = character.strip() or "you"
    elif tell_officer is not None:
        channel = "officer"
        body = tell_officer.group("body")
        speaker = tell_officer.group("speaker").strip() or "you"
    elif tell_guild is not None:
        channel = "guild"
        body = tell_guild.group("body")
        speaker = tell_guild.group("speaker").strip() or "you"
    else:
        return None

    command = _command_at_start(body)
    if now_utc is None:
        now_utc = int(time.time())
    stamp_epoch, stamp_error = _stamp_epoch(stamp, now_utc)
    return GuildLine(
        speaker=speaker,
        body=body,
        channel=channel,
        stamp=stamp,
        stamp_epoch=stamp_epoch,
        stamp_error=stamp_error,
        command=command,
    )


def _command_at_start(body: str) -> GuildCommand | None:
    match = _COMMAND.match(body.strip())
    if match is None:
        return None
    target = (match.group(2) or "").strip()
    if not target:
        return None
    return GuildCommand(kind=match.group(1).lower(), target=target)


def _stamp_epoch(stamp: str, now_utc: int) -> tuple[int | None, str | None]:
    try:
        return parse_human_time(stamp, now_utc), None
    except ValueError as exc:
        return None, str(exc)
