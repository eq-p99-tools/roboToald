"""Tests for ``roboToald.db.models.points`` query helpers and CRUD."""

from __future__ import annotations

import datetime

from freezegun import freeze_time

from roboToald import constants
from roboToald.db.models import points as points_model


def test_get_event_roundtrip(points_session):  # noqa: ARG001
    t = datetime.datetime(2024, 2, 1, 10, 0, 0)
    ev = points_model.PointsAudit(user_id=5, guild_id=99, event=constants.Event.IN, time=t, active=True)
    points_model.start_event(ev)
    loaded = points_model.get_event(ev.id)
    assert loaded is not None
    assert loaded.user_id == 5
    assert loaded.guild_id == 99


def test_get_events_for_member_filters_guild(points_session):  # noqa: ARG001
    t = datetime.datetime(2024, 2, 1, 10, 0, 0)
    points_model.start_event(
        points_model.PointsAudit(user_id=1, guild_id=10, event=constants.Event.IN, time=t, active=True)
    )
    points_model.start_event(
        points_model.PointsAudit(user_id=1, guild_id=20, event=constants.Event.IN, time=t, active=True)
    )
    rows = points_model.get_events_for_member(1, 10)
    assert len(rows) == 1
    assert rows[0].guild_id == 10


def test_get_last_event_orders_by_time(points_session):  # noqa: ARG001
    points_model.start_event(
        points_model.PointsAudit(
            user_id=3,
            guild_id=1,
            event=constants.Event.IN,
            time=datetime.datetime(2024, 1, 1, 10, 0, 0),
            active=False,
        )
    )
    points_model.start_event(
        points_model.PointsAudit(
            user_id=3,
            guild_id=1,
            event=constants.Event.IN,
            time=datetime.datetime(2024, 1, 2, 10, 0, 0),
            active=True,
        )
    )
    last = points_model.get_last_event(3, 1)
    assert last is not None
    assert last.time.day == 2


def test_get_active_events_respects_include_zero(points_session):  # noqa: ARG001
    points_model.start_event(
        points_model.PointsAudit(
            user_id=0, guild_id=7, event=constants.Event.IN, time=datetime.datetime(2024, 1, 1, 10, 0, 0), active=True
        )
    )
    points_model.start_event(
        points_model.PointsAudit(
            user_id=1, guild_id=7, event=constants.Event.IN, time=datetime.datetime(2024, 1, 1, 11, 0, 0), active=True
        )
    )
    without_zero = points_model.get_active_events(7, include_0=False)
    assert len(without_zero) == 1
    assert without_zero[0].user_id == 1
    with_zero = points_model.get_active_events(7, include_0=True)
    assert len(with_zero) == 2


def test_get_events_since_time(points_session):  # noqa: ARG001
    pop_t = datetime.datetime(2024, 3, 1, 8, 0, 0)
    late_t = datetime.datetime(2024, 3, 1, 12, 0, 0)
    points_model.start_event(
        points_model.PointsAudit(user_id=1, guild_id=5, event=constants.Event.POP, time=pop_t, active=False)
    )
    points_model.start_event(
        points_model.PointsAudit(user_id=2, guild_id=5, event=constants.Event.IN, time=late_t, active=True)
    )
    evs = points_model.get_events_since_time(5, pop_t)
    assert len(evs) == 1
    assert evs[0].user_id == 2


def test_get_event_pairs_active_session(points_session):  # noqa: ARG001
    t = datetime.datetime(2024, 1, 10, 10, 0, 0)
    ev = points_model.PointsAudit(user_id=1, guild_id=1, event=constants.Event.IN, time=t, active=True)
    points_model.start_event(ev)
    pairs = points_model.get_event_pairs([ev])
    assert pairs[t] == datetime.datetime.max


def test_get_event_pairs_start_and_stop(points_session):  # noqa: ARG001
    t_in = datetime.datetime(2024, 1, 10, 10, 0, 0)
    start_ev = points_model.PointsAudit(user_id=1, guild_id=1, event=constants.Event.IN, time=t_in, active=True)
    points_model.start_event(start_ev)
    t_out = datetime.datetime(2024, 1, 10, 11, 0, 0)
    stop_ev = points_model.PointsAudit(
        user_id=1,
        guild_id=1,
        event=constants.Event.OUT,
        time=t_out,
        active=False,
        start_id=start_ev.id,
    )
    points_model.start_event(stop_ev)
    pairs = points_model.get_event_pairs([stop_ev, start_ev])
    assert pairs[t_in] == t_out


