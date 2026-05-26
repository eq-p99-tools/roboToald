"""Event management helpers. Port of create_event.rb, rte_tracking_helper.rb, raid_status_message.rb."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import disnake

from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.raid import Event, Attendee, Removal, Fte
from roboToald.db.raid_models.target import Target, TargetAlias
from roboToald.db.raid_models.tracking import Tracking
from roboToald.db.raid_models.loot import EventLoot, Item, LootTable
from roboToald.db.raid_models.character import Character

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

ET = zoneinfo.ZoneInfo("America/New_York")


def _time_ago_in_words(dt: datetime) -> str:
    """Precise time-ago string matching Ruby's DOTIW gem output."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    total_seconds = int((now - dt).total_seconds())
    if total_seconds < 60:
        return "less than a minute"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts: list[str] = []
    if days == 1:
        parts.append("1 day")
    elif days > 1:
        parts.append(f"{days} days")
    if hours == 1:
        parts.append("1 hour")
    elif hours > 1:
        parts.append(f"{hours} hours")
    if minutes == 1:
        parts.append("1 minute")
    elif minutes > 1:
        parts.append(f"{minutes} minutes")

    if not parts:
        return "less than a minute"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def resolve_target(name: str, session: Session) -> tuple[list[Target], list[TargetAlias]]:
    """Resolve a target by name or alias, returning (targets, aliases).

    Pass 1: substring match where the query appears inside ``Target.name`` / alias (user-typed
    partials). Pass 2: when pass 1 finds nothing, match where the **incoming string contains**
    the stored name or alias (EQ log lines often use full mob names; DB rows use short names).
    On multiple pass-2 hits, prefer the longest matching stored token.
    """
    name_lower = name.strip().lower()
    aliases = session.query(TargetAlias).filter(TargetAlias.name.ilike(f"%{name_lower}%")).all()
    if len(aliases) > 1:
        exact = [a for a in aliases if a.name.lower().strip() == name_lower]
        if exact:
            aliases = exact

    targets = session.query(Target).filter(Target.name.ilike(f"%{name_lower}%")).all()
    if aliases:
        alias_target_ids = [a.target_id for a in aliases]
        alias_targets = session.query(Target).filter(Target.id.in_(alias_target_ids)).all()
        existing_ids = {t.id for t in targets}
        targets.extend(t for t in alias_targets if t.id not in existing_ids)

    if len(targets) > 1:
        exact = [t for t in targets if t.name.lower().strip() == name_lower]
        if exact:
            targets = exact

    if not targets:
        # Pass 2: full EQ mob string contains short ``Target.name`` or ``TargetAlias.name``.
        best_by_id: dict[int, tuple[int, Target]] = {}
        for t in session.query(Target).all():
            tn = t.name.lower().strip()
            if tn and tn in name_lower:
                score = len(tn)
                prev = best_by_id.get(t.id)
                if prev is None or score > prev[0]:
                    best_by_id[t.id] = (score, t)
        for a in session.query(TargetAlias).all():
            an = a.name.lower().strip()
            if not an or an not in name_lower:
                continue
            tgt = session.query(Target).filter_by(id=a.target_id).first()
            if not tgt:
                continue
            score = len(an)
            prev = best_by_id.get(tgt.id)
            if prev is None or score > prev[0]:
                best_by_id[tgt.id] = (score, tgt)
        if best_by_id:
            max_score = max(s for s, _ in best_by_id.values())
            picked = [t for s, t in best_by_id.values() if s == max_score]
            targets = [picked[0]] if len(picked) > 1 else picked
            aliases = []

    return targets, aliases


def get_shortest_alias(target: Target, session: Session) -> str:
    aliases = session.query(TargetAlias).filter_by(target_id=target.id).all()
    if aliases:
        return min((a.name for a in aliases), key=len)
    return target.name


