"""Shared kill / no-kill marking for raid events ($kill, $nokill, auto-attendance buttons)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import disnake

from roboToald.db.raid_models.raid import Event

logger = logging.getLogger(__name__)

KILL_EMOJI = "\U0001f480"
NOKILL_EMOJI = "\u26d4"


@dataclass(frozen=True)
class KillApplyResult:
    """Result of attempting to set ``Event.killed`` to a desired boolean."""

    status_changed: bool
    dkp_value: int | None


def channel_name_prefix_for_kill(killed: bool) -> str:
    """Discord channel name prefix for a resolved kill (skull) or no-kill (stop sign)."""
    return KILL_EMOJI if killed else NOKILL_EMOJI


def event_channel_name_with_kill_prefix(evt: Event, killed: bool) -> str:
    """Full channel name: emoji prefix plus event ``channel_name`` string."""
    return f"{channel_name_prefix_for_kill(killed)}{evt.channel_name}"


def apply_kill_state_to_event(
    evt: Event,
    want_killed: bool,
    *,
    set_tod_if_missing: bool = False,
) -> KillApplyResult:
    """Set ``evt.killed`` to ``want_killed`` if it would change state.

    When ``set_tod_if_missing`` is True (auto-attendance), sets ``evt.tod_at`` to now if still
    unset after a successful kill-state change. ``$kill`` / ``$nokill`` do not set ToD.

    Does not commit the session. Returns ``dkp_value`` after the would-be or applied state
    (used to gate channel rename when DKP cannot be resolved).
    """
    if want_killed and evt.killed is True:
        return KillApplyResult(status_changed=False, dkp_value=evt.dkp_value)
    if not want_killed and evt.killed is False:
        return KillApplyResult(status_changed=False, dkp_value=evt.dkp_value)

    evt.killed = want_killed
    if set_tod_if_missing and evt.tod_at is None:
        evt.tod_at = datetime.now()
    return KillApplyResult(status_changed=True, dkp_value=evt.dkp_value)


async def rename_event_channel_for_kill_name(channel: disnake.abc.GuildChannel, new_name: str) -> None:
    """Rename channel after kill/no-kill; failures are logged at debug only (matches legacy behavior)."""
    try:
        await channel.edit(name=new_name)
    except disnake.HTTPException:
        logger.debug("Could not rename channel for kill/nokill mark", exc_info=True)


async def rename_event_channel_for_kill_state(
    channel: disnake.abc.GuildChannel,
    evt: Event,
    killed: bool,
) -> None:
    """Rename channel using the standard kill/no-kill emoji prefix and event ``channel_name``."""
    await rename_event_channel_for_kill_name(channel, event_channel_name_with_kill_prefix(evt, killed))
