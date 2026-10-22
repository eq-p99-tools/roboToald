"""Golden tests for ``roboToald.raidtargets.rt_windows`` (PHP port)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roboToald.raidtargets import rt_data, rt_windows
from roboToald.raidtargets.rt_windows import TargetSpec

FIXTURES = Path(__file__).parent / "fixtures" / "raid_timers"
ET = ZoneInfo("America/New_York")
QUAKE = 1698720311  # 2023-10-30 22:45:11 ET
NOW = 1699108792  # 2023-11-04 10:39:52 ET


def _et_epoch(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET).timestamp())


def _load_specs() -> dict[str, TargetSpec]:
    data = json.loads((FIXTURES / "p99_targets_default.json").read_text())
    out: dict[str, TargetSpec] = {}
    for t in data["targets"]:
        out[t["name"]] = TargetSpec(
            name=t["name"],
            short_name=t["short_name"],
            aliases=t["aliases"],
            era=t["era"],
            zone=t["zone"],
            ranges=tuple(tuple(r) for r in t["ranges"]),
            window_count=t.get("window_count"),
            quake_immune=bool(t.get("quake_immune")),
            hidden=bool(t.get("hidden")),
        )
    return out


def _load_tods() -> dict[str, int]:
    data = json.loads((FIXTURES / "p99_tods_fixture_2023_11_04.json").read_text())
    return {row["name"]: _et_epoch(row["tod_et"]) for row in data["tods"]}


SPECS = _load_specs()
TODS = _load_tods()


def test_quake_constant_matches_fixture():
    assert _et_epoch("2023-10-30 22:45:11") == QUAKE
    assert _et_epoch("2023-11-04 10:39:52") == NOW


def test_lord_nagafen_three_windows_untrimmed():
    spec = SPECS["Lord Nagafen"]
    tod = TODS["Lord Nagafen"]
    assert tod == 1698781840
    wins = rt_windows.build_windows(spec, tod, QUAKE, NOW, trim=False)
    assert wins == [
        {"start": 1699357840, "end": 1699415440, "extrapolationCount": 0},
        {"start": 1699933840, "end": 1700049040, "extrapolationCount": 1},
        {"start": 1700509840, "end": 1700682640, "extrapolationCount": 2},
    ]


def test_trakanon_allowlisted_three_windows():
    spec = SPECS["Trakanon"]
    tod = TODS["Trakanon"]
    assert tod == 1698993371
    wins = rt_windows.build_windows(spec, tod, QUAKE, NOW, trim=False)
    assert len(wins) == 3
    assert wins[0] == {"start": 1699223771, "end": 1699281371, "extrapolationCount": 0}


def test_statue_threshold_boundary():
    spec = SPECS["The Statue of Rallos Zek"]
    assert min(r[0] for r in spec.ranges) == 6720
    tod = TODS["The Statue of Rallos Zek"]
    wins = rt_windows.build_windows(spec, tod, QUAKE, NOW, trim=False)
    assert len(wins) == 3
    assert wins[0] == {"start": 1699124800, "end": 1699182400, "extrapolationCount": 0}


def test_quake_wipe_cazic():
    spec = SPECS["Cazic Thule"]
    tod = TODS["Cazic Thule"]
    assert tod < QUAKE
    assert rt_windows.build_windows(spec, tod, QUAKE, NOW, trim=False) == []


def test_quake_immune_ring_8():
    spec = SPECS["Ring 8"]
    assert spec.quake_immune
    tod = QUAKE - 3600
    wins = rt_windows.build_windows(spec, tod, QUAKE, NOW, trim=False)
    assert wins


def test_phinigel_short_respawn_one_window():
    spec = SPECS["Phinigel Autropos"]
    tod = NOW - 3600
    wins = rt_windows.build_windows(spec, tod, None, NOW, trim=False)
    assert len(wins) == 1
    assert wins[0] == {"start": tod + 43200, "end": tod + 43200, "extrapolationCount": 0}


def test_ragefire_multi_range_merge():
    spec = SPECS["Zordak Ragefire"]
    tod = NOW - 60
    wins = rt_windows.build_windows(spec, tod, None, NOW, trim=False)
    assert wins == [
        {"start": tod, "end": tod + 259200, "extrapolationCount": 0},
        {"start": tod + 43200, "end": tod + 115200, "extrapolationCount": 0},
    ]


def test_trim_past_trakanon():
    spec = SPECS["Trakanon"]
    tod = TODS["Trakanon"]
    wins = rt_windows.build_windows(spec, tod, QUAKE, 1699300000, trim=True)
    assert wins
    assert wins[0]["extrapolationCount"] == 1


def test_future_cap_scout_charisa():
    spec = SPECS["Scout Charisa"]
    assert rt_windows.effective_window_count(spec) == 144
    wins = rt_windows.build_windows(spec, NOW, None, NOW, trim=True)
    assert len(wins) == 3
    assert [w["extrapolationCount"] for w in wins] == [0, 1, 2]


def test_unknown_tod_empty():
    spec = SPECS["Lord Nagafen"]
    assert rt_windows.build_windows(spec, None, QUAKE, NOW) == []


def test_hidden_skipped_in_feed():
    feed = rt_windows.build_feed(list(SPECS.values()), TODS, QUAKE, NOW, trim=False)
    names = {t["name"] for t in feed["raidTargets"]}
    assert "King Tranix" not in names
    assert "Lord Nagafen" in names


def test_round_trip_json_decoder():
    feed = rt_windows.build_feed(list(SPECS.values()), TODS, QUAKE, NOW, trim=True)
    decoded = json.loads(json.dumps(feed), cls=rt_data.JSONDecoder)
    assert isinstance(decoded, list)
    assert all(isinstance(t, rt_data.RaidTarget) for t in decoded)
    naggy = next(t for t in decoded if t.name == "Lord Nagafen")
    assert naggy.name_matches("naggy")


def test_shady_goblin_window_count_is_sixty():
    assert rt_windows.effective_window_count(SPECS["a shady goblin"]) == 60


def test_build_target_entry_camel_case_keys():
    entry = rt_windows.build_target_entry(SPECS["Lord Nagafen"], TODS["Lord Nagafen"], QUAKE, NOW)
    assert set(entry.keys()) == {"name", "shortName", "aliases", "era", "zone", "windows"}
    if entry["windows"]:
        assert set(entry["windows"][0].keys()) == {"start", "end", "extrapolationCount"}
