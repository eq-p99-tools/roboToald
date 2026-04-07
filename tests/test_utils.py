"""Tests for ``roboToald.utils`` — URL validation, routing, message splitting."""

from __future__ import annotations

from roboToald import utils


def test_validate_url_accepts_us_and_eu():
    assert utils.validate_url("https://api.squadcast.com/v2/incidents/api/abc123")
    assert utils.validate_url("https://api.eu.squadcast.com/v2/incidents/api/xyz789")


def test_validate_url_rejects_random():
    assert not utils.validate_url("https://example.com/hook")
    assert not utils.validate_url("")


def test_send_function_maps_url():
    us = "https://api.squadcast.com/v2/incidents/api/abc123"
    fn = utils.send_function(us)
    assert fn is not None
    assert fn.__name__ == "send_alert"


def test_split_message_short_single_chunk():
    msg = "hello\nworld"
    assert utils.split_message(msg) == ["hello\nworld\n"]


def test_split_message_respects_2000_char_lines():
    long_line = "x" * 1990
    msg = "\n".join([long_line, long_line])
    chunks = utils.split_message(msg)
    assert all(len(c) <= 2000 for c in chunks)
    assert len(chunks) >= 2


def test_send_alert_calls_squadcast_with_truncated_title(monkeypatch):
    from unittest.mock import MagicMock

    from roboToald import utils

    calls = []

    def fake_send_function(url):
        def inner(title, msg, webhook=None):
            calls.append((title, msg, webhook))

        return inner

    monkeypatch.setattr(utils, "send_function", fake_send_function)
    alert = MagicMock()
    alert.id = 1
    alert.guild_id = 10
    alert.user_id = 20
    alert.alert_url = "https://api.squadcast.com/v2/incidents/api/abc123def456"
    alert.increment_counter = MagicMock()
    utils.send_alert(alert, "hello world")
    assert len(calls) == 1
    assert calls[0][0] == "hello world"[:12]
    assert calls[0][1] == "hello world"
    alert.increment_counter.assert_called_once()


def test_split_message_two_thousand_char_lines_flush_before_second_line():
    """When the first line plus ``\\n`` plus the next line would exceed 2000, the first line flushes."""
    a = "a" * 1000
    b = "b" * 1000
    msg = f"{a}\n{b}"
    chunks = utils.split_message(msg)
    assert len(chunks) == 2
    assert len(chunks[0]) <= 2000
    assert len(chunks[1]) <= 2000
