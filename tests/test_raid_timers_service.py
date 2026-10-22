"""Tests for raid-timer DB service (seed, resolve, ToD/quake, local feed)."""

from __future__ import annotations

import json
import time

import pytest
from freezegun import freeze_time
from sqlalchemy.exc import IntegrityError

from roboToald.db.models import raid_timers as rt_models
from roboToald.raidtargets import rt_data, rt_service


GUILD = 1


def test_unique_guild_name(raid_timers_session):
    raid_timers_session.add(rt_models.RtTarget(guild_id=GUILD, name="A", short_name="", aliases="", era="", zone=""))
    raid_timers_session.commit()
    raid_timers_session.add(rt_models.RtTarget(guild_id=GUILD, name="A", short_name="", aliases="", era="", zone=""))
    with pytest.raises(IntegrityError):
        raid_timers_session.commit()
    raid_timers_session.rollback()


def test_seed_guild_idempotent(raid_timers_session):
    n = rt_service.seed_guild_if_empty(GUILD)
    assert n == 100
    assert rt_service.seed_guild_if_empty(GUILD) == 0
    specs = rt_service.list_specs(GUILD)
    assert len(specs) == 100
    assert any(s.name == "Lord Nagafen" for s in specs)
    assert any(s.name == "Ring 8" and s.quake_immune for s in specs)


def test_resolve_target_aliases_and_ambiguity(raid_timers_session):
    rt_service.seed_guild_if_empty(GUILD)
    assert rt_service.resolve_target(GUILD, "naggy").name == "Lord Nagafen"
    assert rt_service.resolve_target(GUILD, "Dozekar the Cursed").name == "Dozekar the Cursed"
    assert rt_service.resolve_target(GUILD, "rf").name == "Zordak Ragefire"
    assert rt_service.resolve_target(GUILD, "Zordak Ragefire engages you") is not None
    assert rt_service.resolve_target(GUILD, "lord") is None  # ambiguous substring


def test_record_tod_dedup_priority(raid_timers_session):
    rt_service.seed_guild_if_empty(GUILD)
    now = 1_700_000_000
    with freeze_time("2023-11-14 12:00:00"):
        r1 = rt_service.record_tod(GUILD, "naggy", now - 10, "slash", "u1", now_utc=now)
        assert r1.status == "recorded"
        r2 = rt_service.record_tod(GUILD, "naggy", now - 5, "log_death", "char", now_utc=now + 60)
        assert r2.status == "superseded_existing"
        r3 = rt_service.record_tod(GUILD, "naggy", now, "slash", "u2", now_utc=now + 90)
        assert r3.status == "duplicate"


def test_undo_last_tod(raid_timers_session):
    rt_service.seed_guild_if_empty(GUILD)
    now = 1_700_000_000
    rt_service.record_tod(GUILD, "naggy", now - 1000, "slash", now_utc=now)
    # Outside dedup window
    rt_service.record_tod(GUILD, "naggy", now - 100, "slash", now_utc=now + 400)
    prev = rt_service.undo_last_tod(GUILD, "naggy")
    assert prev is not None
    assert prev.tod_utc == now - 1000
    assert rt_service.current_tods(GUILD)["Lord Nagafen"] == now - 1000


def test_build_feed_round_trip(raid_timers_session):
    rt_service.seed_guild_if_empty(GUILD)
    now = int(time.time())
    rt_service.record_tod(GUILD, "Lord Nagafen", now - 100, "slash", now_utc=now)
    feed = rt_service.build_feed_for_guild(GUILD, now_utc=now)
    assert "raidTargets" in feed
    entry = next(t for t in feed["raidTargets"] if t["name"] == "Lord Nagafen")
    assert set(entry.keys()) == {"name", "shortName", "aliases", "era", "zone", "windows"}
    decoded = json.loads(json.dumps(feed), cls=rt_data.JSONDecoder)
    assert any(t.name == "Lord Nagafen" for t in decoded)


