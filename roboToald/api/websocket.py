"""WebSocket connection manager and delta protocol for real-time account updates."""
import asyncio
import logging
import threading
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from roboToald.db.models import sso as sso_model

logger = logging.getLogger(__name__)


def build_account_tree(accessible_accounts) -> dict:
    """Build an account_tree dict from a list of SSOAccount objects.

    Matches the v3 structure returned by POST /list_accounts.
    """
    tree = {}
    for account in accessible_accounts:
        tree[account.real_user] = {
            "aliases": [alias.alias for alias in account.aliases],
            "tags": [tag.tag for tag in account.tags],
            "characters": {
                char.name: {
                    "class": char.klass.value if char.klass else None,
                    "bind": char.bind_location,
                    "park": char.park_location,
                    "level": char.level,
                }
                for char in account.characters
            },
            "last_login": (
                account.last_login.isoformat()
                if account.last_login else None
            ),
        }
    return tree


def compute_diff(old_tree: dict, new_tree: dict) -> list[dict]:
    """Compute granular changes between two account_tree dicts.

    Handles:
      - aliases/tags as sets (add/remove)
      - characters as dicts (add/remove/update with full entry)
      - last_login as a scalar
    """
    changes: list[dict] = []
    old_keys = set(old_tree.keys())
    new_keys = set(new_tree.keys())

    for key in sorted(new_keys - old_keys):
        changes.append({
            "action": "add",
            "entity": "account",
            "account": key,
            "data": new_tree[key],
        })

    for key in sorted(old_keys - new_keys):
        changes.append({
            "action": "remove",
            "entity": "account",
            "account": key,
        })

    for key in sorted(old_keys & new_keys):
        old_data = old_tree[key]
        new_data = new_tree[key]
        if old_data == new_data:
            continue

        fields: dict = {}

        # Set-based fields
        for f in ("aliases", "tags"):
            old_set = set(old_data.get(f, []))
            new_set = set(new_data.get(f, []))
            added = sorted(new_set - old_set)
            removed = sorted(old_set - new_set)
            if added or removed:
                fields[f] = {"add": added, "remove": removed}

        # Dict-based characters field
        old_chars = old_data.get("characters", {})
        new_chars = new_data.get("characters", {})
        if old_chars != new_chars:
            char_diff = {}
            old_ckeys = set(old_chars.keys())
            new_ckeys = set(new_chars.keys())

            added_chars = {k: new_chars[k] for k in sorted(new_ckeys - old_ckeys)}
            removed_chars = sorted(old_ckeys - new_ckeys)
            updated_chars = {}
            for ck in sorted(old_ckeys & new_ckeys):
                if old_chars[ck] != new_chars[ck]:
                    updated_chars[ck] = new_chars[ck]

            if added_chars:
                char_diff["add"] = added_chars
            if removed_chars:
                char_diff["remove"] = removed_chars
            if updated_chars:
                char_diff["update"] = updated_chars
            if char_diff:
                fields["characters"] = char_diff

        # Scalar last_login
        old_ll = old_data.get("last_login")
        new_ll = new_data.get("last_login")
        if old_ll != new_ll:
            fields["last_login"] = new_ll

        if fields:
            changes.append({
                "action": "update",
                "entity": "account",
                "account": key,
                "fields": fields,
            })

    return changes


@dataclass
class ClientConnection:
    websocket: WebSocket
    guild_id: int
    discord_user_id: int
    last_sent_state: dict = field(default_factory=dict)


class ConnectionManager:
    """Manages WebSocket connections and pushes delta updates to clients."""

    def __init__(self):
        self._connections: list[ClientConnection] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._discord_client = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def set_discord_client(self, discord_client):
        self._discord_client = discord_client

    def register(self, conn: ClientConnection):
        with self._lock:
            self._connections.append(conn)
        logger.info(
            "WebSocket client registered: guild=%s user=%s",
            conn.guild_id, conn.discord_user_id,
        )

    def unregister(self, websocket: WebSocket):
        with self._lock:
            self._connections = [
                c for c in self._connections if c.websocket is not websocket
            ]
        logger.info("WebSocket client unregistered")

    def _get_connections_for_guild(self, guild_id: int) -> list[ClientConnection]:
        with self._lock:
            return [c for c in self._connections if c.guild_id == guild_id]

    # -- Public notification API (thread-safe) --------------------------------

    def notify_guild(self, guild_id: int):
        """Schedule a delta push for all clients of a guild.

        Safe to call from any thread (Discord bot, API handlers, etc.).
        """
        if self._loop is None or self._loop.is_closed():
            logger.warning("Cannot notify guild %s: event loop not available", guild_id)
            return
        asyncio.run_coroutine_threadsafe(
            self._notify_guild_async(guild_id), self._loop
        )

    async def notify_guild_async(self, guild_id: int):
        """Await-able version for callers already on the uvicorn event loop."""
        await self._notify_guild_async(guild_id)

    # -- Internal -------------------------------------------------------------

    async def _notify_guild_async(self, guild_id: int):
        connections = self._get_connections_for_guild(guild_id)
        if not connections:
            return

        all_accounts = sso_model.list_accounts(guild_id)

        for conn in connections:
            try:
                await self._push_delta(conn, guild_id, all_accounts)
            except Exception:
                logger.exception(
                    "Failed to push delta to WS client guild=%s user=%s",
                    guild_id, conn.discord_user_id,
                )

    async def _push_delta(self, conn: ClientConnection, guild_id: int, all_accounts):
        from roboToald.api.server import user_has_access_to_accounts

        if conn.websocket.client_state != WebSocketState.CONNECTED:
            self.unregister(conn.websocket)
            return

        accessible = user_has_access_to_accounts(
            self._discord_client,
            conn.discord_user_id,
            guild_id,
            [a.id for a in all_accounts],
        )
        new_tree = build_account_tree(accessible)
        changes = compute_diff(conn.last_sent_state, new_tree)

        if changes:
            conn.last_sent_state = new_tree
            await conn.websocket.send_json({"type": "delta", "changes": changes})

    async def build_full_state(self, guild_id: int, discord_user_id: int) -> dict:
        """Build the full account_tree for a user (used on initial WS auth)."""
        from roboToald.api.server import user_has_access_to_accounts

        all_accounts = sso_model.list_accounts(guild_id)
        accessible = user_has_access_to_accounts(
            self._discord_client,
            discord_user_id,
            guild_id,
            [a.id for a in all_accounts],
        )
        return build_account_tree(accessible)


manager = ConnectionManager()
