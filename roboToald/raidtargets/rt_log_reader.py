"""Follow a guild log-stream SSE URL and apply !tod, !bp, and the chat archive.

Empty ``log_stream_url`` means this module is never started for that guild.
The bearer token is sent as ``Authorization`` and is not logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

import disnake
import httpx

from roboToald import config
from roboToald.db import base
from roboToald.db.models import raid_timers as rt_models
from roboToald.raidtargets import rt_data, rt_service
from roboToald.raidtargets.rt_log_parse import GuildLine, parse_guild_line

logger = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 45.0
CONNECT_TIMEOUT_SECONDS = 10.0
BACKOFF_MAX_SECONDS = 30.0
ARCHIVE_MAX_CHARS = 1900
ARCHIVE_MAX_AGE_SECONDS = 2.0
BP_DEBOUNCE_SECONDS = 30.0

_bp_seen: dict[tuple[int, str], float] = {}


class LogStreamError(Exception):
    """The SSE response was not a stream we can follow."""


class ArchiveFlushError(LogStreamError):
    """The archive channel send failed. The cursor stays on the last flushed seq."""


@dataclass
class SseEvent:
    event_id: str | None
    name: str
    data: str


class SseParser:
    """Split a byte stream into SSE events. Comments are discarded."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> list[SseEvent]:
        self._buf += text.replace("\r\n", "\n").replace("\r", "\n")
        events: list[SseEvent] = []
        while "\n\n" in self._buf:
            block, self._buf = self._buf.split("\n\n", 1)
            event = _parse_sse_block(block)
            if event is not None:
                events.append(event)
        return events


def _parse_sse_block(block: str) -> SseEvent | None:
    event_id = None
    name = "message"
    data_lines: list[str] = []
    saw_field = False
    for raw in block.split("\n"):
        if not raw or raw.startswith(":"):
            continue
        saw_field = True
        field, _, value = raw.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "id":
            event_id = value
        elif field == "event":
            name = value or "message"
        elif field == "data":
            data_lines.append(value)
    if not saw_field:
        return None
    return SseEvent(event_id=event_id, name=name, data="\n".join(data_lines))


def get_log_cursor(guild_id: int) -> int | None:
    with base.get_session() as session:
        row = session.get(rt_models.RtLogCursor, guild_id)
        if row is None:
            return None
        return int(row.seq)


def save_log_cursor(guild_id: int, seq: int) -> None:
    now = int(time.time())
    with base.get_session() as session:
        row = session.get(rt_models.RtLogCursor, guild_id)
        if row is None:
            session.add(rt_models.RtLogCursor(guild_id=guild_id, seq=int(seq), updated_at=now))
        elif int(seq) < int(row.seq):
            return
        else:
            row.seq = int(seq)
            row.updated_at = now
            session.add(row)
        session.commit()


def archive_channel_for(guild_id: int) -> int:
    """Guild-chat archive channel, or 0 when unset or pointed at a live command channel."""
    channel_id = config.get_guild_chat_channel_id(guild_id)
    if not channel_id:
        return 0
    tod_id = config.get_tod_channel_id(guild_id) or 0
    if channel_id == tod_id:
        logger.error(
            "guild_chat_channel_id %s matches tod_channel_id; archive off guild=%s",
            channel_id,
            guild_id,
        )
        return 0
    batphone_id = config.get_raid_setting(guild_id, "batphone_channel_id") or 0
    if channel_id == batphone_id:
        logger.error(
            "guild_chat_channel_id %s matches batphone_channel_id; archive off guild=%s",
            channel_id,
            guild_id,
        )
        return 0
    return channel_id


