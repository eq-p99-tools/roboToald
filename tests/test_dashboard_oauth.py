"""Tests for SSO dashboard Discord OAuth login."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from starlette.testclient import TestClient

from roboToald import config
from roboToald.api.dashboard import _build_discord_authorize_url
from roboToald.api.server import app


@pytest.fixture(autouse=True)
def _dashboard_oauth_config(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(config, "DISCORD_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(config, "DASHBOARD_BASE_URL", "https://example.test")


def test_build_discord_authorize_url_uses_prompt_none_by_default():
    url = _build_discord_authorize_url("state123")
    params = parse_qs(urlparse(url).query)
    assert params["prompt"] == ["none"]
    assert params["state"] == ["state123"]
    assert params["scope"] == ["identify"]


def test_build_discord_authorize_url_omits_prompt_when_force_consent():
    url = _build_discord_authorize_url("state123", force_consent=True)
    params = parse_qs(urlparse(url).query)
    assert "prompt" not in params


def test_oauth_callback_retries_with_consent_when_required():
    with TestClient(app) as client:
        response = client.get(
            "/admin/callback",
            params={"error": "consent_required", "state": "ignored"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login?consent=1"
