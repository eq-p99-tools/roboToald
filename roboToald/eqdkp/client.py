"""Async EQdkp Plus API client. Port of Ruby EqdkpPublisher."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import httpx

from roboToald import config

logger = logging.getLogger(__name__)

API_PATH = "/api.php"
HTTP_TIMEOUT = 30.0
GET_RETRY_STATUS = {502, 503, 504}
MAX_GET_RETRIES = 2


class EqdkpApiError(RuntimeError):
    """EQdkp API returned status 0 or an error payload (HTTP may still be 200)."""


class EqdkpCommunicationError(RuntimeError):
    """EQdkp request failed before a valid API payload was returned."""


@dataclass
class CharacterLookupResult:
    status: Literal["found", "not_found", "ambiguous"]
    member: dict | None = None


def _raise_for_status(
    resp: httpx.Response,
    function: str,
    body: dict | None = None,
    *,
    character_name: str | None = None,
) -> None:
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        logger.warning("EQdkp %s request failed with HTTP %s", function, status_code)
        message = f"EQdkp communication error (HTTP {status_code})"
        if body is not None:
            message = f"{message}: {body}"
        if character_name:
            message = f"{message} for character {character_name}"
        raise EqdkpCommunicationError(message) from None


def _raise_if_eqdkp_error(data: dict) -> None:
    if data.get("status") == 0:
        raise EqdkpApiError(data.get("error") or "unknown EQdkp error")


def _values_with_prefix(d: dict, prefix: str) -> list[dict]:
    """Extract values whose keys start with *prefix* (e.g. 'player:', 'member:')."""
    return [v for k, v in d.items() if isinstance(v, dict) and k.startswith(prefix)]


class EqdkpClient:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.base_url = config.get_eqdkp_setting(guild_id, "url")
        self.host = config.get_eqdkp_setting(guild_id, "host")
        self.api_key = config.get_eqdkp_setting(guild_id, "api_key")
        self._adjustment_event_id = config.get_eqdkp_setting(guild_id, "adjustment_event_id") or 0

    def _params(self, function: str, **extra) -> dict:
        return {"function": function, "atoken": self.api_key, "type": "api", "format": "json", **extra}

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.host:
            headers["Host"] = self.host
        return headers

    async def _request_get(self, function: str, **extra) -> httpx.Response:
        async with httpx.AsyncClient(verify=False, timeout=HTTP_TIMEOUT) as client:
            return await client.get(
                f"{self.base_url}{API_PATH}",
                params=self._params(function, **extra),
                headers=self._headers(),
            )

    async def _get(self, function: str, **extra) -> dict:
        last_exc: Exception | None = None
        for attempt in range(MAX_GET_RETRIES + 1):
            resp = await self._request_get(function, **extra)
            try:
                _raise_for_status(resp, function)
            except EqdkpCommunicationError as exc:
                last_exc = exc
                status_code = resp.status_code
                if attempt < MAX_GET_RETRIES and status_code in GET_RETRY_STATUS:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
            data = resp.json()
            _raise_if_eqdkp_error(data)
            return data
        if last_exc:
            raise last_exc
        raise EqdkpCommunicationError(f"EQdkp {function} request failed")

    async def _post(self, function: str, body: dict, *, character_name: str | None = None) -> dict:
        async with httpx.AsyncClient(verify=False, timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{self.base_url}{API_PATH}",
                params=self._params(function),
                headers=self._headers(),
                json=body,
            )
            _raise_for_status(resp, function, body, character_name=character_name)
            data = resp.json()
            _raise_if_eqdkp_error(data)
            return data

    async def lookup_character(self, char_name: str) -> CharacterLookupResult:
        data = await self._get("search", **{"in": "charname", "for": char_name})
        logger.debug("lookup_character(%s) raw: %s", char_name, data)
        direct = data.get("direct", {})
        members = _values_with_prefix(direct, "member:")
        if not members:
            return CharacterLookupResult(status="not_found")
        if len(members) == 1:
            return CharacterLookupResult(status="found", member=members[0])
        valid = [m for m in members if str(m.get("user_id", "0")) != "0"]
        if len(valid) == 1:
            return CharacterLookupResult(status="found", member=valid[0])
        return CharacterLookupResult(status="ambiguous")

    async def find_character(self, char_name: str) -> dict | None:
        lookup = await self.lookup_character(char_name)
        return lookup.member if lookup.status == "found" else None

    async def find_characters_by_discord_id(
        self,
        discord_id: str | int,
    ) -> list[dict]:
        """Look up EQdkp characters linked to a Discord user via auth_account."""
        data = await self._get(
            "search",
            **{"in": "auth_account", "for": str(discord_id)},
        )
        logger.debug(
            "find_characters_by_discord_id(%s) raw: %s",
            discord_id,
            data,
        )
        direct = data.get("direct", {})
        members = _values_with_prefix(direct, "member:")
        return [m for m in members if m.get("name")]

    async def find_points(self, user_id: str | int) -> str | None:
        data = await self._get("points", filter="user", filterid=str(user_id))
        players = _values_with_prefix(data.get("players", {}), "player:")
        if not players:
            return None
        points = players[0].get("points", {})
        mdkp = _values_with_prefix(points, "multidkp_points:")
        if mdkp:
            return mdkp[0].get("points_current_with_twink")
        return None

    async def create_event(self, event_name: str, event_value: int) -> int:
        data = await self._post(
            "add_event",
            {
                "event_name": event_name,
                "event_value": event_value,
                "multidkp_poolid": 1,
            },
        )
        return data["event_id"]

    async def create_character(self, name: str) -> dict | None:
        await self._post("character", {"name": name}, character_name=name)
        return await self.find_character(name)

    async def bind_member(self, character, session=None):
        """Bind EQdkp IDs for a Character after a fresh lookup-only validation."""
        from roboToald.db.raid_base import get_raid_session

        lookup = await self.lookup_character(character.name)
        if lookup.status == "not_found":
            raise EqdkpCommunicationError(f"Character {character.name} not found on EQdkp")
        if lookup.status == "ambiguous":
            raise EqdkpCommunicationError(f"Character {character.name} is ambiguous on EQdkp")
        member = lookup.member
        if session is not None:
            char = session.merge(character)
            char.eqdkp_member_id = member.get("id")
            char.eqdkp_user_id = member.get("user_id")
            char.eqdkp_main_id = member.get("main_id")
            session.flush()
            return char
        with get_raid_session(self.guild_id) as own_session:
            char = own_session.merge(character)
            char.eqdkp_member_id = member.get("id")
            char.eqdkp_user_id = member.get("user_id")
            char.eqdkp_main_id = member.get("main_id")
            own_session.commit()
            own_session.refresh(char)
            return char

    async def create_member(self, character, session=None):
        """Lookup-only alias retained for callers; does not create EQdkp characters."""
        return await self.bind_member(character, session=session)

    async def create_raid(
        self,
        event_eqdkp_event_id: int,
        raid_value: int,
        raid_note: str,
        member_ids: list[int],
        raid_date: datetime | None = None,
    ) -> int:
        date_str = (raid_date or datetime.utcnow()).strftime("%Y-%m-%d %I:%M")
        data = await self._post(
            "add_raid",
            {
                "raid_date": date_str,
                "raid_value": raid_value,
                "raid_event_id": event_eqdkp_event_id,
                "raid_note": raid_note,
                "raid_attendees": {"member": member_ids},
            },
        )
        return data["raid_id"]

    async def add_item(
        self,
        item_name: str,
        item_value: int,
        member_id: int,
        raid_id: int,
        item_date: datetime | None = None,
    ) -> int:
        date_str = (item_date or datetime.utcnow()).strftime("%Y-%m-%d %I:%M")
        data = await self._post(
            "add_item",
            {
                "item_date": date_str,
                "item_buyers": {"member": [member_id]},
                "item_name": item_name,
                "item_value": item_value,
                "item_raid_id": raid_id,
                "item_id": None,
                "item_game_id": None,
                "item_itempool_id": 1,
            },
        )
        return data["item_id"]

    async def add_adjustment(
        self,
        member_id: int,
        value: int,
        reason: str,
        event_id: int | None = None,
        raid_id: int | None = None,
        time: datetime | None = None,
    ) -> int:
        date_str = (time or datetime.utcnow()).strftime("%Y-%m-%d %I:%M")
        body: dict = {
            "adjustment_date": date_str,
            "adjustment_reason": reason,
            "adjustment_event_id": event_id or self._adjustment_event_id,
            "adjustment_members": {"member": [member_id]},
            "adjustment_value": value,
        }
        if raid_id:
            body["adjustment_raid_id"] = raid_id
        data = await self._post("add_adjustment", body)
        return data["adjustment_id"][0]
