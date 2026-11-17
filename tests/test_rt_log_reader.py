"""SSE log-stream reader: cursor, !tod, !bp, and the guild-chat archive."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import disnake
import httpx
import pytest

from roboToald import config
from roboToald.db import base
from roboToald.db.models import raid_timers as rt_models
from roboToald.raidtargets import rt_log_reader, rt_service

ET = ZoneInfo("America/New_York")
GUILD = 1
STAMP = "Fri Mar 06 11:13:03 2026"
EPOCH = int(datetime(2026, 3, 6, 11, 13, 3, tzinfo=ET).timestamp())
NOW = EPOCH + 3600


def _guild(body: str, speaker: str = "Toald", officers: bool = False) -> str:
    kind = "tells the guild officers" if officers else "tells the guild"
    return f"[{STAMP}] {speaker} {kind}, '{body}'"


def _event(seq: int, line: str, character: str = "Toald") -> bytes:
    data = json.dumps(
        {"seq": seq, "file": "chat.jsonl", "character": character, "line": line},
        separators=(",", ":"),
    )
    return f"id: {seq}\nevent: line\ndata: {data}\n\n".encode()


class _Chunks:
    def __init__(self, body: bytes):
        self._chunks = [body] if body else []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200):
        self.body = body
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def aiter_bytes(self):
        return _Chunks(self.body)


class FakeClient:
    def __init__(self, bodies: list[bytes]):
        self.bodies = list(bodies)
        self.calls: list[dict] = []

    def stream(self, method, url, headers=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {})})
        body = self.bodies.pop(0) if self.bodies else b""
        return FakeResponse(body)


class FakeChannel:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[str, object]] = []
        self.guild = object()

    async def send(self, content, **kwargs):
        if self.fail:
            raise RuntimeError("discord down")
        self.sent.append((content, kwargs.get("allowed_mentions")))


class FakeDiscord:
    def __init__(self, channels: dict[int, FakeChannel]):
        self.channels = channels

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)


def _patch_stream(monkeypatch, *, source: str = "local", archive: int = 0, tod: int = 0, batphone: int = 0):
    monkeypatch.setattr(config, "get_log_stream_url", lambda _gid: "https://logs.example/v1/streams/myguild")
    monkeypatch.setattr(config, "get_log_stream_key", lambda _gid: "secret")
    monkeypatch.setattr(config, "get_raidtargets_source", lambda _gid: source)
    monkeypatch.setattr(config, "get_guild_chat_channel_id", lambda _gid: archive)
    monkeypatch.setattr(config, "get_tod_channel_id", lambda _gid: tod)

    def raid_setting(_gid, key):
        if key == "batphone_channel_id":
            return batphone
        return 0

    monkeypatch.setattr(config, "get_raid_setting", raid_setting)


async def test_cursor_advances_past_non_command_and_resume_sends_it(raid_timers_session, monkeypatch):
    rt_service.seed_guild_if_empty(GUILD)
    _patch_stream(monkeypatch)
    body = _event(1, _guild("!tod naggy")) + b": ping\n\n" + _event(2, _guild("pulling"))
    first = FakeClient([body])
    await rt_log_reader.follow_once(GUILD, FakeDiscord({}), first, now_utc=NOW)
    assert rt_log_reader.get_log_cursor(GUILD) == 2
    assert rt_service.current_tods(GUILD)["Lord Nagafen"] == EPOCH
    with base.get_session() as session:
        row = session.query(rt_models.RtTod).one()
        assert row.source == "guild_chat"
        assert row.reported_by == "Toald"
    assert first.calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert "Last-Event-ID" not in first.calls[0]["headers"]

    second = FakeClient([b": ping\n\n"])
    await rt_log_reader.follow_once(GUILD, FakeDiscord({}), second, now_utc=NOW)
    assert second.calls[0]["headers"]["Last-Event-ID"] == "2"


async def test_endpoint_guild_does_not_record_tod(raid_timers_session, monkeypatch):
    _patch_stream(monkeypatch, source="endpoint")
    calls = []
    monkeypatch.setattr(rt_log_reader.rt_service, "record_tod", lambda *args, **kwargs: calls.append(args))
    client = FakeClient([_event(1, _guild("!tod naggy"))])
    await rt_log_reader.follow_once(GUILD, FakeDiscord({}), client, now_utc=NOW)
    assert calls == []
    assert rt_log_reader.get_log_cursor(GUILD) == 1


async def test_bp_calls_shared_batphone_once_per_target(raid_timers_session, monkeypatch):
    rt_log_reader._bp_seen.clear()
    _patch_stream(monkeypatch, batphone=4242)
    calls = []

    async def fake_batphone(_guild, content, started_by, _send):
        calls.append((content, started_by))

    monkeypatch.setattr(rt_log_reader, "_call_apply_batphone", fake_batphone)
    channel = FakeChannel()
    discord = FakeDiscord({4242: channel})
    body = _event(1, _guild("!bp naggy")) + _event(2, _guild("!BP Naggy"))
    await rt_log_reader.follow_once(GUILD, discord, FakeClient([body]), now_utc=NOW)
    assert calls == [("@everyone naggy", "Toald")]


async def test_archive_batches_guild_lines_and_skips_officer(raid_timers_session, monkeypatch):
    _patch_stream(monkeypatch, archive=777)
    channel = FakeChannel()
    discord = FakeDiscord({777: channel})
    body = _event(1, _guild("pulling")) + _event(2, _guild("wait")) + _event(3, _guild("secret plan", officers=True))
    await rt_log_reader.follow_once(GUILD, discord, FakeClient([body]), now_utc=NOW)
    assert len(channel.sent) == 1
    text, mentions = channel.sent[0]
    assert text == (f"<t:{EPOCH}:t> **Toald:** pulling\n<t:{EPOCH}:t> **Toald:** wait")
    assert "secret" not in text
    assert isinstance(mentions, disnake.AllowedMentions)
    assert mentions.everyone is False
    assert mentions.users is False
    assert mentions.roles is False
    assert rt_log_reader.get_log_cursor(GUILD) == 3


async def test_failed_archive_leaves_the_earlier_cursor(raid_timers_session, monkeypatch):
    _patch_stream(monkeypatch, archive=777)
    rt_log_reader.save_log_cursor(GUILD, 4)
    channel = FakeChannel(fail=True)
    body = _event(5, _guild("pulling")) + _event(6, _guild("wait"))
    with pytest.raises(rt_log_reader.ArchiveFlushError):
        await rt_log_reader.follow_once(GUILD, FakeDiscord({777: channel}), FakeClient([body]), now_utc=NOW)
    assert rt_log_reader.get_log_cursor(GUILD) == 4


def test_is_transient_disconnect_covers_network_and_stream_errors():
    assert rt_log_reader.is_transient_disconnect(httpx.ConnectError("refused"))
    assert rt_log_reader.is_transient_disconnect(httpx.ReadTimeout("timed out"))
    assert rt_log_reader.is_transient_disconnect(rt_log_reader.LogStreamError("HTTP 502"))
    assert rt_log_reader.is_transient_disconnect(rt_log_reader.ArchiveFlushError("discord down"))
    assert not rt_log_reader.is_transient_disconnect(RuntimeError("bug"))


def test_log_stream_disconnect_warns_then_errors_with_cooldown(caplog):
    exc = httpx.ConnectError("All connection attempts failed")
    with caplog.at_level(logging.WARNING, logger=rt_log_reader.logger.name):
        first = rt_log_reader.log_stream_disconnect(
            GUILD,
            exc,
            consecutive_failures=1,
            backoff=1.0,
            last_error_alert_at=None,
            now=100.0,
        )
        assert first is None
        assert any(r.levelno == logging.WARNING and "disconnected" in r.message for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)

        caplog.clear()
        errored = rt_log_reader.log_stream_disconnect(
            GUILD,
            exc,
            consecutive_failures=rt_log_reader.PERSISTENT_FAILURES_BEFORE_ERROR,
            backoff=16.0,
            last_error_alert_at=None,
            now=100.0,
        )
        assert errored == 100.0
        assert any(r.levelno == logging.ERROR and "still failing" in r.message for r in caplog.records)
        assert all(r.exc_info is None for r in caplog.records if r.levelno >= logging.ERROR)

        caplog.clear()
        cooled = rt_log_reader.log_stream_disconnect(
            GUILD,
            exc,
            consecutive_failures=rt_log_reader.PERSISTENT_FAILURES_BEFORE_ERROR + 1,
            backoff=30.0,
            last_error_alert_at=errored,
            now=errored + 1.0,
        )
        assert cooled == errored
        assert any(r.levelno == logging.WARNING and "still failing" in r.message for r in caplog.records)
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)


class _PassthroughAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


def _patch_run_loop(monkeypatch, *, raise_exc: BaseException, stop_after: int = 2):
    """Drive ``run_log_stream`` without a real HTTP client or DB."""

    async def boom_follow(*_args, **_kwargs):
        raise raise_exc

    sleeps: list[float] = []

    async def fast_sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) >= stop_after:
            raise asyncio.CancelledError()

    monkeypatch.setattr(rt_log_reader.httpx, "AsyncClient", _PassthroughAsyncClient)
    monkeypatch.setattr(rt_log_reader, "follow_once", boom_follow)
    monkeypatch.setattr(rt_log_reader.asyncio, "sleep", fast_sleep)
    return sleeps


async def test_run_log_stream_warns_on_connect_error_without_traceback(monkeypatch, caplog):
    _patch_run_loop(monkeypatch, raise_exc=httpx.ConnectError("All connection attempts failed"), stop_after=2)
    with caplog.at_level(logging.WARNING, logger=rt_log_reader.logger.name):
        with pytest.raises(asyncio.CancelledError):
            await rt_log_reader.run_log_stream(GUILD, FakeDiscord({}))

    stream_records = [r for r in caplog.records if "log stream" in r.getMessage()]
    assert stream_records
    assert all(r.levelno == logging.WARNING for r in stream_records)
    assert all(r.exc_info is None for r in stream_records)
    assert any("disconnected" in r.getMessage() for r in stream_records)


async def test_run_log_stream_exceptions_unexpected_bugs(monkeypatch, caplog):
    _patch_run_loop(monkeypatch, raise_exc=RuntimeError("unexpected bug"), stop_after=1)
    with caplog.at_level(logging.ERROR, logger=rt_log_reader.logger.name):
        with pytest.raises(asyncio.CancelledError):
            await rt_log_reader.run_log_stream(GUILD, FakeDiscord({}))

    unexpected = [r for r in caplog.records if "unexpected error" in r.getMessage()]
    assert len(unexpected) == 1
    assert unexpected[0].exc_info is not None


async def test_run_log_stream_escalates_persistent_connect_failures(monkeypatch, caplog):
    monkeypatch.setattr(rt_log_reader, "PERSISTENT_FAILURES_BEFORE_ERROR", 3)
    monkeypatch.setattr(rt_log_reader, "ERROR_ALERT_COOLDOWN_SECONDS", 0.0)
    _patch_run_loop(monkeypatch, raise_exc=httpx.ConnectError("All connection attempts failed"), stop_after=3)
    with caplog.at_level(logging.WARNING, logger=rt_log_reader.logger.name):
        with pytest.raises(asyncio.CancelledError):
            await rt_log_reader.run_log_stream(GUILD, FakeDiscord({}))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "log stream" in r.getMessage()]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and "still failing" in r.getMessage()]
    assert len(warnings) == 2
    assert len(errors) == 1
    assert errors[0].exc_info is None
