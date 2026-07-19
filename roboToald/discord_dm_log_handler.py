"""Logging handler that forwards ERROR+ log records to a Discord user via DM.

Usage (in batphone.py after Discord client is ready):
    install_discord_dm_handler(discord_client, user_id)

Rate-limited to avoid flooding: at most one DM per COOLDOWN_SECONDS, with
overflow messages coalesced into a count.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time

COOLDOWN_SECONDS = 10
MAX_MESSAGE_LEN = 1900

_REDACT_PATTERNS = (
    (re.compile(r"(atoken=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(access_key=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(password=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(token=)[^&\s\"']+", re.IGNORECASE), r"\1[REDACTED]"),
)

_INSTALLED_HANDLER: DiscordDMHandler | None = None


def redact_sensitive_text(text: str) -> str:
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class _TransientGatewayFilter(logging.Filter):
    """Skip expected disnake gateway reconnect noise from operator DMs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "disnake.client":
            return True
        message = record.getMessage()
        if "Attempting a reconnect in" in message:
            return False
        if record.exc_info:
            exc_type = record.exc_info[0]
            if exc_type is not None and exc_type.__name__ == "ClientConnectionResetError":
                return False
        return True


class DiscordDMHandler(logging.Handler):
    """Emit ERROR+ log records as Discord DMs to a specific user."""

    def __init__(self, discord_client, user_id: int, *, level: int = logging.ERROR):
        super().__init__(level)
        self._client = discord_client
        self._user_id = user_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_sent = 0.0
        self._suppressed = 0
        self._lock = threading.Lock()
        self.addFilter(_TransientGatewayFilter())

    def _get_loop(self) -> asyncio.AbstractEventLoop | None:
        if self._loop is None:
            try:
                self._loop = self._client.loop
            except Exception:
                return None
        return self._loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            loop = self._get_loop()
            if loop is None or loop.is_closed():
                return
            if not self._client.is_ready():
                return

            now = time.monotonic()
            with self._lock:
                if now - self._last_sent < COOLDOWN_SECONDS:
                    self._suppressed += 1
                    return
                suppressed = self._suppressed
                self._suppressed = 0
                self._last_sent = now

            text = redact_sensitive_text(self.format(record))
            if suppressed:
                text = f"[+{suppressed} suppressed]\n{text}"
            if len(text) > MAX_MESSAGE_LEN:
                text = text[:MAX_MESSAGE_LEN] + "\n... (truncated)"

            asyncio.run_coroutine_threadsafe(self._send(text), loop)
        except Exception:
            self.handleError(record)

    async def _send(self, text: str) -> None:
        try:
            user = self._client.get_user(self._user_id)
            if user is None:
                user = await self._client.fetch_user(self._user_id)
            dm = user.dm_channel or await user.create_dm()
            await dm.send(f"```\n{text}\n```")
        except Exception:
            logging.getLogger(__name__).warning(
                "Failed to send Discord DM error alert to user_id=%s",
                self._user_id,
                exc_info=True,
            )


def install_discord_dm_handler(discord_client, user_id: int) -> DiscordDMHandler | None:
    """Attach a DiscordDMHandler to the root logger. Returns the handler, or None if user_id is 0."""
    global _INSTALLED_HANDLER
    if not user_id:
        return None
    if _INSTALLED_HANDLER is not None:
        return _INSTALLED_HANDLER
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s]\n%(message)s",
        datefmt="%H:%M:%S",
    )
    handler = DiscordDMHandler(discord_client, user_id)
    handler.setFormatter(fmt)
    logging.root.addHandler(handler)
    _INSTALLED_HANDLER = handler
    logging.getLogger(__name__).info("Discord DM error handler installed for user_id=%s", user_id)
    return handler
