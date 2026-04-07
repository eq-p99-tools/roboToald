"""Tests for ``roboToald.eqdkp.client`` helpers and ``find_character``."""

from __future__ import annotations

import pytest

from roboToald import config
from roboToald.eqdkp.client import EqdkpApiError, EqdkpClient, _raise_if_eqdkp_error, _values_with_prefix


def test_raise_if_eqdkp_error():
    with pytest.raises(EqdkpApiError, match="unknown EQdkp error"):
        _raise_if_eqdkp_error({"status": 0})
    with pytest.raises(EqdkpApiError, match="oops"):
        _raise_if_eqdkp_error({"status": 0, "error": "oops"})
    _raise_if_eqdkp_error({"status": 1})


def test_values_with_prefix_filters_dict_values():
    data = {
        "member:1": {"id": 1},
        "other": "skip",
        "member:2": {"id": 2},
        "plain": {"x": 1},
    }
    got = _values_with_prefix(data, "member:")
    assert len(got) == 2
    assert {"id": 1} in got


@pytest.mark.asyncio
async def test_find_character_single_member(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_get(function, **extra):
        assert function == "search"
        return {"direct": {"member:0": {"user_id": "5", "name": "Bob"}}}

    monkeypatch.setattr(client, "_get", fake_get)
    row = await client.find_character("Bob")
    assert row is not None
    assert row["name"] == "Bob"


@pytest.mark.asyncio
async def test_find_character_prefers_nonzero_user_id_when_ambiguous(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_get(function, **extra):
        return {
            "direct": {
                "member:0": {"user_id": "0", "name": "Dup"},
                "member:1": {"user_id": "99", "name": "Dup"},
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    row = await client.find_character("Dup")
    assert row is not None
    assert row["user_id"] == "99"


@pytest.mark.asyncio
async def test_find_character_returns_none_when_multiple_valid(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_get(function, **extra):
        return {
            "direct": {
                "member:0": {"user_id": "1", "name": "X"},
                "member:1": {"user_id": "2", "name": "X"},
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.find_character("X") is None


@pytest.mark.asyncio
async def test_find_character_no_members(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_get(*a, **k):
        return {"direct": {}}

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.find_character("Nobody") is None


@pytest.mark.asyncio
async def test_find_points_returns_mdkp(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_get(function, **extra):
        assert function == "points"
        return {
            "players": {
                "player:0": {
                    "points": {
                        "multidkp_points:0": {"points_current_with_twink": "42.5"},
                    }
                }
            }
        }

    monkeypatch.setattr(client, "_get", fake_get)
    assert await client.find_points(1) == "42.5"


@pytest.mark.asyncio
async def test_create_event_returns_id(monkeypatch):
    monkeypatch.setitem(
        config.EQDKP_SETTINGS,
        1,
        {"url": "http://example.test", "host": "example.test", "api_key": "token"},
    )
    client = EqdkpClient(1)

    async def fake_post(function, body):
        assert function == "add_event"
        return {"event_id": 999}

    monkeypatch.setattr(client, "_post", fake_post)
    assert await client.create_event("Raid Night", 10) == 999