class ArchiveBuffer:
    def __init__(self, guild_id: int, channel_id: int) -> None:
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.parts: list[str] = []
        self.seqs: list[int] = []
        self.oldest: float | None = None

    def seconds_until_due(self) -> float | None:
        if self.oldest is None:
            return None
        remaining = ARCHIVE_MAX_AGE_SECONDS - (time.monotonic() - self.oldest)
        return max(0.0, remaining)

    def _length_with(self, text: str) -> int:
        extra = 1 if self.parts else 0
        return sum(len(part) for part in self.parts) + (len(self.parts) - 1 if self.parts else 0) + extra + len(text)

    async def add(self, seq: int, text: str, discord) -> None:
        if self.parts and self._length_with(text) > ARCHIVE_MAX_CHARS:
            await self.flush(discord)
        if self.oldest is None:
            self.oldest = time.monotonic()
        self.parts.append(text)
        self.seqs.append(seq)

    async def flush(self, discord) -> None:
        if not self.parts:
            return
        text = "\n".join(self.parts)
        seq = max(self.seqs)
        channel = discord.get_channel(self.channel_id) if discord is not None else None
        if channel is None:
            raise ArchiveFlushError(f"archive channel {self.channel_id} not found")
        try:
            await channel.send(text, allowed_mentions=disnake.AllowedMentions.none())
        except Exception as exc:
            raise ArchiveFlushError(str(exc)) from exc
        save_log_cursor(self.guild_id, seq)
        self.parts = []
        self.seqs = []
        self.oldest = None


def format_archive_line(parsed: GuildLine) -> str:
    if parsed.stamp_epoch is None:
        return f"**{parsed.speaker}:** {parsed.body}"
    return f"<t:{parsed.stamp_epoch}:t> **{parsed.speaker}:** {parsed.body}"


async def apply_commands(guild_id: int, parsed: GuildLine, discord) -> None:
    if parsed.command is None:
        return
    if parsed.command.kind == "tod":
        await _apply_tod(guild_id, parsed, discord)
    elif parsed.command.kind == "bp":
        await _apply_bp(guild_id, parsed, discord)


async def _apply_tod(guild_id: int, parsed: GuildLine, discord) -> None:
    if config.get_raidtargets_source(guild_id) != "local":
        return
    if parsed.stamp_epoch is None or parsed.command is None:
        logger.info(
            "guild !tod ignored guild=%s target=%s error=%s",
            guild_id,
            parsed.command.target if parsed.command else "",
            parsed.stamp_error,
        )
        return
    result = await asyncio.to_thread(
        rt_service.record_tod,
        guild_id,
        parsed.command.target,
        parsed.stamp_epoch,
        "guild_chat",
        parsed.speaker,
    )
    if result.status in ("recorded", "superseded_existing"):
        rt_data.RaidTargets._cache.pop(guild_id, None)
        tod_channel_id = config.get_tod_channel_id(guild_id)
        if not tod_channel_id or discord is None:
            return
        channel = discord.get_channel(tod_channel_id)
        if channel is None:
            logger.info("guild !tod has no tod channel object guild=%s", guild_id)
            return
        name = result.target_name or parsed.command.target
        await channel.send(
            f"Guild ToD: **{name}** at <t:{result.tod_utc}:F> ({parsed.speaker})",
            allowed_mentions=disnake.AllowedMentions.none(),
        )
    elif result.status == "unknown_target":
        logger.info("guild !tod unknown target guild=%s query=%s", guild_id, parsed.command.target)


async def _apply_bp(guild_id: int, parsed: GuildLine, discord) -> None:
    if parsed.command is None:
        return
    key = (guild_id, parsed.command.target.casefold())
    now = time.monotonic()
    last = _bp_seen.get(key)
    if last is not None and now - last < BP_DEBOUNCE_SECONDS:
        return
    _bp_seen[key] = now
    channel_id = config.get_raid_setting(guild_id, "batphone_channel_id") or 0
    if not channel_id:
        logger.info("!bp skipped, batphone_channel_id unset guild=%s", guild_id)
        return
    if discord is None:
        return
    channel = discord.get_channel(channel_id)
    if channel is None:
        logger.info("!bp skipped, batphone channel %s missing guild=%s", channel_id, guild_id)
        return
    await _call_apply_batphone(channel.guild, f"@everyone {parsed.command.target}", parsed.speaker, channel.send)


async def _call_apply_batphone(guild, content: str, started_by: str, send) -> None:
    from roboToald.discord_client.commands.cmd_event import apply_batphone

    await apply_batphone(guild, content, started_by, send)


async def _commit_if_clear(guild_id: int, seq: int, archive: ArchiveBuffer, discord) -> None:
    """Advance past a line that is not sitting in the archive buffer."""
    await archive.flush(discord)
    current = get_log_cursor(guild_id)
    if current is None or seq > current:
        save_log_cursor(guild_id, seq)