@freeze_time("2024-06-01T12:00:00")
def test_get_event_pairs_split_members_active(points_session):  # noqa: ARG001
    t = datetime.datetime(2024, 6, 1, 11, 0, 0)
    ev = points_model.PointsAudit(user_id=9, guild_id=3, event=constants.Event.IN, time=t, active=True)
    points_model.start_event(ev)
    pairs = points_model.get_event_pairs_split_members([ev])
    assert 9 in pairs
    assert pairs[9][t] == datetime.datetime(2024, 6, 1, 12, 10, 0)


def test_get_last_pop_time_from_db(points_session):  # noqa: ARG001
    pop_t = datetime.datetime(2023, 5, 1, 9, 0, 0)
    points_model.start_event(
        points_model.PointsAudit(user_id=0, guild_id=0, event=constants.Event.POP, time=pop_t, active=False)
    )
    got = points_model.get_last_pop_time()
    assert got.date() == pop_t.date()


def test_close_event_module_updates_db(points_session):  # noqa: ARG001
    t0 = datetime.datetime(2024, 1, 1, 9, 0, 0)
    start = points_model.PointsAudit(user_id=2, guild_id=1, event=constants.Event.IN, time=t0, active=True)
    points_model.start_event(start)
    start.active = False
    t1 = datetime.datetime(2024, 1, 1, 10, 0, 0)
    end = points_model.PointsAudit(
        user_id=2, guild_id=1, event=constants.Event.OUT, time=t1, active=False, start_id=start.id
    )
    points_model.close_event(start, end)
    again = points_model.get_event(start.id)
    assert again is not None
    assert again.active is False


def test_update_event(points_session):  # noqa: ARG001
    ev = points_model.PointsAudit(
        user_id=1, guild_id=1, event=constants.Event.IN, time=datetime.datetime(2024, 1, 1, 8, 0, 0), active=True
    )
    points_model.start_event(ev)
    ev.active = False
    points_model.update_event(ev)
    loaded = points_model.get_event(ev.id)
    assert loaded.active is False


def test_get_points_earned_and_by_member(points_session):
    now = datetime.datetime(2024, 4, 1, 10, 0, 0)
    points_session.add_all(
        [
            points_model.PointsEarned(user_id=10, guild_id=50, points=5, time=now),
            points_model.PointsEarned(user_id=10, guild_id=50, points=7, time=now),
            points_model.PointsEarned(user_id=11, guild_id=50, points=3, time=now),
        ]
    )
    points_session.commit()

    totals = points_model.get_points_earned(50)
    by_user = {row.user_id: row.points for row in totals}
    assert by_user[10] == 12
    assert by_user[11] == 3

    member_rows = points_model.get_points_earned_by_member(10, 50)
    assert len(member_rows) == 2
    assert sum(r.points for r in member_rows) == 12


def test_get_points_spent_and_by_member(points_session):
    now = datetime.datetime(2024, 4, 1, 10, 0, 0)
    points_session.add_all(
        [
            points_model.PointsSpent(user_id=20, guild_id=60, points=100, time=now),
            points_model.PointsSpent(user_id=20, guild_id=60, points=50, time=now),
        ]
    )
    points_session.commit()
    spent = points_model.get_points_spent(60)
    assert len(spent) == 2
    by_m = points_model.get_points_spent_by_member(20, 60)
    assert sum(s.points for s in by_m) == 150


@freeze_time("2024-04-15T12:00:00")
def test_get_points_earned_recently_filters_window(points_session):
    old = datetime.datetime(2024, 3, 1, 10, 0, 0)
    recent = datetime.datetime(2024, 4, 10, 10, 0, 0)
    points_session.add_all(
        [
            points_model.PointsEarned(user_id=30, guild_id=70, points=1, time=old),
            points_model.PointsEarned(user_id=31, guild_id=70, points=9, time=recent),
        ]
    )
    points_session.commit()
    rows = points_model.get_points_earned_recently(70, days=14)
    ids = {r.user_id for r in rows}
    assert 31 in ids
    assert 30 not in ids
