"""Tests for ``roboToald.raidtargets.rt_data`` scheduling and JSON decoding."""

from __future__ import annotations

import json

import pytest

from roboToald.raidtargets.rt_data import JSONDecoder, RaidTarget, RaidWindow, RaidWindowStatus


def _window(start, end, extrap=0):
    w = RaidWindow(start=start, end=end, extrapolationCount=extrap)
    return w


def test_raid_window_get_status_past_now_soon_later():
    w = _window(1000, 2000)
    assert w.get_status(now=1500) == RaidWindowStatus.NOW
    assert w.get_status(now=2500) == RaidWindowStatus.PAST
    # Far-future window: not within ``now + soon_threshold`` → LATER
    w_far = _window(200_000, 300_000)
    assert w_far.get_status(now=500) == RaidWindowStatus.LATER
    # Start in future but within default ``soon_threshold`` → SOON
    w2 = _window(1500, 2500)
    assert w2.get_status(now=1000, soon_threshold=600) == RaidWindowStatus.SOON


def test_raid_window_get_percent_elapsed():
    w = _window(1000, 3000)
    # midpoint of window in absolute time: start=1000, end=3000, duration 2000s
    # at now=2000, passed 1000s from start → 50%
    assert w.get_percent_elapsed(now=2000) == pytest.approx(0.5)


def test_raid_window_get_percent_elapsed_zero_duration_raises():
    w = RaidWindow(start=1000, end=1000, extrapolationCount=0)
    with pytest.raises(ZeroDivisionError):
        w.get_percent_elapsed(now=1000)


def test_raid_target_name_matches():
    t = RaidTarget(
        name="Lord Nagafen",
        shortName="Naggy",
        aliases="naggy,lord",
        era="classic",
        zone="LS",
        windows=[_window(0, 999999, 0)],
    )
    assert t.name_matches("Lord Nagafen")
    assert t.name_matches("NAGGY")
    assert not t.name_matches("other")


def test_raid_target_get_active_window_picks_first_non_past(monkeypatch):
    """``get_status`` uses ``time.time()`` when ``now`` is omitted — align with outer ``now``."""
    monkeypatch.setattr("roboToald.raidtargets.rt_data.time.time", lambda: 250.0)
    w_past = _window(0, 100, 0)
    w_next = _window(200, 300, 1)
    t = RaidTarget(
        name="T",
        shortName="t",
        aliases="",
        era="",
        zone="",
        windows=[w_past, w_next],
    )
    active = t.get_active_window(now=250.0)
    assert active is w_next


def test_json_decoder_round_trip_minimal():
    raw = json.dumps(
        {
            "name": "Boss",
            "shortName": "b",
            "aliases": "",
            "era": "e",
            "zone": "z",
            "windows": [{"start": 1, "end": 2, "extrapolationCount": 0}],
        }
    )
    obj = json.loads(raw, cls=JSONDecoder)
    assert isinstance(obj, RaidTarget)
    assert obj.name == "Boss"
    assert len(obj.windows) == 1
    assert isinstance(obj.windows[0], RaidWindow)
