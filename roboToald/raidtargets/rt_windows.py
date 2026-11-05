"""Pure raid-window computation (PHP ``targets-v2.json`` port).

No DB, Discord, or FastAPI imports. See docs/raid-timers-channel-plan.md.
"""

from __future__ import annotations

import dataclasses


LONG_RESPAWN_MINUTES = 6720
DEFAULT_LONG_WINDOW_COUNT = 3
FEED_MAX_FUTURE_WINDOWS = 3


@dataclasses.dataclass(frozen=True)
class TargetSpec:
    name: str
    short_name: str
    aliases: str  # comma-separated, may be ""
    era: str
    zone: str
    ranges: tuple[tuple[int, int], ...]  # minutes (min, max)
    window_count: int | None = None
    quake_immune: bool = False
    hidden: bool = False


def effective_window_count(spec: TargetSpec) -> int:
    if spec.window_count is not None:
        return spec.window_count
    if not spec.ranges:
        return 1
    min_m = min(lo for lo, _hi in spec.ranges)
    if min_m >= LONG_RESPAWN_MINUTES:
        return DEFAULT_LONG_WINDOW_COUNT
    return 1


def build_windows(
    spec: TargetSpec,
    tod_utc: int | None,
    last_quake_utc: int | None,
    now_utc: int,
    *,
    trim: bool = True,
) -> list[dict]:
    if tod_utc is None:
        return []
    if last_quake_utc is not None and tod_utc < last_quake_utc and not spec.quake_immune:
        return []

    count = effective_window_count(spec)
    windows: list[dict] = []
    for min_m, max_m in spec.ranges:
        for i in range(count):
            windows.append(
                {
                    "start": int(tod_utc + min_m * 60 * (i + 1)),
                    "end": int(tod_utc + max_m * 60 * (i + 1)),
                    "extrapolationCount": i,
                }
            )
    windows.sort(key=lambda w: (w["start"], w["end"]))

    if trim:
        windows = [w for w in windows if w["end"] >= now_utc]
        windows = windows[:FEED_MAX_FUTURE_WINDOWS]
    return windows


def build_target_entry(
    spec: TargetSpec,
    tod_utc: int | None,
    last_quake_utc: int | None,
    now_utc: int,
    *,
    trim: bool = True,
) -> dict:
    return {
        "name": spec.name,
        "shortName": spec.short_name,
        "aliases": spec.aliases,
        "era": spec.era,
        "zone": spec.zone,
        "windows": build_windows(spec, tod_utc, last_quake_utc, now_utc, trim=trim),
    }


def build_feed(
    specs: list[TargetSpec],
    tods: dict[str, int],
    last_quake_utc: int | None,
    now_utc: int,
    *,
    trim: bool = True,
) -> dict:
    raid_targets = []
    for spec in specs:
        if spec.hidden:
            continue
        raid_targets.append(
            build_target_entry(
                spec,
                tods.get(spec.name),
                last_quake_utc,
                now_utc,
                trim=trim,
            )
        )
    return {"raidTargets": raid_targets}
