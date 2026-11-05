"""Tests for GET /raidtargets/{guild_id}/targets-v2.json."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from roboToald.api import server
from roboToald.raidtargets import rt_data, rt_service


@pytest.fixture()
def api_client(raid_timers_session, monkeypatch):
    guild_id = 1
    rt_service.seed_guild_if_empty(guild_id)
    monkeypatch.setattr(server.config, "get_raidtargets_feed_key", lambda gid: "secret-key" if gid == 1 else None)
    monkeypatch.setattr(server.config, "get_raidtargets_source", lambda gid: "local" if gid == 1 else "endpoint")
    return TestClient(server.app), guild_id


def test_feed_404_without_key(api_client):
    client, guild_id = api_client
    resp = client.get(f"/raidtargets/{guild_id}/targets-v2.json")
    assert resp.status_code == 404


def test_feed_404_wrong_key(api_client):
    client, guild_id = api_client
    resp = client.get(
        f"/raidtargets/{guild_id}/targets-v2.json",
        headers={"AuthorizationKey": "nope"},
    )
    assert resp.status_code == 404


def test_feed_404_when_endpoint_source(api_client, monkeypatch):
    client, guild_id = api_client
    monkeypatch.setattr(server.config, "get_raidtargets_source", lambda gid: "endpoint")
    resp = client.get(
        f"/raidtargets/{guild_id}/targets-v2.json",
        headers={"AuthorizationKey": "secret-key"},
    )
    assert resp.status_code == 404


def test_feed_200_parses(api_client):
    client, guild_id = api_client
    resp = client.get(
        f"/raidtargets/{guild_id}/targets-v2.json",
        headers={"AuthorizationKey": "secret-key"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "raidTargets" in body
    decoded = json.loads(json.dumps(body), cls=rt_data.JSONDecoder)
    assert isinstance(decoded, list)
    assert any(t.name == "Lord Nagafen" for t in decoded)
