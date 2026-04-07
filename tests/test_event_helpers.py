"""Tests for pure helpers in ``roboToald.raid.event_helpers``."""

from __future__ import annotations

import datetime
from datetime import timezone

from freezegun import freeze_time

from roboToald.db.raid_models.loot import Item, LootTable
from roboToald.db.raid_models.raid import Attendee, Event
from roboToald.db.raid_models.target import Target, TargetAlias
from roboToald.db.raid_models.tracking import Tracking
from roboToald.db.raid_models.character import Character
from roboToald.raid.event_helpers import (
    _time_ago_in_words,
    build_target_loot_table_lines,
    get_shortest_alias,
    resolve_target,
    rte_tracking_creator,
)


@freeze_time("2020-01-15T12:00:00")
def test_time_ago_in_words_less_than_minute():
    # Match ``_time_ago_in_words``: naive UTC wall time vs naive ``dt``
    dt = datetime.datetime(2020, 1, 15, 11, 59, 30)
    assert _time_ago_in_words(dt) == "less than a minute"


@freeze_time("2020-01-15T12:00:00")
def test_time_ago_in_words_days_and_hours():
    dt = datetime.datetime(2020, 1, 13, 10, 0, 0)
    s = _time_ago_in_words(dt)
    assert "day" in s
    assert "hour" in s


def test_resolve_target_single_hit(raid_session):
    raid_session.add(Target(name="Test Boss Mob"))
    raid_session.commit()
    targets, _aliases = resolve_target("boss", raid_session)
    assert len(targets) == 1
    assert targets[0].name == "Test Boss Mob"


def test_get_shortest_alias_prefers_short_alias(raid_session):
    t = Target(name="Very Long Target Name Here")
    raid_session.add(t)
    raid_session.flush()
    raid_session.add_all(
        [
            TargetAlias(target_id=t.id, name="short"),
            TargetAlias(target_id=t.id, name="mediumalias"),
        ]
    )
    raid_session.commit()
    assert get_shortest_alias(t, raid_session) == "short"


def test_build_target_loot_table_lines(raid_session):
    tgt = Target(name="Frost Boss", value=50, nokill_value=25)
    raid_session.add(tgt)
    raid_session.flush()
    it = Item(name="Frozen Sword")
    raid_session.add(it)
    raid_session.flush()
    raid_session.add(LootTable(item_id=it.id, target_id=tgt.id))
    evt = Event(target_id=tgt.id, name="Sunday Raid", dkp=100, nokill_dkp=40, killed=True)
    raid_session.add(evt)
    raid_session.commit()

    lines = build_target_loot_table_lines(evt, tgt, raid_session)
    joined = "\n".join(lines)
    assert "Frost Boss" in joined
    assert "Frozen Sword" in joined
    assert "100" in joined


def test_rte_tracking_creator_closes_tracking_and_adds_attendee(raid_session):
    tgt = Target(name="Velious Dragon", can_rte=True)
    char = Character(name="MainTank", klass="Warlord")
    raid_session.add_all([tgt, char])
    raid_session.flush()
    tr = Tracking(
        target_id=tgt.id,
        character_id=char.id,
        start_time=datetime.datetime.now(timezone.utc),
        role_id=1,
        is_rte=True,
    )
    raid_session.add(tr)
    raid_session.flush()
    evt = Event(channel_id="9001", target_id=tgt.id, name="kill", killed=True, dkp=10)
    raid_session.add(evt)
    raid_session.commit()
    tr_id = tr.id
    evt_id = evt.id

    msgs = rte_tracking_creator(evt, tgt, None, raid_session)
    assert msgs
    raid_session.commit()

    tr_db = raid_session.query(Tracking).filter_by(id=tr_id).one()
    assert tr_db.end_time is not None
    assert tr_db.close_event_id == evt_id

    att = raid_session.query(Attendee).filter_by(event_id=evt_id).one()
    assert str(char.id) == att.character_id
