"""Guild/officer line parser for the log stream."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from roboToald import config
from roboToald.raidtargets import rt_log_reader
from roboToald.raidtargets.rt_log_parse import parse_guild_line

ET = ZoneInfo("America/New_York")
STAMP = "Fri Mar 06 11:13:03 2026"
EPOCH = int(datetime(2026, 3, 6, 11, 13, 3, tzinfo=ET).timestamp())
NOW = EPOCH + 3600


def _line(rest: str, stamp: str = STAMP) -> str:
    return f"[{stamp}] {rest}"


def test_guild_tod_uses_eastern_stamp():
    parsed = parse_guild_line(_line("Toald tells the guild, '!tod Lord Nagafen'"), now_utc=NOW)
    assert parsed is not None
    assert parsed.channel == "guild"
    assert parsed.speaker == "Toald"
    assert parsed.command is not None
    assert parsed.command.kind == "tod"
    assert parsed.command.target == "Lord Nagafen"
    assert parsed.stamp_epoch == EPOCH
    assert parsed.stamp_error is None


def test_you_say_batphone_uses_character_name():
    parsed = parse_guild_line(_line("You say to your guild, '!bp naggy'"), character="Toald", now_utc=NOW)
    assert parsed is not None
    assert parsed.speaker == "Toald"
    assert parsed.channel == "guild"
    assert parsed.command is not None
    assert parsed.command.kind == "bp"
    assert parsed.command.target == "naggy"


def test_you_say_without_character_is_you():
    parsed = parse_guild_line(_line("You say to your guild, 'hello there'"), character="", now_utc=NOW)
    assert parsed is not None
    assert parsed.speaker == "you"
    assert parsed.command is None


def test_officer_variants():
    tod = parse_guild_line(_line("Toald tells the guild officers, '!tod Lord Nagafen'"), now_utc=NOW)
    bp = parse_guild_line(
        _line("You say to your guild officers, '!bp naggy'"),
        character="Toald",
        now_utc=NOW,
    )
    assert tod is not None and tod.channel == "officer"
    assert tod.command is not None and tod.command.kind == "tod"
    assert bp is not None and bp.channel == "officer"
    assert bp.speaker == "Toald"
    assert bp.command is not None and bp.command.target == "naggy"


def test_command_must_start_the_body():
    upper = parse_guild_line(_line("Toald tells the guild, '!TOD Lord Nagafen'"), now_utc=NOW)
    buried = parse_guild_line(_line("Toald tells the guild, 'please !tod naggy'"), now_utc=NOW)
    say = parse_guild_line(_line("You say, 'hello'"), now_utc=NOW)
    combat = parse_guild_line(_line("A goblin is slain by Toald!"), now_utc=NOW)
    assert upper is not None and upper.command is not None and upper.command.kind == "tod"
    assert buried is not None and buried.command is None
    assert say is None
    assert combat is None


def test_plain_guild_line_has_no_command_and_officer_is_officer():
    guild = parse_guild_line(_line("Toald tells the guild, 'pulling'"), now_utc=NOW)
    officer = parse_guild_line(_line("Toald tells the guild officers, 'pulling'"), now_utc=NOW)
    assert guild is not None and guild.channel == "guild" and guild.command is None
    assert officer is not None and officer.channel == "officer"


async def test_future_stamp_is_rejected_and_does_not_record(monkeypatch):
    calls = []
    monkeypatch.setattr(config, "get_raidtargets_source", lambda _gid: "local")
    monkeypatch.setattr(rt_log_reader.rt_service, "record_tod", lambda *args, **kwargs: calls.append(args))
    parsed = parse_guild_line(
        _line("Toald tells the guild, '!tod Lord Nagafen'"),
        now_utc=EPOCH - 600,
    )
    assert parsed is not None
    assert parsed.stamp_epoch is None
    assert parsed.stamp_error
    assert parsed.command is not None
    await rt_log_reader.apply_commands(1, parsed, discord=None)
    assert calls == []


def test_empty_command_target_is_not_a_command():
    parsed = parse_guild_line(_line("Toald tells the guild, '!tod'"), now_utc=NOW)
    assert parsed is not None and parsed.command is None
    assert parsed.body == "!tod"


@pytest.mark.parametrize("bad", ["", "not a log line", "[no close Toald tells the guild, 'hi'"])
def test_non_guild_shapes_are_none(bad):
    assert parse_guild_line(bad, now_utc=NOW) is None