def rte_tracking_creator(
    evt: Event,
    target: Target | None,
    child_target: Target | None,
    session: Session,
    target_name: str | None = None,
) -> list[str]:
    """Close open trackings and add tracking-based attendees. Returns messages to send."""
    messages: list[str] = []
    is_quake = (target_name or "").lower().find("quake") != -1
    this_event_tracker_ids: list[int] = []

    if target:
        trackings = session.query(Tracking).filter_by(target_id=target.id, end_time=None).all()
        if trackings:
            this_event_tracker_ids = [t.id for t in trackings]
            session.query(Tracking).filter_by(target_id=target.id, end_time=None).update(
                {"end_time": datetime.now(timezone.utc), "close_event_id": evt.id}
            )
            messages.append(f"```diff\n+ All active RTE for {target.name} was closed due to event.```")
    elif is_quake:
        quake_ids = [t.id for t in session.query(Target).filter_by(close_on_quake=True).all()]
        if quake_ids:
            trackings = (
                session.query(Tracking).filter(Tracking.target_id.in_(quake_ids), Tracking.end_time.is_(None)).all()
            )
            if trackings:
                session.query(Tracking).filter(Tracking.target_id.in_(quake_ids), Tracking.end_time.is_(None)).update(
                    {"end_time": datetime.now(timezone.utc), "close_event_id": evt.id},
                    synchronize_session="fetch",
                )
                messages.append("```diff\n+ All active RTE on applicable targets were closed due to QUAKE.```")

    pull_other = False
    if child_target and child_target.pull_other_rte_in:
        pull_other = True
    elif target and target.pull_other_rte_in:
        pull_other = True

    trackings_to_add: list[Tracking] = []
    if pull_other:
        exclude_ids = [t.id for t in session.query(Target).filter_by(rte_attendence=False).all()]
        q = session.query(Tracking).filter(Tracking.end_time.is_(None))
        if exclude_ids:
            q = q.filter(~Tracking.target_id.in_(exclude_ids))
        if target:
            q = q.filter(Tracking.target_id != target.id)
        trackings_to_add.extend(q.all())

    if this_event_tracker_ids:
        trackings_to_add.extend(session.query(Tracking).filter(Tracking.id.in_(this_event_tracker_ids)).all())

    for tracking in trackings_to_add:
        existing = session.query(Attendee).filter_by(character_id=str(tracking.character_id), event_id=evt.id).first()
        if existing:
            continue
        tracked_target = session.query(Target).get(tracking.target_id)
        character = session.query(Character).get(tracking.character_id)
        if not character or not tracked_target:
            continue
        args = {
            "tracking_id": str(tracking.id),
            "character_id": str(character.id),
            "event_id": evt.id,
            "reason": f"Tracking/RTE on {tracked_target.name}",
        }
        if tracking.on_character_id:
            on_char = session.query(Character).get(tracking.on_character_id)
            if on_char:
                args["on_character_id"] = str(on_char.id)
                args["reason"] += f" (on {on_char.name})"
        session.add(Attendee(**args))

    session.flush()
    return messages


def build_target_loot_table_lines(evt: Event, target: Target, session: Session) -> list[str]:
    lines = [
        f"```diff\n+ Target is set as {target.name}. DKP value is {evt.dkp_value}. "
        f"No Kill DKP value is {evt.nokill_dkp_value or 0}",
        "",
        "+ Loot Table:",
    ]
    loot_entries = (
        session.query(LootTable)
        .filter(LootTable.target_id == target.id)
        .order_by(LootTable.from_group, Item.name)
        .join(Item)
        .all()
    )
    # Reserve space for the suffix, closing fence, and the "What's next?" block
    # that gets appended after this in _perform_create_event (~350 chars).
    char_budget = 2000 - 400
    current_len = sum(len(line) + 1 for line in lines)
    shown = 0
    for lt in loot_entries:
        entry = f"+  {lt.item.name} (ID: {lt.item.id})"
        # +1 for the newline, +50 for the potential truncation suffix + closing fence
        if current_len + len(entry) + 1 + 50 > char_budget:
            break
        lines.append(entry)
        current_len += len(entry) + 1
        shown += 1
    remaining = len(loot_entries) - shown
    if remaining > 0:
        lines.append(f"+  ... and {remaining} more items (use /loot add autocomplete to see all)")
    lines.append("```")
    return lines


