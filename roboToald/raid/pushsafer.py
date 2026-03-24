"""Pushsafer API client for mobile push notifications."""

from __future__ import annotations

import logging

import requests

from roboToald import config

logger = logging.getLogger(__name__)

PUSHSAFER_API_URL = "https://www.pushsafer.com/api"


def send_batphone(title: str, message: str, guild_id: int, opts: dict | None = None) -> None:
    """Send a push notification via Pushsafer.

    Port of the Ruby send_batphone() helper from funcs.rb.
    """
    private_key = config.get_pushsafer_setting(guild_id, "private_key")
    if not private_key:
        logger.warning("Pushsafer private key not configured for guild %s, skipping push", guild_id)
        return

    payload = {
        "t": title,
        "m": message,
        "k": private_key,
    }
    if opts:
        payload.update(opts)

    try:
        resp = requests.post(PUSHSAFER_API_URL, data=payload, timeout=10)
        resp.raise_for_status()
    except requests.RequestException:
        logger.exception("Failed to send Pushsafer notification")
