"""DB-backed raid-timer catalog, ToD/quake writes, and local feed build."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from datetime import datetime, timedelta
from importlib import resources
from zoneinfo import ZoneInfo

import sqlalchemy

from roboToald.db import base
from roboToald.db.models import raid_timers as rt_models
from roboToald.raidtargets import rt_windows

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
SOURCE_PRIORITY = {"admin": 4, "log_death": 3, "guild_chat": 2, "slash": 1, "discord": 1}
TOD_DEDUP_SECONDS = 300
CATALOG_RESOURCE = "p99_targets_default.json"


@dataclasses.dataclass
class RecordResult:
    status: str  # recorded | duplicate | superseded_existing | unknown_target
    target_name: str | None = None
    tod_utc: int | None = None


def load_default_catalog() -> list[dict]:
    path = resources.files("roboToald.raidtargets").joinpath("data", CATALOG_RESOURCE)
    return json.loads(path.read_text(encoding="utf-8"))["targets"]


def _spec_from_row(row: rt_models.RtTarget) -> rt_windows.TargetSpec:
    ranges = tuple((r.min_minutes, r.max_minutes) for r in row.ranges)
    return rt_windows.TargetSpec(
        name=row.name,
        short_name=row.short_name or "",
        aliases=row.aliases or "",
        era=row.era or "",
        zone=row.zone or "",
        ranges=ranges,
        window_count=row.window_count,
        quake_immune=bool(row.quake_immune),
        hidden=bool(row.hidden),
    )


def _insert_target_from_catalog(session, guild_id: int, entry: dict) -> rt_models.RtTarget:
    target = rt_models.RtTarget(
        guild_id=guild_id,
        name=entry["name"],
        short_name=entry.get("short_name") or "",
        aliases=entry.get("aliases") or "",
        era=entry.get("era") or "",
        zone=entry.get("zone") or "",
        hidden=bool(entry.get("hidden")),
        window_count=entry.get("window_count"),
        quake_immune=bool(entry.get("quake_immune")),
        note=entry.get("note"),
        seed_key=entry["name"],
        customized=False,
    )
    session.add(target)
    session.flush()
    for lo, hi in entry.get("ranges") or []:
        session.add(rt_models.RtRespawnRange(target_id=target.id, min_minutes=int(lo), max_minutes=int(hi)))
    return target


def seed_guild_if_empty(guild_id: int) -> int:
    with base.get_session() as session:
        existing = session.query(rt_models.RtTarget).filter_by(guild_id=guild_id).count()
        if existing:
            return 0
        catalog = load_default_catalog()
        for entry in catalog:
            _insert_target_from_catalog(session, guild_id, entry)
        session.commit()
        return len(catalog)


def sync_from_defaults(guild_id: int) -> tuple[int, int]:
    catalog = load_default_catalog()
    inserted = 0
    updated = 0
    with base.get_session() as session:
        by_seed = {
            t.seed_key: t for t in session.query(rt_models.RtTarget).filter_by(guild_id=guild_id).all() if t.seed_key
        }
        for entry in catalog:
            key = entry["name"]
            existing = by_seed.get(key)
            if existing is None:
                _insert_target_from_catalog(session, guild_id, entry)
                inserted += 1
                continue
            if existing.customized:
                continue
            existing.short_name = entry.get("short_name") or ""
            existing.aliases = entry.get("aliases") or ""
            existing.era = entry.get("era") or ""
            existing.zone = entry.get("zone") or ""
            existing.hidden = bool(entry.get("hidden"))
            existing.window_count = entry.get("window_count")
            existing.quake_immune = bool(entry.get("quake_immune"))
            existing.note = entry.get("note")
            for old in list(existing.ranges):
                session.delete(old)
            session.flush()
            for lo, hi in entry.get("ranges") or []:
                session.add(rt_models.RtRespawnRange(target_id=existing.id, min_minutes=int(lo), max_minutes=int(hi)))
            updated += 1
        session.commit()
    return inserted, updated


def list_specs(guild_id: int) -> list[rt_windows.TargetSpec]:
    with base.get_session() as session:
        rows = session.query(rt_models.RtTarget).filter_by(guild_id=guild_id).order_by(rt_models.RtTarget.id).all()
        return [_spec_from_row(r) for r in rows]


def current_tods(guild_id: int) -> dict[str, int]:
    """Latest ToD per target name (highest ``id``, not max tod_utc)."""
    with base.get_session() as session:
        # Subquery: max id per target_id for this guild
        subq = (
            session.query(
                rt_models.RtTod.target_id,
                sqlalchemy.func.max(rt_models.RtTod.id).label("max_id"),
            )
            .filter(rt_models.RtTod.guild_id == guild_id)
            .group_by(rt_models.RtTod.target_id)
            .subquery()
        )
        rows = (
            session.query(rt_models.RtTarget.name, rt_models.RtTod.tod_utc)
            .join(rt_models.RtTod, rt_models.RtTod.target_id == rt_models.RtTarget.id)
            .join(subq, rt_models.RtTod.id == subq.c.max_id)
            .filter(rt_models.RtTarget.guild_id == guild_id)
            .all()
        )
        return {name: int(tod) for name, tod in rows}


def last_quake(guild_id: int) -> int | None:
    with base.get_session() as session:
        row = (
            session.query(rt_models.RtQuake).filter_by(guild_id=guild_id).order_by(rt_models.RtQuake.id.desc()).first()
        )
        return int(row.quake_utc) if row else None


def build_feed_for_guild(guild_id: int, now_utc: int | None = None) -> dict:
    if now_utc is None:
        now_utc = int(time.time())
    return rt_windows.build_feed(
        list_specs(guild_id),
        current_tods(guild_id),
        last_quake(guild_id),
        now_utc,
        trim=True,
    )


def _alias_terms(aliases: str) -> list[str]:
    return [a.strip() for a in (aliases or "").split(",") if a.strip()]


def resolve_target(guild_id: int, query: str) -> rt_models.RtTarget | None:
    q = (query or "").strip()
    if not q:
        return None
    with base.get_session() as session:
        rows = session.query(rt_models.RtTarget).filter_by(guild_id=guild_id).all()
        # Detach with ranges for use outside session
        for r in rows:
            _ = r.ranges
            session.expunge(r)

    q_lower = q.lower()

    for row in rows:
        if row.name.lower() == q_lower:
            return row
    for row in rows:
        for alias in _alias_terms(row.aliases):
            if alias.lower() == q_lower:
                return row
    for row in rows:
        if (row.short_name or "").lower() == q_lower:
            return row

    substring_hits = [r for r in rows if q_lower in r.name.lower()]
    if len(substring_hits) == 1:
        return substring_hits[0]
    if len(substring_hits) > 1:
        return None

    containment: list[tuple[int, rt_models.RtTarget]] = []
    for row in rows:
        terms = [row.name] + _alias_terms(row.aliases)
        for term in terms:
            if re.search(rf"\b{re.escape(term)}\b", q, re.I):
                containment.append((len(term), row))
                break
    if not containment:
        return None
    containment.sort(key=lambda x: -x[0])
    best_len = containment[0][0]
    best = [r for ln, r in containment if ln == best_len]
    if len(best) != 1:
        return None
    return best[0]


def _priority(source: str) -> int:
    return SOURCE_PRIORITY.get(source, 0)


def record_tod(
    guild_id: int,
    target_query: str,
    tod_utc: int,
    source: str,
    reported_by: str = "",
    now_utc: int | None = None,
) -> RecordResult:
    if now_utc is None:
        now_utc = int(time.time())
    target = resolve_target(guild_id, target_query)
    if target is None:
        return RecordResult(status="unknown_target")

    with base.get_session() as session:
        existing = (
            session.query(rt_models.RtTod)
            .filter_by(guild_id=guild_id, target_id=target.id)
            .order_by(rt_models.RtTod.id.desc())
            .first()
        )
        if (
            existing is not None
            and abs(existing.tod_utc - tod_utc) <= TOD_DEDUP_SECONDS
            and now_utc - existing.created_at <= TOD_DEDUP_SECONDS
        ):
            if _priority(source) <= _priority(existing.source):
                return RecordResult(
                    status="duplicate",
                    target_name=target.name,
                    tod_utc=int(existing.tod_utc),
                )
            session.add(
                rt_models.RtTod(
                    guild_id=guild_id,
                    target_id=target.id,
                    tod_utc=int(tod_utc),
                    source=source,
                    reported_by=reported_by or "",
                    created_at=now_utc,
                )
            )
            session.commit()
            return RecordResult(
                status="superseded_existing",
                target_name=target.name,
                tod_utc=int(tod_utc),
            )

        session.add(
            rt_models.RtTod(
                guild_id=guild_id,
                target_id=target.id,
                tod_utc=int(tod_utc),
                source=source,
                reported_by=reported_by or "",
                created_at=now_utc,
            )
        )
        session.commit()
        return RecordResult(status="recorded", target_name=target.name, tod_utc=int(tod_utc))


def undo_last_tod(guild_id: int, target_query: str) -> rt_models.RtTod | None:
    target = resolve_target(guild_id, target_query)
    if target is None:
        return None
    with base.get_session() as session:
        latest = (
            session.query(rt_models.RtTod)
            .filter_by(guild_id=guild_id, target_id=target.id)
            .order_by(rt_models.RtTod.id.desc())
            .first()
        )
        if latest is None:
            return None
        session.delete(latest)
        session.commit()
        prev = (
            session.query(rt_models.RtTod)
            .filter_by(guild_id=guild_id, target_id=target.id)
            .order_by(rt_models.RtTod.id.desc())
            .first()
        )
        if prev is not None:
            session.expunge(prev)
        return prev


def record_quake(
    guild_id: int,
    quake_utc: int,
    source: str,
    reported_by: str = "",
    now_utc: int | None = None,
) -> RecordResult:
    if now_utc is None:
        now_utc = int(time.time())
    with base.get_session() as session:
        existing = (
            session.query(rt_models.RtQuake).filter_by(guild_id=guild_id).order_by(rt_models.RtQuake.id.desc()).first()
        )
        if (
            existing is not None
            and abs(existing.quake_utc - quake_utc) <= TOD_DEDUP_SECONDS
            and now_utc - existing.created_at <= TOD_DEDUP_SECONDS
        ):
            if _priority(source) <= _priority(existing.source):
                return RecordResult(status="duplicate", tod_utc=int(existing.quake_utc))
            session.add(
                rt_models.RtQuake(
                    guild_id=guild_id,
                    quake_utc=int(quake_utc),
                    source=source,
                    reported_by=reported_by or "",
                    created_at=now_utc,
                )
            )
            session.commit()
            return RecordResult(status="superseded_existing", tod_utc=int(quake_utc))

        session.add(
            rt_models.RtQuake(
                guild_id=guild_id,
                quake_utc=int(quake_utc),
                source=source,
                reported_by=reported_by or "",
                created_at=now_utc,
            )
        )
        session.commit()
        return RecordResult(status="recorded", tod_utc=int(quake_utc))


def parse_human_time(text: str, now_utc: int) -> int:
    """Parse human time as America/New_York → UTC epoch. Raises ValueError."""
    raw = (text or "").strip().lower()
    now_et = datetime.fromtimestamp(now_utc, tz=ET)
    if raw in ("", "now"):
        result = now_et
    else:
        result = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                naive = datetime.strptime(raw, fmt)
                result = naive.replace(tzinfo=ET)
                break
            except ValueError:
                pass
        if result is None:
            for fmt in ("%m/%d %H:%M:%S", "%m/%d %H:%M"):
                try:
                    naive = datetime.strptime(raw, fmt)
                    year = now_et.year
                    result = naive.replace(year=year, tzinfo=ET)
                    if result > now_et + timedelta(minutes=5):
                        result = result.replace(year=year - 1)
                    break
                except ValueError:
                    pass
        if result is None:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    naive = datetime.strptime(raw, fmt)
                    result = now_et.replace(
                        hour=naive.hour,
                        minute=naive.minute,
                        second=getattr(naive, "second", 0) or 0,
                        microsecond=0,
                    )
                    if result > now_et + timedelta(minutes=5):
                        result = result - timedelta(days=1)
                    break
                except ValueError:
                    pass
        if result is None:
            raise ValueError(f"Unrecognized time: {text!r}")

    if result > now_et + timedelta(minutes=5):
        raise ValueError("Time is more than 5 minutes in the future")
    return int(result.timestamp())


def get_board_message_ids(guild_id: int) -> tuple[int, list[int]]:
    with base.get_session() as session:
        row = session.get(rt_models.RtBoardMessage, guild_id)
        if row is None:
            return 0, []
        ids = [int(x) for x in (row.message_ids or "").split(",") if x.strip()]
        return int(row.channel_id), ids


def set_board_message_ids(guild_id: int, channel_id: int, message_ids: list[int]) -> None:
    with base.get_session() as session:
        row = session.get(rt_models.RtBoardMessage, guild_id)
        joined = ",".join(str(i) for i in message_ids)
        if row is None:
            session.add(rt_models.RtBoardMessage(guild_id=guild_id, channel_id=channel_id, message_ids=joined))
        else:
            row.channel_id = channel_id
            row.message_ids = joined
            session.add(row)
        session.commit()
