"""Tests for pure helper functions in ``cmd_ds`` (DS slash command module)."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from roboToald import config
from roboToald import constants
from roboToald.db.models import points as points_model
from roboToald.discord_client.commands import cmd_ds


def test_get_effective_pop_time_uses_spawn_override():
    cmd_ds.SPAWN_OVERRIDE.clear()
    fixed = datetime.datetime(2024, 3, 1, 10, 0, 0, tzinfo=ZoneInfo("UTC"))
    cmd_ds.SPAWN_OVERRIDE[7] = fixed
    try:
        assert cmd_ds.get_effective_pop_time(7) == fixed
    finally:
        cmd_ds.SPAWN_OVERRIDE.pop(7, None)


def test_get_effective_pop_time_falls_back_to_db(monkeypatch):
    cmd_ds.SPAWN_OVERRIDE.clear()
    fallback = datetime.datetime(2024, 4, 1, 8, 0, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(cmd_ds.points_model, "get_last_pop_time", lambda: fallback)
    assert cmd_ds.get_effective_pop_time(999) == fallback


@pytest.mark.parametrize(
    ("minute", "expected"),
    [
        (0, 2.0),
        (50, 6.0),
        (100, 10.0),
        (500, 10.0),
    ],
)
def test_get_point_value_ramp_and_plateau(monkeypatch, minute: int, expected: float):
    monkeypatch.setattr(config, "SKP_STARTTIME", 0)
    monkeypatch.setattr(config, "SKP_MINIMUM", 2)
    monkeypatch.setattr(config, "SKP_BASELINE", 10)
    monkeypatch.setattr(config, "SKP_PLATEAU_MINUTE", 100)
    assert cmd_ds.get_point_value(minute) == expected


def test_sum_points_by_member_totals():
    out = cmd_ds.sum_points_by_member({1: {2.5: 2, 10.0: 1}, 2: {1.0: 5}})
    assert out[1] == (15, 3)  # 5+10 points, 3 minutes
    assert out[2] == (5, 5)


def test_calculate_points_for_session_with_mocked_windows(monkeypatch):
    t_pop = datetime.datetime(2024, 6, 1, 12, 0, tzinfo=datetime.timezone.utc)
    t_end = datetime.datetime(2024, 6, 1, 12, 5, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(cmd_ds.points_model, "get_last_pop_time", lambda: t_pop)
    monkeypatch.setattr(
        cmd_ds.points_model,
        "get_event_pairs_since_last_pop",
        lambda _gid: {100: {t_pop: t_end}},
    )
    monkeypatch.setattr(cmd_ds, "get_effective_pop_time", lambda _gid: t_pop)
    monkeypatch.setattr(config, "SKP_STARTTIME", 0)
    monkeypatch.setattr(config, "SKP_MINIMUM", 10)
    monkeypatch.setattr(config, "SKP_BASELINE", 10)
    monkeypatch.setattr(config, "SKP_PLATEAU_MINUTE", 60 * 24)

    result = cmd_ds.calculate_points_for_session(1, t_end)
    assert isinstance(result, dict)
    assert 100 in result
    assert isinstance(result[100], dict)


def test_cmd_ds_close_event_writes_stop_row(points_session, monkeypatch):
    monkeypatch.setattr(config, "SKP_STARTTIME", 0)
    start_t = datetime.datetime(2024, 1, 1, 12, 0, 0)
    start = points_model.PointsAudit(
        user_id=50,
        guild_id=10,
        event=constants.Event.IN,
        time=start_t,
        active=True,
    )
    points_model.start_event(start)
    assert start.id is not None

    stop_t = datetime.datetime(2024, 1, 1, 14, 0, 0)
    cmd_ds.close_event(start, stop_t)

    rows = points_session.query(points_model.PointsAudit).order_by(points_model.PointsAudit.id).all()
    assert len(rows) == 2
    assert rows[0].active is False
    assert rows[1].event == constants.Event.OUT
    assert rows[1].start_id == start.id
    assert rows[1].active is False
