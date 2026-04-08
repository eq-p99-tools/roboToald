"""WebSocket connection manager and delta protocol for real-time account updates."""

import asyncio
import datetime
import logging
import threading
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from roboToald.db.models import sso as sso_model

logger = logging.getLogger(__name__)

# Coalesce rapid notify_guild calls (heartbeats, location updates) into one delta push per guild.
WS_NOTIFY_DEBOUNCE_SEC = 3.0

# Temporary: also emit legacy ``keys`` (seb/vp/st only) on each character for old login-proxy builds.
# Set False and remove ``_legacy_keys_subset`` usage to drop outbound ``keys``.
INCLUDE_LEGACY_KEYS_ON_ACCOUNT_TREE = True


def _legacy_keys_subset(items: dict) -> dict:
    """Zone keys only, for clients that still read ``character['keys']``."""
    return {"seb": items.get("seb"), "vp": items.get("vp"), "st": items.get("st")}


def _character_items_payload(char) -> dict:
    """Canonical ``items`` map for WebSocket (wire short names)."""
    return {
        "seb": char.key_seb,
        "vp": char.key_vp,
        "st": char.key_st,
        "void": char.item_void,
        "neck": char.item_neck,
        "lizard": char.item_lizard,
        "thurg": char.item_thurg,
        "reaper": char.item_reaper,
        "brass_idol": char.item_brass_idol,
        "pearl": char.item_pearl,
        "peridot": char.item_peridot,
        "mb3": char.item_mb3,
        "mb4": char.item_mb4,
        "mb5": char.item_mb5,
    }


def _build_character_tree_entry(char) -> dict:
    items = _character_items_payload(char)
    entry = {
        "class": char.klass.value if char.klass else None,
        "bind": char.bind_location,
        "park": char.park_location,
        "level": char.level,
        "items": items,
    }
    if INCLUDE_LEGACY_KEYS_ON_ACCOUNT_TREE:
        entry["keys"] = _legacy_keys_subset(items)
    return entry


def _brief_exc_info() -> str:
    """Return a one-line summary of the current exception (type + message)."""
    import sys

    exc = sys.exc_info()[1]
    return f"{type(exc).__name__}: {exc}" if exc else "unknown"


