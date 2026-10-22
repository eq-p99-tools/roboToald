"""Discord timers-channel board: format + edit-in-place updater."""

from __future__ import annotations

import logging
import time

import disnake

from roboToald import config
from roboToald.raidtargets import rt_data

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1900
_FORBIDDEN_WARN_AT: dict[int, float] = {}


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
        display = target.short_name or target.name
        tag = f"[{window.extrapolation_count}] " if window.extrapolation_count > 0 else ""
        if status == rt_data.RaidWindowStatus.NOW:
            now_bucket.append((window.end, display, tag, window))
        elif status == rt_data.RaidWindowStatus.SOON:
            soon_bucket.append((window.start, display, tag, window))
        elif status == rt_data.RaidWindowStatus.LATER:
            later_bucket.append((window.start, display, tag, window))

    now_bucket.sort(key=lambda x: x[0])
    soon_bucket.sort(key=lambda x: x[0])
    later_bucket.sort(key=lambda x: x[0])

    lines: list[str] = []
    if now_bucket:
        lines.append("__**In window NOW**__")
        for _end, name, tag, window in now_bucket:
            prefix = f"`{tag}`" if tag else ""
            lines.append(f"{prefix}**{name}** — closes <t:{window.end}:R> (<t:{window.end}:t>)")
    if soon_bucket:
        hours = max(1, soon_threshold // 3600)
        lines.append(f"__**SOON (under {hours}h)**__")
        for _start, name, tag, window in soon_bucket:
            tag_part = f" {tag}" if tag else " "
            lines.append(f"**{name}**{tag_part}— opens <t:{window.start}:R> (<t:{window.start}:f>)")
    if later_bucket:
        lines.append("__**LATER**__")
        for _start, name, tag, window in later_bucket:
            tag_part = f" {tag}" if tag else " "
            lines.append(f"**{name}**{tag_part}— opens <t:{window.start}:R> (<t:{window.start}:f>)")

    footer = f"-# Updated <t:{now_utc}:R> · [N] = N missed respawns extrapolated"
    if tod_channel_id:
        footer += f" · ToDs: <#{tod_channel_id}>"
    if not now_bucket and not soon_bucket and not later_bucket:
        return ["No raid targets with known windows.\n" + footer]

    lines.append(footer)
    return _chunk_lines(lines)


def _chunk_lines(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        add = len(line) + (1 if current else 0)
        if current and length + add > MAX_MESSAGE_CHARS:
            chunks.append("\n".join(current))
            current = [line]
            length = len(line)
        else:
            current.append(line)
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