def build_raid_status_embed(channel_id: str, guild_id: int) -> disnake.Embed:
    """Build the raid status embed for an event channel."""
    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=channel_id).first()
        if not evt:
            return disnake.Embed(title="Raid Status", description="No event found.")

        total_dkp_spend = 0

        attendees = session.query(Attendee).filter_by(event_id=evt.id, tracking_id=None).all()

        att_chars: list[tuple[Attendee, Character]] = []
        for att in attendees:
            char = session.query(Character).filter_by(id=int(att.character_id)).first() if att.character_id else None
            if char:
                att_chars.append((att, char))

        user_id_groups: dict[str, list[str]] = {}
        for _, char in att_chars:
            uid = char.eqdkp_user_id
            if uid and str(uid) != "0":
                user_id_groups.setdefault(str(uid), []).append(char.name)
        dup_user_ids = {uid for uid, names in user_id_groups.items() if len(names) > 1}

        attendance_lines = []
        for att, char in att_chars:
            uid = str(char.eqdkp_user_id) if char.eqdkp_user_id else None
            is_dup = uid is not None and uid in dup_user_ids

            if att.on_character_id:
                on_char = session.query(Character).filter_by(id=int(att.on_character_id)).first()
                line = f"{char.name} on {on_char.name}" if on_char else char.name
            elif att.reason:
                line = f"{char.name} ({att.reason})"
            else:
                line = char.name

            if is_dup:
                others = [n for n in user_id_groups[uid] if n != char.name]
                line = f"- {line} [dup: same player as {', '.join(others)}]"
            else:
                line = f"+ {line}"

            attendance_lines.append(line)

        if not attendance_lines:
            attendance_lines.append("- There are no attendees added yet. Please submit logs.")

        tracker_lines = []
        tracker_attendees = (
            session.query(Attendee).filter(Attendee.event_id == evt.id, Attendee.tracking_id.isnot(None)).all()
        )
        for att in tracker_attendees:
            tracking = session.query(Tracking).get(int(att.tracking_id)) if att.tracking_id else None
            if not tracking:
                continue
            trk_target = session.query(Target).get(tracking.target_id) if tracking.target_id else None
            char = session.query(Character).filter_by(id=int(att.character_id)).first() if att.character_id else None
            if not char or not trk_target:
                continue
            msg = f"+ {char.name} ({tracking.role_name}, {trk_target.name})"
            if tracking.on_character_id:
                on_char = session.query(Character).get(tracking.on_character_id)
                if on_char:
                    msg += f" on {on_char.name}"
            tracker_lines.append(msg)

        fte_lines = []
        ftes = session.query(Fte).filter_by(event_id=evt.id).all()
        if ftes:
            fte_lines.append("```diff")
            for fte in ftes:
                char = session.query(Character).get(fte.character_id) if fte.character_id else None
                if char:
                    fte_lines.append(f"+ {char.name} (DKP: {fte.dkp}, ID: {fte.id})")
            fte_lines.append("```")

        removal_lines = []
        removals = session.query(Removal).filter_by(event_id=evt.id).all()
        if removals:
            removal_lines.append("```diff")
            for rem in removals:
                char = session.query(Character).get(rem.character_id) if rem.character_id else None
                if char:
                    if rem.reason:
                        removal_lines.append(f"+ {char.name} ({rem.reason})")
                    else:
                        removal_lines.append(f"+ {char.name}")
            removal_lines.append("```")

        loot_lines = []
        event_loots = session.query(EventLoot).filter_by(event_id=evt.id).all()
        for el in event_loots:
            item = session.query(Item).get(el.item_id) if el.item_id else None
            char = session.query(Character).get(el.character_id) if el.character_id else None
            if item and char:
                loot_lines.append(f"+ {item.name}: {el.dkp} DKP to {char.name} (ID: {el.id})")
                total_dkp_spend += el.dkp or 0

        details = ["```diff"]
        target = session.query(Target).get(evt.target_id) if evt.target_id else None
        name = target.name if target else (evt.name or "Unknown")
        if evt.created_at:
            et_time = evt.created_at.replace(tzinfo=timezone.utc).astimezone(ET)
            time_str = et_time.strftime("%Y-%m-%d %I:%M %p")
            ago = _time_ago_in_words(evt.created_at)
            details.append(f"+ {name} added at {time_str} ({ago} ago)")
        else:
            details.append(f"+ {name}")
        num_dups = sum(1 for _, c in att_chars if str(c.eqdkp_user_id or "") in dup_user_ids)
        if num_dups:
            details.append(f"+ Total Attendees: {len(attendees)} ({num_dups} duplicate-player)")
        else:
            details.append(f"+ Total Attendees: {len(attendees)}")

        if target or evt.dkp is not None:
            suffix = ""
            if evt.killed is False:
                suffix = " (Not killed)"
            elif evt.killed is True:
                suffix = " (Killed)"
            else:
                suffix = " (If killed)"
            details.append(f"+ DKP: {evt.dkp_value}{suffix}")
        else:
            details.append("- DKP: No target set")

        details.append(f"+ DKP Spent: {total_dkp_spend}")
        details.append(f"+ Event ID: {evt.id}")
        details.append("```")

        embed = disnake.Embed(title="Raid Status")

        def _chunk_field(title: str, lines: list[str], max_len: int = 900):
            texts, buf = [], ""
            for line in sorted(lines):
                if len(buf + line + "\n") > max_len:
                    texts.append(buf)
                    buf = ""
                buf += line + "\n"
            if buf:
                texts.append(buf)
            for i, text in enumerate(texts):
                embed.add_field(
                    name=title if i == 0 else f"{title} (cont.)",
                    value=f"```diff\n{text}```",
                    inline=False,
                )

        _chunk_field("Attendees", attendance_lines)
        if tracker_lines:
            _chunk_field("Trackers", tracker_lines)
        if fte_lines:
            embed.add_field(name="FTEs", value="\n".join(fte_lines), inline=False)
        if removal_lines:
            embed.add_field(name="Removals", value="\n".join(removal_lines), inline=False)
        if loot_lines:
            _chunk_field("Loot", loot_lines)
        embed.add_field(name="Event Review", value="\n".join(details), inline=False)

        return embed
