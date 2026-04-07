"""Tests for computed properties on raid ORM models (Event, Tracking)."""

from __future__ import annotations

import datetime

from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.raid import Event
from roboToald.db.raid_models.target import Target, Tier
from roboToald.db.raid_models.tracking import Tracking
from roboToald.raid.dkp_calculator import dkp_from_duration


def test_event_target_name_prefers_linked_target(raid_session):
    tgt = Target(name="Linked Boss")
    raid_session.add(tgt)
    raid_session.flush()
    evt = Event(target_id=tgt.id, name="Fallback Name")
    raid_session.add(evt)
    raid_session.commit()
    assert evt.target_name == "Linked Boss"


def test_event_target_name_falls_back_to_event_name(raid_session):
    evt = Event(name="Name Only")
    raid_session.add(evt)
    raid_session.commit()
    assert evt.target_name == "Name Only"


def test_event_channel_name_includes_formatted_time(raid_session):
    tgt = Target(name="T")
    raid_session.add(tgt)
    raid_session.flush()
    created = datetime.datetime(2024, 7, 4, 15, 30, 0, tzinfo=datetime.timezone.utc)
    evt = Event(target_id=tgt.id, name="Sunday", created_at=created)
    raid_session.add(evt)
    raid_session.commit()
    assert "Sunday" in evt.channel_name
    assert "jul" in evt.channel_name.lower()


def test_event_dkp_value_explicit_dkp_killed(raid_session):
    evt = Event(dkp=50, nokill_dkp=10, killed=True)
    raid_session.add(evt)
    raid_session.commit()
    assert evt.dkp_value == 50


def test_event_dkp_value_explicit_dkp_not_killed(raid_session):
    evt = Event(dkp=50, nokill_dkp=10, killed=False)
    raid_session.add(evt)
    raid_session.commit()
    assert evt.dkp_value == 10


def test_event_dkp_value_from_tier(raid_session):
    tier = Tier(name="T1", value=200, nokill_value=40)
    raid_session.add(tier)
    raid_session.flush()
    tgt = Target(name="Boss", tier_id=tier.id, value=None, nokill_value=None)
    raid_session.add(tgt)
    raid_session.flush()
    evt_kill = Event(target_id=tgt.id, killed=True, dkp=None)
    evt_nok = Event(target_id=tgt.id, killed=False, dkp=None)
    raid_session.add_all([evt_kill, evt_nok])
    raid_session.commit()
    assert evt_kill.dkp_value == 200
    assert evt_nok.nokill_dkp_value == 40


def test_tracking_duration_rate_dkp_and_names(raid_session):
    tgt = Target(name="Mob", rte_tank=60)
    char = Character(name="WarMain", klass="Warlord")
    raid_session.add_all([tgt, char])
    raid_session.flush()
    start = datetime.datetime(2024, 1, 1, 12, 0, 0)
    end = datetime.datetime(2024, 1, 1, 13, 0, 0)
    tr = Tracking(target_id=tgt.id, character_id=char.id, start_time=start, end_time=end, role_id=1)
    raid_session.add(tr)
    raid_session.commit()

    assert tr.duration == 3600.0
    assert tr.rate_per_hour == 60
    assert tr.dkp_amount == dkp_from_duration(60, 3600.0)
    assert tr.role_name == "Tank"
    assert tr.character_name == "WarMain"


def test_tracking_role_name_falls_back_to_class(raid_session):
    tgt = Target(name="Mob")
    char = Character(name="X", klass="Arch Mage")
    raid_session.add_all([tgt, char])
    raid_session.flush()
    tr = Tracking(
        target_id=tgt.id,
        character_id=char.id,
        start_time=datetime.datetime(2024, 1, 1, 12, 0, 0),
        end_time=datetime.datetime(2024, 1, 1, 12, 30, 0),
        role_id=999,
    )
    raid_session.add(tr)
    raid_session.commit()
    assert tr.role_name == "MAG"
