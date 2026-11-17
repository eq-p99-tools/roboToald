"""log_stream_url must be per-guild and not inherited from [DEFAULT]."""

from __future__ import annotations

import configparser
import logging

from roboToald import config
from roboToald.raidtargets import rt_log_reader


def test_section_option_ignores_default_inheritance():
    parser = configparser.ConfigParser()
    parser.read_string(
        """
[DEFAULT]
log_stream_url = https://logs.example/v1/streams/from-default
log_stream_key = default-secret

[guild.268632657724702721]
enable_raidtarget = true
"""
    )
    section = "guild.268632657724702721"
    assert parser.get(section, "log_stream_url", fallback=None) == (
        "https://logs.example/v1/streams/from-default"
    )
    assert config.section_option(parser, section, "log_stream_url", fallback=None) is None
    assert config.section_option(parser, section, "log_stream_key", fallback=None) is None


def test_section_option_reads_explicit_guild_value():
    parser = configparser.ConfigParser()
    parser.read_string(
        """
[DEFAULT]
log_stream_url = https://logs.example/v1/streams/from-default

[guild.1]
log_stream_url = https://logs.example/v1/streams/guild-one
log_stream_key = guild-secret
"""
    )
    assert (
        config.section_option(parser, "guild.1", "log_stream_url", fallback=None)
        == "https://logs.example/v1/streams/guild-one"
    )
    assert config.section_option(parser, "guild.1", "log_stream_key", fallback=None) == "guild-secret"


def test_get_log_stream_url_treats_blank_as_unset(monkeypatch):
    monkeypatch.setitem(config.GUILD_SETTINGS, 99, {"log_stream_url": "  ", "log_stream_key": "x"})
    assert config.get_log_stream_url(99) is None
    monkeypatch.setitem(config.GUILD_SETTINGS, 99, {"log_stream_url": "", "log_stream_key": "x"})
    assert config.get_log_stream_url(99) is None
    monkeypatch.setitem(config.GUILD_SETTINGS, 99, {"log_stream_url": None, "log_stream_key": "x"})
    assert config.get_log_stream_url(99) is None


def test_start_log_stream_tasks_skips_guilds_without_url(monkeypatch, caplog):
    urls = {
        1: "https://logs.example/v1/streams/one",
        2: "",
        3: None,
    }
    monkeypatch.setattr(config, "GUILD_SETTINGS", {gid: {} for gid in urls})
    monkeypatch.setattr(
        config,
        "get_log_stream_url",
        lambda guild_id: (urls.get(guild_id) or None) and str(urls[guild_id]).strip() or None,
    )

    started: list[int] = []

    async def fake_run(guild_id, discord):
        started.append(guild_id)

    def fake_create_task(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass
        finally:
            coro.close()
        return object()

    monkeypatch.setattr(rt_log_reader, "run_log_stream", fake_run)
    monkeypatch.setattr(rt_log_reader.asyncio, "create_task", fake_create_task)

    with caplog.at_level(logging.INFO, logger=rt_log_reader.logger.name):
        tasks = rt_log_reader.start_log_stream_tasks(discord=object())

    assert started == [1]
    assert len(tasks) == 1
    assert any("url=https://logs.example/v1/streams/one" in r.getMessage() for r in caplog.records)