@pytest.mark.asyncio
async def test_local_source_loads_names(raid_timers_session, monkeypatch):
    from roboToald import config

    rt_service.seed_guild_if_empty(GUILD)
    monkeypatch.setitem(config.GUILD_SETTINGS, GUILD, {"raidtargets_source": "local"})
    # ensure get_raidtargets_source reads local
    monkeypatch.setattr(config, "get_raidtargets_source", lambda gid: "local")
    rt_data.RaidTargets._cache.clear()
    names = await rt_data.RaidTargets.get_all_names(GUILD, force_refresh=True)
    assert "Lord Nagafen" in names
    assert "King Tranix" not in names  # hidden


@pytest.mark.asyncio
async def test_tod_command_records(raid_timers_session, monkeypatch, fake_inter):
    from roboToald.discord_client.commands import cmd_raidtarget

    rt_service.seed_guild_if_empty(GUILD)
    monkeypatch.setattr(cmd_raidtarget.base, "is_user_authorized", lambda **kwargs: True)
    monkeypatch.setattr(cmd_raidtarget.config, "get_raidtargets_source", lambda gid: "local")
    now = 1_700_000_000
    monkeypatch.setattr(cmd_raidtarget.time, "time", lambda: now)
    await cmd_raidtarget.record_tod_interaction(fake_inter, "naggy", "now")
    assert rt_service.current_tods(GUILD)["Lord Nagafen"] == now
    fake_inter.send.assert_awaited()


def test_parse_human_time_now_and_hhmm():
    now = 1_700_000_000  # ~2023-11-14 17:46:40 UTC = 12:46 ET
    assert rt_service.parse_human_time("now", now) == now
    # 10:00 ET same day
    parsed = rt_service.parse_human_time("10:00", now)
    assert parsed < now
    with pytest.raises(ValueError):
        rt_service.parse_human_time("not-a-time", now)


def test_parse_human_time_eq_log_stamp():
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    now = 1_700_000_000  # 2023-11-14
    winter = int(datetime(2023, 1, 15, 17, 0, 0, tzinfo=timezone.utc).timestamp())
    summer = int(datetime(2023, 7, 16, 16, 0, 0, tzinfo=timezone.utc).timestamp())
    assert rt_service.parse_human_time("Sun Jan 15 12:00:00 2023", now) == winter  # EST
    assert rt_service.parse_human_time("[sun jul 16 12:00:00 2023]", now) == summer  # EDT
    assert winter == int(datetime(2023, 1, 15, 12, 0, 0, tzinfo=et).timestamp())
    assert summer == int(datetime(2023, 7, 16, 12, 0, 0, tzinfo=et).timestamp())
    # Unpadded day, weekday ignored when it does not match the date.
    march = int(datetime(2023, 3, 6, 11, 13, 3, tzinfo=et).timestamp())
    assert rt_service.parse_human_time("Fri Mar 6 11:13:03 2023", now) == march
    with pytest.raises(ValueError, match="future"):
        rt_service.parse_human_time("Fri Mar 06 11:13:03 2026", now)
    with pytest.raises(ValueError, match="Unrecognized"):
        rt_service.parse_human_time("Fri Feb 31 11:13:03 2023", now)


@pytest.mark.asyncio
async def test_tod_command_records_eq_log_stamp(raid_timers_session, monkeypatch, fake_inter):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from roboToald.discord_client.commands import cmd_raidtarget

    rt_service.seed_guild_if_empty(GUILD)
    monkeypatch.setattr(cmd_raidtarget.base, "is_user_authorized", lambda **kwargs: True)
    monkeypatch.setattr(cmd_raidtarget.config, "get_raidtargets_source", lambda gid: "local")
    monkeypatch.setattr(cmd_raidtarget.time, "time", lambda: 1_700_000_000)
    await cmd_raidtarget.record_tod_interaction(fake_inter, "naggy", "Mon Mar 06 11:13:03 2023")
    expected = int(datetime(2023, 3, 6, 11, 13, 3, tzinfo=ZoneInfo("America/New_York")).timestamp())
    assert rt_service.current_tods(GUILD)["Lord Nagafen"] == expected
