"""Tests for Discord DM error logging handler."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

from roboToald.discord_dm_log_handler import (
    DiscordDMHandler,
    _TransientGatewayFilter,
    install_discord_dm_handler,
    redact_sensitive_text,
)


def test_redact_sensitive_text_masks_tokens():
    raw = "https://example.test/api.php?function=search&atoken=secret-admin-token&type=api"
    assert "secret-admin-token" not in redact_sensitive_text(raw)
    assert "atoken=[REDACTED]" in redact_sensitive_text(raw)


def test_transient_gateway_filter_skips_reconnect():
    filt = _TransientGatewayFilter()
    record = logging.LogRecord(
        name="disnake.client",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Attempting a reconnect in 1.49s",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is False


def test_transient_gateway_filter_allows_app_errors():
    filt = _TransientGatewayFilter()
    record = logging.LogRecord(
        name="roboToald.db.models.subscription",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Failed to refresh subscription",
        args=(),
        exc_info=None,
    )
    assert filt.filter(record) is True


def test_install_discord_dm_handler_is_idempotent():
    import roboToald.discord_dm_log_handler as dm_module

    client = MagicMock()
    client.is_ready.return_value = True
    client.loop = MagicMock()

    dm_module._INSTALLED_HANDLER = None
    first = install_discord_dm_handler(client, 12345)
    second = install_discord_dm_handler(client, 12345)

    assert first is second
    handlers = [h for h in logging.root.handlers if isinstance(h, DiscordDMHandler)]
    assert len(handlers) == 1

    logging.root.removeHandler(first)
    dm_module._INSTALLED_HANDLER = None
