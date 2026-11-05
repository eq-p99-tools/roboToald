"""Tests for timers-channel board formatting and update."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from freezegun import freeze_time

from roboToald.raidtargets import rt_board, rt_data


def _target(name: str, windows: list[tuple[int, int, int]], short: str = "") -> rt_data.RaidTarget:
    import json

    feed = {
        "raidTargets": [
            {
                "name": name,
                "shortName": short or name,
                "aliases": "",
                "era": "Classic",
                "zone": "Z",
                "windows": [{"start": s, "end": e, "extrapolationCount": c} for s, e, c in windows],
            }
        ]
    }
    return json.loads(json.dumps(feed), cls=rt_data.JSONDecoder)[0]


def _freeze_epoch(epoch: int):
    return freeze_time(datetime.fromtimestamp(epoch, tz=timezone.utc))


def test_render_board_buckets_and_tags():
    now = 1_700_000_000
    soon = 48 * 3600
    targets = [
        _target("NowMob", [(now - 100, now + 1000, 0)], short="Now"),
        _target("SoonMob", [(now + 3600, now + 7200, 1)]),
        _target("LaterMob", [(now + soon + 100, now + soon + 200, 0)]),
        _target("PastMob", [(now - 5000, now - 100, 0)]),
    ]
    with _freeze_epoch(now):
        chunks = rt_board.render_board(targets, now, soon, tod_channel_id=99)
    text = "\n".join(chunks)
    assert "**NOW**" in text
    assert "**Now**" in text
    assert "🟩" in text and "⬜" in text
    assert "16m" in text
    assert text.count("\n") < 12
    assert "**SOON**" in text
    assert "[1]" in text
    assert "**LATER**" in text
    assert "PastMob" not in text
    assert " · Z" not in text
    assert "<#99>" in text
    assert all(len(c) <= rt_board.MAX_MESSAGE_CHARS for c in chunks)


def test_progress_bar_and_remaining():
    assert rt_board.progress_bar(0) == "⬜" * rt_board.BAR_WIDTH
    assert rt_board.progress_bar(1) == "🟩" * rt_board.BAR_WIDTH
    assert rt_board.progress_bar(0.5).count("🟩") == rt_board.BAR_WIDTH // 2
    assert rt_board.format_remaining(90 * 60) == "1h 30m"
    assert rt_board.format_remaining(2 * 86400 + 3 * 3600) == "2d 3h 0m"


def test_render_board_chunks_many_targets():
    now = 1_700_000_000
    targets = [_target(f"Mob{i:03d}", [(now + 100 + i, now + 200 + i, 0)]) for i in range(200)]
    with _freeze_epoch(now):
        chunks = rt_board.render_board(targets, now, 48 * 3600)
    assert len(chunks) > 1
    assert all(len(c) <= rt_board.MAX_MESSAGE_CHARS for c in chunks)
    joined = "\n".join(chunks)
    for i in range(200):
        assert f"Mob{i:03d}" in joined


def test_render_board_empty():
    now = 1_700_000_000
    with _freeze_epoch(now):
        chunks = rt_board.render_board([], now, 48 * 3600)
    assert len(chunks) == 1
    assert "No raid targets" in chunks[0]


@pytest.mark.asyncio
async def test_update_board_edit_in_place(raid_timers_session, monkeypatch):
    from roboToald.raidtargets import rt_service

    guild_id = 1
    rt_service.seed_guild_if_empty(guild_id)
    now = int(1_700_000_000)
    rt_service.record_tod(guild_id, "Lord Nagafen", now - 100, "slash", now_utc=now)

    monkeypatch.setattr("roboToald.config.get_raid_timers_channel_id", lambda gid: 555)
    monkeypatch.setattr("roboToald.config.get_raidtargets_soon_threshold", lambda gid: 48 * 3600)
    monkeypatch.setattr("roboToald.config.get_tod_channel_id", lambda gid: 0)
    monkeypatch.setattr("roboToald.config.get_raidtargets_source", lambda gid: "local")

    channel = MagicMock()
    channel.id = 555
    sent = []

    async def _send(content):
        msg = MagicMock()
        msg.id = 1000 + len(sent)
        sent.append(content)
        return msg

    channel.send = AsyncMock(side_effect=_send)
    edited = []

    def _partial(msg_id):
        m = MagicMock()
        m.edit = AsyncMock(side_effect=lambda content: edited.append((msg_id, content)))
        m.delete = AsyncMock()
        return m

    channel.get_partial_message = MagicMock(side_effect=_partial)

    client = MagicMock()
    client.get_channel = MagicMock(return_value=channel)

    rt_data.RaidTargets._cache.clear()
    with _freeze_epoch(now):
        await rt_board.update_board(guild_id, client)
    assert sent
    assert rt_service.get_board_message_ids(guild_id)[1]

    with _freeze_epoch(now + 60):
        await rt_board.update_board(guild_id, client)
    assert edited