async def _handle_sse_event(
    guild_id: int,
    event: SseEvent,
    discord,
    archive: ArchiveBuffer,
    now_utc: int | None = None,
) -> None:
    payload = None
    if event.data:
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError:
            logger.warning("log stream bad JSON guild=%s id=%s", guild_id, event.event_id)
            seq = _as_seq(event.event_id)
            if seq is not None:
                await _commit_if_clear(guild_id, seq, archive, discord)
            return
    if not isinstance(payload, dict):
        payload = {}

    seq = _as_seq(event.event_id)
    if seq is None:
        seq = _as_seq(payload.get("seq"))
    name = event.name or "message"
    if name == "reset":
        logger.warning(
            "log stream reset guild=%s seq=%s reason=%s",
            guild_id,
            seq,
            payload.get("reason"),
        )
        if seq is not None:
            await _commit_if_clear(guild_id, seq, archive, discord)
        return
    if name != "line":
        if seq is not None:
            await _commit_if_clear(guild_id, seq, archive, discord)
        return
    if seq is None:
        logger.warning("log stream line missing seq guild=%s", guild_id)
        return

    line = payload.get("line")
    character = payload.get("character") or ""
    parsed = parse_guild_line(line, str(character), now_utc=now_utc) if isinstance(line, str) else None
    if parsed is not None:
        try:
            await apply_commands(guild_id, parsed, discord)
        except Exception:
            logger.exception("log stream command failed guild=%s seq=%s", guild_id, seq)
        if parsed.channel == "guild" and archive.channel_id:
            await archive.add(seq, format_archive_line(parsed), discord)
            return
    await _commit_if_clear(guild_id, seq, archive, discord)


def _as_seq(raw) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


async def follow_once(guild_id: int, discord, client, now_utc: int | None = None) -> bool:
    """Read one SSE response until it ends. Returns True when any event arrived.

    The read timeout is 45s on the HTTP client, so any received bytes start a
    new 45s window. Archive lines flush when the next line would pass 1900
    characters, 2s after the oldest buffered line, or when this response ends.
    """
    url = config.get_log_stream_url(guild_id)
    if not url:
        return False
    headers = {
        "Accept": "text/event-stream",
        "Authorization": f"Bearer {config.get_log_stream_key(guild_id)}",
    }
    cursor = get_log_cursor(guild_id)
    if cursor is not None:
        headers["Last-Event-ID"] = str(cursor)

    saw_event = False
    archive = ArchiveBuffer(guild_id, archive_channel_for(guild_id))
    parser = SseParser()
    async with client.stream("GET", url, headers=headers) as response:
        status = getattr(response, "status_code", 200)
        if status != 200:
            logger.warning("log stream HTTP %s guild=%s", status, guild_id)
            raise LogStreamError(f"HTTP {status}")
        stream = response.aiter_bytes()
        pending: asyncio.Task | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(_next_chunk(stream))
                delay = archive.seconds_until_due()
                done, _pending = await asyncio.wait({pending}, timeout=delay)
                if not done:
                    await archive.flush(discord)
                    continue
                pending = None
                try:
                    chunk = done.pop().result()
                except StopAsyncIteration:
                    break
                if isinstance(chunk, bytes):
                    text = chunk.decode("utf-8", errors="replace")
                else:
                    text = str(chunk)
                for event in parser.feed(text):
                    saw_event = True
                    await _handle_sse_event(guild_id, event, discord, archive, now_utc=now_utc)
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                try:
                    await pending
                except (asyncio.CancelledError, Exception):
                    pass
        await archive.flush(discord)
    return saw_event


async def _next_chunk(stream):
    return await anext(stream)


async def run_log_stream(guild_id: int, discord) -> None:
    """Reconnect forever. Backoff is 1, 2, 4, … 30s and resets after any SSE event."""
    backoff = 1.0
    timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    while True:
        saw_event = False
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                saw_event = await follow_once(guild_id, discord, client)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("log stream disconnected guild=%s", guild_id)
        if saw_event:
            backoff = 1.0
        await asyncio.sleep(backoff)
        if not saw_event:
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)


def start_log_stream_tasks(discord) -> list[asyncio.Task]:
    tasks = []
    for guild_id in config.GUILD_SETTINGS:
        if not config.get_log_stream_url(guild_id):
            continue
        tasks.append(asyncio.create_task(run_log_stream(guild_id, discord)))
        logger.info("Started log stream reader for guild %s", guild_id)
    return tasks
