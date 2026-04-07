"""Auto-attendance proposal on mob death.

When a raid target dies and an open event channel exists for it, computes which
SSO users were online for a meaningful portion of the event window (using session
history) and posts a suggested +Player attendance list with Apply/Ignore buttons.

The suggestion message contains copy-pasteable +lines so a raid lead can also
manually pick a subset by pasting into the channel (handled by _handle_add_player).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import disnake

from roboToald import config
from roboToald.db.models import sso as sso_model
from roboToald.db.raid_base import get_raid_session
from roboToald.db.raid_models.character import Character
from roboToald.db.raid_models.raid import Attendee, Event
from roboToald.discord_client import base as discord_base
from roboToald.eqdkp.client import EqdkpClient
from roboToald.raid.event_helpers import resolve_target

logger = logging.getLogger(__name__)

# Presence threshold: user must have been online for at least whichever is LOWER:
#   - 50% of the event duration, OR
#   - 2 minutes (MIN_PRESENCE_SECONDS)
# i.e. threshold = min(event_duration * 0.5, 120)
MIN_PRESENCE_SECONDS = 120.0
MIN_PRESENCE_FRACTION = 0.5

# Player character cache: (guild_id, discord_user_id) -> (player_char_name, all_char_names_lower, timestamp)
_player_char_cache: dict[tuple[int, int], tuple[str, frozenset[str], float]] = {}
PLAYER_CHAR_CACHE_TTL = 3600.0  # 1 hour

CUSTOM_ID_APPLY = "auto_att_apply"
CUSTOM_ID_IGNORE = "auto_att_ignore"


# ---------------------------------------------------------------------------
# Session overlap calculation
# ---------------------------------------------------------------------------


def _compute_overlap_seconds(
    first_seen: datetime,
    last_seen: datetime,
    event_start: datetime,
    death_time: datetime,
) -> float:
    """Seconds a session overlaps with [event_start, death_time]. Both naive local time."""
    overlap_start = max(first_seen, event_start)
    overlap_end = min(last_seen, death_time)
    delta = (overlap_end - overlap_start).total_seconds()
    return max(0.0, delta)


def _build_user_overlaps(
    sessions: list,
    event_start: datetime,
    death_time: datetime,
) -> dict[int, tuple[float, str]]:
    """
    Given SSOCharacterSession rows overlapping the event window, return:
        discord_user_id -> (total_overlap_seconds, dominant_character_name)

    The dominant character is whichever character_name accumulated the most
    overlap time for that Discord user.
    """
    user_char_overlap: dict[int, dict[str, float]] = {}
    for s in sessions:
        overlap = _compute_overlap_seconds(s.first_seen, s.last_seen, event_start, death_time)
        if overlap <= 0:
            continue
        uid = s.discord_user_id
        char = s.character_name
        user_char_overlap.setdefault(uid, {})
        user_char_overlap[uid][char] = user_char_overlap[uid].get(char, 0.0) + overlap

    result: dict[int, tuple[float, str]] = {}
    for uid, char_map in user_char_overlap.items():
        total = sum(char_map.values())
        dominant_char = max(char_map, key=char_map.__getitem__)
        result[uid] = (total, dominant_char)
    return result


# ---------------------------------------------------------------------------
# EQDKP player character cache
# ---------------------------------------------------------------------------


async def _get_player_character(
    guild_id: int,
    discord_user_id: int,
) -> tuple[str, frozenset[str]] | None:
    """
    Return (player_char_name, all_eqdkp_char_names_lowercase) for a Discord user,
    using an in-memory TTL cache to avoid repeated API calls per kill.

    player_char_name is picked as the first character alphabetically from EQDKP.
    Returns None if EQDKP is not configured, the lookup fails, or the user has
    no characters in EQDKP.
    """
    if not config.eqdkp_is_configured(guild_id):
        return None

    cache_key = (guild_id, discord_user_id)
    cached = _player_char_cache.get(cache_key)
    if cached and time.monotonic() - cached[2] < PLAYER_CHAR_CACHE_TTL:
        return cached[0], cached[1]

    try:
        eqdkp = EqdkpClient(guild_id)
        members = await eqdkp.find_characters_by_discord_id(discord_user_id)
    except Exception:
        logger.exception("EQDKP lookup failed for discord_user_id=%s guild=%s", discord_user_id, guild_id)
        return None

    names = sorted(m["name"] for m in members if m.get("name"))
    if not names:
        return None

    player_char = names[0]
    all_chars = frozenset(n.lower() for n in names)
    _player_char_cache[cache_key] = (player_char, all_chars, time.monotonic())
    return player_char, all_chars


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def _fmt_minutes(seconds: float) -> str:
    """Format a duration in seconds as 'Xm', minimum 1m."""
    return f"{max(1, int(seconds / 60))}m"


def _discord_name_suffix(member: disnake.Member | None, user_id: int) -> str:
    """Trailing `` [label]`` for suggestion lines; brackets in the label are sanitized."""
    if member is None:
        inner = str(user_id)
    else:
        raw = (member.display_name or member.name or "").strip() or str(user_id)
        inner = raw.replace("[", "(").replace("]", ")")
    return f" [{inner}]"


async def _resolve_member(guild: disnake.Guild, user_id: int) -> disnake.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (disnake.NotFound, disnake.HTTPException):
        logger.debug("Could not resolve guild member user_id=%s in guild %s", user_id, guild.id)
        return None


def _make_proposal_view(guild_id: int) -> disnake.ui.View:
    view = disnake.ui.View(timeout=None)
    view.add_item(
        disnake.ui.Button(
            label="Apply",
            style=disnake.ButtonStyle.green,
            custom_id=f"{CUSTOM_ID_APPLY}:{guild_id}",
        )
    )
    view.add_item(
        disnake.ui.Button(
            label="Ignore",
            style=disnake.ButtonStyle.secondary,
            custom_id=f"{CUSTOM_ID_IGNORE}:{guild_id}",
        )
    )
    return view


def _make_resolved_view(label: str) -> disnake.ui.View:
    view = disnake.ui.View()
    view.add_item(
        disnake.ui.Button(
            label=label,
            style=disnake.ButtonStyle.secondary,
            disabled=True,
            custom_id="auto_att_done",
        )
    )
    return view


# ---------------------------------------------------------------------------
# propose_online_players -- scheduled on the Discord event loop from server.py
# ---------------------------------------------------------------------------


async def propose_online_players(guild_id: int, mob_name: str, discord_client) -> None:
    """Compute session-based attendance suggestions for a mob death and post to open event channels.

    Called via asyncio.run_coroutine_threadsafe from _ws_handle_mob_death so that
    it runs on the Discord client's event loop.
    """
    if not config.get_raid_setting(guild_id, "auto_attendance"):
        return
    if not config.eqdkp_is_configured(guild_id):
        return

    # death_time in naive local time (same as SSOCharacterSession timestamps)
    death_time_local = datetime.now()
    local_tz = datetime.now().astimezone().tzinfo

    with get_raid_session(guild_id) as session:
        targets, _ = resolve_target(mob_name, session)
        if not targets:
            return
        target = targets[0]

        events = session.query(Event).filter(Event.target_id == target.id, Event.killed.isnot(True)).all()
        if not events:
            return

        # Capture scalar attributes before the session closes
        event_rows = [(evt.id, evt.created_at, evt.channel_id) for evt in events]

    for evt_id, evt_created_at, evt_channel_id in event_rows:
        if not evt_created_at:
            continue

        # Event.created_at is naive UTC; convert to naive local for session comparison
        event_start_local = evt_created_at.replace(tzinfo=timezone.utc).astimezone(local_tz).replace(tzinfo=None)

        event_duration = max(1.0, (death_time_local - event_start_local).total_seconds())
        threshold = min(event_duration * MIN_PRESENCE_FRACTION, MIN_PRESENCE_SECONDS)

        sessions = sso_model.get_sessions_in_range(guild_id, event_start_local, death_time_local)
        if not sessions:
            continue

        user_overlaps = _build_user_overlaps(sessions, event_start_local, death_time_local)
        qualifying = [(uid, overlap, char) for uid, (overlap, char) in user_overlaps.items() if overlap >= threshold]
        if not qualifying:
            continue

        guild = discord_client.get_guild(guild_id)
        if not guild:
            continue

        # Resolve EQDKP characters and build suggestion lines
        lines: list[str] = []
        for discord_user_id, overlap_secs, online_char in sorted(qualifying, key=lambda x: x[2].lower()):
            result = await _get_player_character(guild_id, discord_user_id)
            if result is None:
                continue
            player_char, all_eqdkp_chars = result
            time_str = _fmt_minutes(overlap_secs)
            member = await _resolve_member(guild, discord_user_id)
            disc_suffix = _discord_name_suffix(member, discord_user_id)
            if online_char.lower() in all_eqdkp_chars:
                # Online character belongs to this user -- add directly
                lines.append(f"+{online_char} ({time_str}){disc_suffix}")
            else:
                # Online character is a shared/bot account -- add as "player on box"
                lines.append(f"+{player_char} on {online_char} ({time_str}){disc_suffix}")

        if not lines:
            continue

        channel = guild.get_channel(int(evt_channel_id))
        if not channel:
            continue

        event_mins = _fmt_minutes(event_duration)
        header = f"**Suggested attendance for `{mob_name}`** (`{len(lines)}` qualifying, event open `{event_mins}`):"
        body = "\n".join(lines)
        content = f"{header}\n```diff\n{body}\n```"
        await channel.send(content, view=_make_proposal_view(guild_id))
        logger.info(
            "Posted auto-attendance suggestion for %s in channel %s (%d lines)",
            mob_name,
            evt_channel_id,
            len(lines),
        )


# ---------------------------------------------------------------------------
# Button handler -- Apply / Ignore
# ---------------------------------------------------------------------------


@discord_base.DISCORD_CLIENT.listen("on_button_click")
async def on_auto_att_button(inter: disnake.MessageInteraction) -> None:
    custom_id = inter.component.custom_id or ""
    is_apply = custom_id.startswith(f"{CUSTOM_ID_APPLY}:")
    is_ignore = custom_id.startswith(f"{CUSTOM_ID_IGNORE}:")
    if not is_apply and not is_ignore:
        return

    guild_id = int(custom_id.split(":", 1)[1])

    if is_ignore:
        await inter.response.edit_message(view=_make_resolved_view(f"Ignored by {inter.author.display_name}"))
        return

    # Apply: parse +lines from the code block in the original message, strip (Xm) annotations
    code_match = re.search(r"```\w*\n(.*?)\n```", inter.message.content or "", re.DOTALL)
    if not code_match:
        await inter.response.send_message("```diff\n- Could not parse suggestion lines.```", ephemeral=True)
        return

    raw_lines = [ln.strip() for ln in code_match.group(1).splitlines() if ln.strip().startswith("+")]
    if not raw_lines:
        await inter.response.edit_message(
            view=_make_resolved_view(f"Applied by {inter.author.display_name} (nothing to add)")
        )
        return

    # Strip trailing (Xm) and optional " [Discord name]" suffix before processing
    cleaned_lines = [re.sub(r"\s*\(\d+m\)\s*(\[[^\]]+\])?\s*$", "", ln) for ln in raw_lines]

    eqdkp_client: EqdkpClient | None = None
    if config.eqdkp_is_configured(guild_id):
        eqdkp_client = EqdkpClient(guild_id)

    out = ["```diff"]

    with get_raid_session(guild_id) as session:
        evt = session.query(Event).filter_by(channel_id=str(inter.channel_id)).first()
        if not evt:
            await inter.response.send_message("```diff\n- No event found for this channel.```", ephemeral=True)
            return

        for line in cleaned_lines:
            stripped = re.sub(r"^\+", "", line).strip()
            if not stripped:
                continue
            parts = stripped.split(" ", 1)
            player_name = re.sub(r"[^A-Za-z]", "", parts[0]).capitalize()
            reason = parts[1].strip("() ") if len(parts) > 1 else ""

            if not player_name:
                continue

            char = session.query(Character).filter(Character.name.ilike(player_name)).first()
            if not char:
                char = Character(name=player_name)
                session.add(char)
                session.flush()

            if eqdkp_client and not char.eqdkp_member_id:
                try:
                    member = await eqdkp_client.find_character(char.name)
                except Exception as exc:
                    logger.exception("EQdkp find_character failed for %s", char.name)
                    out.append(f"- {char.name}: EQdkp lookup failed ({exc}). Skipped.")
                    continue
                if member:
                    char.eqdkp_member_id = member.get("id")
                    char.eqdkp_user_id = member.get("user_id")
                    char.eqdkp_main_id = member.get("main_id")
                    session.flush()
                else:
                    out.append(f"- {player_name}: not found on EQDKP. Skipped.")
                    continue

            on_character = None
            on_match = re.match(r"^on\s+(.+)$", reason, re.IGNORECASE)
            if on_match:
                on_name = on_match.group(1).strip().capitalize()
                on_character = session.query(Character).filter(Character.name.ilike(on_name)).first()

            if on_character:
                on_existing = (
                    session.query(Attendee).filter_by(event_id=evt.id, on_character_id=str(on_character.id)).first()
                )
                if on_existing:
                    c = session.query(Character).filter_by(id=int(on_existing.character_id)).first()
                    out.append(f"- {c.name if c else '?'} is already on {on_character.name}")
                    continue

            existing = session.query(Attendee).filter_by(event_id=evt.id, character_id=str(char.id)).first()
            if existing:
                out.append(f"- {char.name} already exists in this event")
                continue

            att = Attendee(event_id=evt.id, character_id=str(char.id), reason=reason)
            if on_character:
                att.on_character_id = str(on_character.id)
            session.add(att)
            session.flush()

            msg_text = f"+ {char.name} was added"
            if reason:
                msg_text += f" ({reason})"
            out.append(msg_text)

            if on_character:
                dup = (
                    session.query(Attendee)
                    .filter_by(event_id=evt.id, character_id=str(on_character.id))
                    .filter(Attendee.on_character_id.is_(None))
                    .first()
                )
                if dup:
                    session.delete(dup)
                    out.append(f"- {on_character.name} removed (replaced by boxed entry)")

        session.commit()

    out.append("```")
    await inter.response.edit_message(view=_make_resolved_view(f"Applied by {inter.author.display_name}"))
    await inter.followup.send("\n".join(out))
