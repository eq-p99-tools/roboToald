"""Auto-attendance proposal on mob death.

When a raid target dies and an open event channel exists for it, computes which
SSO users were online for at least the configured percentage of the event window (using session
history) and posts a suggested +Player attendance list with Kill / No Kill / Ignore
buttons (legacy messages may still show Apply).

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
from roboToald.raid import permissions as perms
from roboToald.raid.event_helpers import resolve_target

logger = logging.getLogger(__name__)

# Presence threshold: overlap must be at least ``presence_percent``% of the event duration (default 50%).
# Users can re-run reconcile with a lower percentage to include more people.
MIN_PRESENCE_PERCENT = 50.0

# Player character cache: (guild_id, discord_user_id) -> (player_char_name, all_char_names_lower, timestamp)
_player_char_cache: dict[tuple[int, int], tuple[str, frozenset[str], float]] = {}
PLAYER_CHAR_CACHE_TTL = 3600.0  # 1 hour

CUSTOM_ID_KILL = "auto_att_kill"
CUSTOM_ID_NOKILL = "auto_att_nokill"
CUSTOM_ID_IGNORE = "auto_att_ignore"
# Legacy suggestion messages (before Kill / No Kill buttons)
CUSTOM_ID_APPLY = "auto_att_apply"


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


def qualifying_players_for_event_window(
    guild_id: int,
    event_start: datetime,
    end_time: datetime,
    presence_percent: float = MIN_PRESENCE_PERCENT,
) -> tuple[list[tuple[int, float, str]], float]:
    """
    Return (qualifying rows, threshold_seconds) using the same rules as auto-attendance proposals.

    Each row is ``(discord_user_id, overlap_seconds, dominant_character_name)``, sorted by character name.
    ``event_start`` and ``end_time`` must be naive datetimes in local time (same convention as SSO sessions).

    ``presence_percent`` is the minimum percentage of the event duration (e.g. ``50`` for 50%).
    """
    if presence_percent <= 0 or presence_percent > 100:
        msg = f"presence_percent must be in (0, 100], got {presence_percent}"
        raise ValueError(msg)
    event_duration = max(1.0, (end_time - event_start).total_seconds())
    threshold = event_duration * (presence_percent / 100.0)
    sessions = sso_model.get_sessions_in_range(guild_id, event_start, end_time)
    if not sessions:
        return [], threshold
    user_overlaps = _build_user_overlaps(sessions, event_start, end_time)
    qualifying = [(uid, overlap, char) for uid, (overlap, char) in user_overlaps.items() if overlap >= threshold]
    qualifying.sort(key=lambda x: x[2].lower())
    return qualifying, threshold


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


async def format_qualifying_proposal_lines(
    guild_id: int,
    qualifying: list[tuple[int, float, str]],
    guild: disnake.Guild,
) -> list[str]:
    """Build ``+`` lines (EQDKP / on-box logic) for mob-death suggestions and ``/sso reconcile`` proposals."""
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
            lines.append(f"+{online_char} ({time_str}){disc_suffix}")
        else:
            lines.append(f"+{player_char} on {online_char} ({time_str}){disc_suffix}")
    return lines


def _make_proposal_view(guild_id: int) -> disnake.ui.View:
    view = disnake.ui.View(timeout=None)
    view.add_item(
        disnake.ui.Button(
            label="Kill",
            style=disnake.ButtonStyle.success,
            custom_id=f"{CUSTOM_ID_KILL}:{guild_id}",
        )
    )
    view.add_item(
        disnake.ui.Button(
            label="No Kill",
            style=disnake.ButtonStyle.primary,
            custom_id=f"{CUSTOM_ID_NOKILL}:{guild_id}",
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

        qualifying, _threshold = qualifying_players_for_event_window(
            guild_id, event_start_local, death_time_local, MIN_PRESENCE_PERCENT
        )
        if not qualifying:
            continue

        event_duration = max(1.0, (death_time_local - event_start_local).total_seconds())
        event_mins = _fmt_minutes(event_duration)

        guild = discord_client.get_guild(guild_id)
        if not guild:
            continue

        lines = await format_qualifying_proposal_lines(guild_id, qualifying, guild)
        if not lines:
            continue

        channel = guild.get_channel(int(evt_channel_id))
        if not channel:
            continue

        # Record mob-death (ToD) time on the event for kill / no-kill bookkeeping.
        with get_raid_session(guild_id) as session:
            evt_row = session.query(Event).filter_by(id=evt_id).first()
            if evt_row:
                evt_row.tod_at = death_time_local
                session.commit()

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
# Button handler -- Kill / No Kill / Ignore (legacy Apply)
# ---------------------------------------------------------------------------


def _guild_member_for_perms(inter: disnake.MessageInteraction) -> disnake.Member | None:
    if isinstance(inter.author, disnake.Member):
        return inter.author
    g = inter.guild
    if g is None:
        return None
    return g.get_member(inter.author.id)


@discord_base.DISCORD_CLIENT.listen("on_button_click")
async def on_auto_att_button(inter: disnake.MessageInteraction) -> None:
    custom_id = inter.component.custom_id or ""
    parts = custom_id.split(":", 1)
    if len(parts) != 2:
        return
    prefix, guild_s = parts
    try:
        guild_id = int(guild_s)
    except ValueError:
        return

    is_ignore = prefix == CUSTOM_ID_IGNORE
    is_kill = prefix == CUSTOM_ID_KILL
    is_nokill = prefix == CUSTOM_ID_NOKILL
    is_apply = prefix == CUSTOM_ID_APPLY
    if not is_ignore and not is_kill and not is_nokill and not is_apply:
        return

    if is_ignore:
        await inter.response.edit_message(view=_make_resolved_view(f"Ignored by {inter.author.display_name}"))
        return

    kill_flag: bool | None
    if is_kill:
        kill_flag = True
    elif is_nokill:
        kill_flag = False
    else:
        kill_flag = None

    if is_kill or is_nokill:
        member = _guild_member_for_perms(inter)
        if member is None:
            await inter.response.send_message(
                "```diff\n- Could not resolve member for permission check.```",
                ephemeral=True,
            )
            return
        if is_kill and not perms.can(member, "kill", guild_id):
            await inter.response.send_message(
                "```diff\n- You do not have permission for Kill (requires kill permission).```",
                ephemeral=True,
            )
            return
        if is_nokill and not perms.can(member, "nokill", guild_id):
            await inter.response.send_message(
                "```diff\n- You do not have permission for No Kill (requires nokill permission).```",
                ephemeral=True,
            )
            return

    code_match = re.search(r"```\w*\n(.*?)\n```", inter.message.content or "", re.DOTALL)
    if code_match:
        raw_lines = [ln.strip() for ln in code_match.group(1).splitlines() if ln.strip().startswith("+")]
    else:
        # e.g. reconcile with no EQDKP lines — plain-text body, no fence
        raw_lines = []
    if not raw_lines and kill_flag is None:
        await inter.response.edit_message(
            view=_make_resolved_view(f"Applied by {inter.author.display_name} (nothing to add)")
        )
        return

    cleaned_lines = [re.sub(r"\s*\(\d+m\)\s*(\[[^\]]+\])?\s*$", "", ln) for ln in raw_lines]

    eqdkp_client: EqdkpClient | None = None
    if config.eqdkp_is_configured(guild_id):
        eqdkp_client = EqdkpClient(guild_id)

    out = ["```diff"]
    resolved_suffix = inter.author.display_name
    dkp_for_rename: int | None = None
    rename_channel: bool = False

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
                    eqdkp_member = await eqdkp_client.find_character(char.name)
                except Exception as exc:
                    logger.exception("EQdkp find_character failed for %s", char.name)
                    out.append(f"- {char.name}: EQdkp lookup failed ({exc}). Skipped.")
                    continue
                if eqdkp_member:
                    char.eqdkp_member_id = eqdkp_member.get("id")
                    char.eqdkp_user_id = eqdkp_member.get("user_id")
                    char.eqdkp_main_id = eqdkp_member.get("main_id")
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

        if kill_flag is not None:
            evt.killed = kill_flag
            if evt.tod_at is None:
                evt.tod_at = datetime.now()
            dkp_for_rename = evt.dkp_value
            rename_channel = dkp_for_rename is not None
            if dkp_for_rename is None:
                out.append(
                    "- Must specify a target or dkp value using `/event target` or $dkp before kill/no-kill DKP applies."
                )
            else:
                out.append(
                    f"+ Event marked as {'killed' if kill_flag else 'not killed'}; DKP reward will be {dkp_for_rename}."
                )
            resolved_suffix = f"{resolved_suffix} ({'kill' if kill_flag else 'no kill'})"

        session.commit()

    out.append("```")

    await inter.response.edit_message(view=_make_resolved_view(f"Applied by {resolved_suffix}"))
    await inter.followup.send("\n".join(out))

    if kill_flag is not None and rename_channel and dkp_for_rename is not None:
        ch = inter.channel
        if ch is not None and hasattr(ch, "edit"):
            new_name: str | None = None
            with get_raid_session(guild_id) as session:
                evt_rename = session.query(Event).filter_by(channel_id=str(inter.channel_id)).first()
                if evt_rename:
                    emoji = "\U0001f480" if kill_flag else "\u26d4"
                    new_name = f"{emoji}{evt_rename.channel_name}"
            if new_name:
                try:
                    await ch.edit(name=new_name)
                except disnake.HTTPException:
                    logger.debug("Could not rename channel after auto-attendance kill mark", exc_info=True)