def build_account_tree(accessible_accounts, active_characters: dict[int, str] | None = None) -> dict:
    """Build an account_tree dict from a list of SSOAccount objects.

    Matches the v3 ``account_tree`` shape sent in WebSocket ``full_state`` messages.
    *active_characters* is an optional ``{account_id: character_name}`` map
    from :func:`sso_model.get_active_characters`.
    """
    if active_characters is None:
        active_characters = {}
    tree = {}
    for account in accessible_accounts:
        tree[account.real_user] = {
            "aliases": [alias.alias for alias in account.aliases],
            "tags": [tag.tag for tag in account.tags],
            "characters": {char.name: _build_character_tree_entry(char) for char in account.characters},
            "last_login": (
                account.last_login.astimezone(datetime.timezone.utc).isoformat()
                if account.last_login and account.last_login.year > 1
                else None
            ),
            "last_login_by": account.last_login_by,
            "active_character": active_characters.get(account.id),
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
        changes.append(
            {
                "action": "add",
                "entity": "account",
                "account": key,
                "data": new_tree[key],
            }
        )

    for key in sorted(old_keys - new_keys):
        changes.append(
            {
                "action": "remove",
                "entity": "account",
                "account": key,
            }
        )

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

        # Scalar fields
        for scalar in ("last_login", "last_login_by", "active_character"):
            old_val = old_data.get(scalar)
            new_val = new_data.get(scalar)
            if old_val != new_val:
                fields[scalar] = new_val

        if fields:
            changes.append(
                {
                    "action": "update",
                    "entity": "account",
                    "account": key,
                    "fields": fields,
                }
            )

    return changes


@dataclass
class ClientConnection:
    websocket: WebSocket
    guild_id: int
    discord_user_id: int
    last_sent_state: dict = field(default_factory=dict)
    connected_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    client_version: str = "unknown"
    client_ip: str = ""


class ConnectionManager:
    """Manages WebSocket connections and pushes delta updates to clients."""

    def __init__(self):
        self._connections: list[ClientConnection] = []
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._discord_client = None
        self._pending_guild_handles: dict[int, asyncio.TimerHandle] = {}

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def set_discord_client(self, discord_client):
        self._discord_client = discord_client

    def register(self, conn: ClientConnection):
        with self._lock:
            self._connections.append(conn)

    def unregister(self, websocket: WebSocket):
        with self._lock:
            self._connections = [c for c in self._connections if c.websocket is not websocket]

    def _get_connections_for_guild(self, guild_id: int) -> list[ClientConnection]:
        with self._lock:
            return [c for c in self._connections if c.guild_id == guild_id]

    def get_connections_summary(self) -> list[dict]:
        """Return metadata for all active connections (no websocket objects).

        Each dict contains guild_id, discord_user_id, client_version,
        connected_at, and optionally resolved guild_name / user_name.
        """
        with self._lock:
            snapshot = list(self._connections)

        results = []
        for conn in snapshot:
            info: dict = {
                "guild_id": conn.guild_id,
                "discord_user_id": conn.discord_user_id,
                "client_version": conn.client_version,
                "connected_at": conn.connected_at,
                "ip_cc": sso_model.ip_country_code(conn.client_ip) if conn.client_ip else "",
                "ip_hash": sso_model.hash_ip(conn.client_ip) if conn.client_ip else "",
            }
            if self._discord_client:
                guild = self._discord_client.get_guild(conn.guild_id)
                info["guild_name"] = guild.name if guild else str(conn.guild_id)
                member = guild.get_member(conn.discord_user_id) if guild else None
                info["user_name"] = member.display_name if member else str(conn.discord_user_id)
            else:
                info["guild_name"] = str(conn.guild_id)
                info["user_name"] = str(conn.discord_user_id)
            results.append(info)
        return results

    # -- Public notification API (thread-safe) --------------------------------

    def disconnect_user(self, guild_id: int, discord_user_id: int, code: int = 4003, reason: str = "Access revoked"):
        """Close all WebSocket connections for a specific user in a guild.

        Safe to call from any thread.
        """
        if self._loop is None or self._loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(
            self._disconnect_user_async(guild_id, discord_user_id, code, reason),
            self._loop,
        )

    async def _disconnect_user_async(self, guild_id: int, discord_user_id: int, code: int, reason: str):
        with self._lock:
            targets = [c for c in self._connections if c.guild_id == guild_id and c.discord_user_id == discord_user_id]
        for conn in targets:
            try:
                await conn.websocket.send_json({"type": "error", "detail": reason})
                await conn.websocket.close(code=code, reason=reason)
            except Exception:
                pass
            self.unregister(conn.websocket)
        if targets:
            logger.info(
                "Disconnected %d WebSocket session(s) for user %s in guild %s: %s",
                len(targets),
                discord_user_id,
                guild_id,
                reason,
            )

    def notify_guild(self, guild_id: int, immediate: bool = False):
        """Schedule a delta push for all clients of a guild.

        By default, notifications are debounced (see ``WS_NOTIFY_DEBOUNCE_SEC``) so
        bursts of heartbeats/location updates coalesce into one push. Pass *immediate* ``True``
        when the UI should see a change right away (e.g. Discord admin edits, successful login).

        Safe to call from any thread (Discord bot, API handlers, etc.).
        """
        if self._loop is None or self._loop.is_closed():
            logger.warning("Cannot notify guild %s: event loop not available", guild_id)
            return
        asyncio.run_coroutine_threadsafe(self._notify_guild_entry(guild_id, immediate), self._loop)

    async def notify_guild_async(self, guild_id: int, immediate: bool = False):
        """Await-able version for callers already on the uvicorn event loop."""
        await self._notify_guild_entry(guild_id, immediate)

    def _cancel_debounce(self, guild_id: int) -> None:
        h = self._pending_guild_handles.pop(guild_id, None)
        if h is not None and not h.cancelled():
            h.cancel()

    async def _notify_guild_entry(self, guild_id: int, immediate: bool) -> None:
        if immediate:
            self._cancel_debounce(guild_id)
            await self._notify_guild_async(guild_id)
        else:
            await self._debounce_schedule(guild_id)

    async def _debounce_schedule(self, guild_id: int) -> None:
        loop = asyncio.get_running_loop()

        def fire() -> None:
            self._pending_guild_handles.pop(guild_id, None)
            asyncio.create_task(self._notify_guild_async(guild_id))

        self._cancel_debounce(guild_id)
        self._pending_guild_handles[guild_id] = loop.call_later(WS_NOTIFY_DEBOUNCE_SEC, fire)

    # -- Internal -------------------------------------------------------------

    def _filter_accessible(self, discord_user_id: int, guild_id: int, accounts: list) -> list:
        """Filter accounts to those accessible by the user's Discord roles.

        Relies on the ``groups`` relationship already being loaded on each
        account (e.g. via ``joinedload``), so this does **no** DB queries.
        """
        if not self._discord_client:
            return []
        guild = self._discord_client.get_guild(guild_id)
        member = guild.get_member(discord_user_id) if guild else None
        if member is None:
            return []
        role_ids = {role.id for role in member.roles}
        return [a for a in accounts if any(g.role_id in role_ids for g in a.groups)]

    async def _notify_guild_async(self, guild_id: int):
        connections = self._get_connections_for_guild(guild_id)
        if not connections:
            return

        all_accounts = await asyncio.to_thread(sso_model.list_accounts, guild_id)
        active_characters = await asyncio.to_thread(sso_model.get_active_characters, guild_id)

        async def _safe_push(conn: ClientConnection):
            try:
                await self._push_delta(conn, guild_id, all_accounts, active_characters)
            except WebSocketDisconnect:
                logger.info(
                    "WS client disconnected during delta push guild=%s user=%s",
                    guild_id,
                    conn.discord_user_id,
                )
                self.unregister(conn.websocket)
            except Exception:
                logger.warning(
                    "Failed to push delta to WS client guild=%s user=%s: %s",
                    guild_id,
                    conn.discord_user_id,
                    _brief_exc_info(),
                )
                self.unregister(conn.websocket)

        await asyncio.gather(*[_safe_push(conn) for conn in connections])

    async def _push_delta(self, conn: ClientConnection, guild_id: int, all_accounts, active_characters: dict[int, str]):
        if conn.websocket.client_state != WebSocketState.CONNECTED:
            self.unregister(conn.websocket)
            return

        accessible = self._filter_accessible(conn.discord_user_id, guild_id, all_accounts)
        new_tree = build_account_tree(accessible, active_characters)
        changes = compute_diff(conn.last_sent_state, new_tree)

        if changes:
            conn.last_sent_state = new_tree
            await conn.websocket.send_json({"type": "delta", "changes": changes})

    async def build_full_state(self, guild_id: int, discord_user_id: int) -> dict:
        """Build the full account_tree for a user (used on initial WS auth)."""
        all_accounts, active_characters = await asyncio.gather(
            asyncio.to_thread(sso_model.list_accounts, guild_id),
            asyncio.to_thread(sso_model.get_active_characters, guild_id),
        )
        accessible = self._filter_accessible(discord_user_id, guild_id, all_accounts)
        return build_account_tree(accessible, active_characters)


manager = ConnectionManager()
