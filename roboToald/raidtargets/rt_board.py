"""Discord timers-channel board: format + edit-in-place updater."""

from __future__ import annotations

import logging
import time

import disnake

from roboToald import config
from roboToald.raidtargets import rt_data

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1900
BAR_WIDTH = 16
_FORBIDDEN_WARN_AT: dict[int, float] = {}


def progress_bar(fraction: float, width: int = BAR_WIDTH) -> str:
    """Filled portion is time already elapsed; empty portion is time left."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def format_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _label(target: rt_data.RaidTarget, window: rt_data.RaidWindow) -> str:
    name = target.short_name or target.name
    tag = f" [{window.extrapolation_count}]" if window.extrapolation_count else ""
    zone = f" · {target.zone}" if target.zone else ""
    return f"**{name}**{tag}{zone}"


def _now_block(target: rt_data.RaidTarget, window: rt_data.RaidWindow, now_utc: int) -> str:
    span = window.end - window.start
    elapsed = (now_utc - window.start) / span if span > 0 else 1.0
    left = window.end - now_utc
    bar = progress_bar(elapsed)
    return "\n".join(
        [
            _label(target, window),
            f"`{bar}` **{format_remaining(left)}** left · closes <t:{window.end}:R> (<t:{window.end}:t>)",
            f"<t:{window.start}:f> → <t:{window.end}:f>",
        ]
    )


def _upcoming_block(target: rt_data.RaidTarget, window: rt_data.RaidWindow) -> str:
    return "\n".join(
        [
            _label(target, window),
            f"opens <t:{window.start}:R> · <t:{window.start}:f> → <t:{window.end}:t>",
        ]
    )


def render_board(
    targets: list[rt_data.RaidTarget],
    now_utc: int,
    soon_threshold: int,
    tod_channel_id: int = 0,
) -> list[str]:
    now_bucket: list[tuple] = []
    soon_bucket: list[tuple] = []
    later_bucket: list[tuple] = []

    for target in targets:
        window = target.get_active_window(now_utc, soon_threshold=soon_threshold)
        if window is None:
            continue
        status = window.get_status(now_utc, soon_threshold=soon_threshold)
        if status == rt_data.RaidWindowStatus.NOW:
            now_bucket.append((window.end, target, window))
        elif status == rt_data.RaidWindowStatus.SOON:
            soon_bucket.append((window.start, target, window))
        elif status == rt_data.RaidWindowStatus.LATER:
            later_bucket.append((window.start, target, window))

    now_bucket.sort(key=lambda x: x[0])
    soon_bucket.sort(key=lambda x: x[0])
    later_bucket.sort(key=lambda x: x[0])

    blocks: list[str] = []
    if now_bucket:
        blocks.append("__**In window NOW**__")
        blocks.extend(_now_block(target, window, now_utc) for _end, target, window in now_bucket)
    if soon_bucket:
        hours = max(1, soon_threshold // 3600)
        blocks.append(f"__**SOON**__ · under {hours}h")
        blocks.extend(_upcoming_block(target, window) for _start, target, window in soon_bucket)
    if later_bucket:
        blocks.append("__**LATER**__")
        blocks.extend(_upcoming_block(target, window) for _start, target, window in later_bucket)

    footer = f"-# Updated <t:{now_utc}:R> · [N] = missed respawns · █ elapsed, ░ left"
    if tod_channel_id:
        footer += f" · ToDs: <#{tod_channel_id}>"
    if not blocks:
        return ["No raid targets with known windows.\n" + footer]

    blocks.append(footer)
    return _chunk_blocks(blocks)


def _chunk_blocks(blocks: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for block in blocks:
        add = len(block) + (1 if current else 0)
        if current and length + add > MAX_MESSAGE_CHARS:
            chunks.append("\n".join(current))
            current = [block]
            length = len(block)
        else:
            current.append(block)
            length += add
    if current:
        chunks.append("\n".join(current))
    return chunks or ["No raid targets with known windows."]


async def update_board(guild_id: int, client: disnake.Client) -> None:
    channel_id = config.get_raid_timers_channel_id(guild_id)
    if not channel_id:
        return

    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            logger.warning("Raid timers channel %s unavailable for guild %s", channel_id, guild_id)
            return

    now_utc = int(time.time())
    soon = config.get_raidtargets_soon_threshold(guild_id)
    targets = await rt_data.RaidTargets.get_targets(guild_id)
    chunks = render_board(targets, now_utc, soon, tod_channel_id=config.get_tod_channel_id(guild_id))

    from roboToald.raidtargets import rt_service
    import asyncio

    stored_channel, stored_ids = await asyncio.to_thread(rt_service.get_board_message_ids, guild_id)
    if stored_channel != channel_id:
        stored_ids = []

    new_ids: list[int] = []
    try:
        for i, content in enumerate(chunks):
            if i < len(stored_ids):
                msg_id = stored_ids[i]
                try:
                    msg = channel.get_partial_message(msg_id)
                    await msg.edit(content=content)
                    new_ids.append(msg_id)
                    continue
                except disnake.NotFound:
                    pass
                except disnake.HTTPException:
                    logger.exception("Failed to edit board message %s guild=%s", msg_id, guild_id)
            sent = await channel.send(content=content)
            new_ids.append(sent.id)

        for extra_id in stored_ids[len(chunks) :]:
            try:
                await channel.get_partial_message(extra_id).delete()
            except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                pass

        await asyncio.to_thread(rt_service.set_board_message_ids, guild_id, channel_id, new_ids)
    except disnake.Forbidden:
        last = _FORBIDDEN_WARN_AT.get(guild_id, 0)
        if now_utc - last > 3600:
            logger.warning(
                "Missing permission to update raid timers channel %s for guild %s",
                channel_id,
                guild_id,
            )
            _FORBIDDEN_WARN_AT[guild_id] = now_utc
