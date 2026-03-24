"""Async EQdkp Plus API client. Port of Ruby EqdkpPublisher."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from roboToald import config

logger = logging.getLogger(__name__)

API_PATH = "/api.php"


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
        return {"Content-Type": "application/json", "Host": self.host}

    async def _get(self, function: str, **extra) -> dict:
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.get(
                f"{self.base_url}{API_PATH}",
                params=self._params(function, **extra),
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def _post(self, function: str, body: dict) -> dict:
        async with httpx.AsyncClient(verify=False) as client:
            resp = await client.post(
                f"{self.base_url}{API_PATH}",
                params=self._params(function),
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def find_character(self, char_name: str) -> dict | None:
        data = await self._get("search", **{"in": "charname", "for": char_name})
        direct = data.get("direct", {})
        members = _values_with_prefix(direct, "member:")
        if not members:
            return None
        if len(members) == 1:
            return members[0]
        valid = [m for m in members if str(m.get("user_id", "0")) != "0"]
        return valid[0] if len(valid) == 1 else None

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
        data = await self._post("add_event", {
            "event_name": event_name,
            "event_value": event_value,
            "multidkp_poolid": 1,
        })
        return data["event_id"]

    async def create_character(self, name: str) -> dict | None:
        await self._post("character", {"name": name})
        return await self.find_character(name)

    async def create_member(self, character, session=None):
        """Find or create an EQdkp member for a Character, updating IDs.

        If *session* is provided the update is flushed (not committed) on that
        session so the caller can commit as part of a larger transaction.
        """
        from roboToald.db.raid_base import get_raid_session
        member = await self.find_character(character.name)
        if not member:
            await self._post("character", {"name": character.name})
            member = await self.find_character(character.name)
        if member:
            if session is not None:
                char = session.merge(character)
                char.eqdkp_member_id = member.get("id")
                char.eqdkp_user_id = member.get("user_id")
                char.eqdkp_main_id = member.get("main_id")
                session.flush()
                return char
            else:
                with get_raid_session(self.guild_id) as own_session:
                    char = own_session.merge(character)
                    char.eqdkp_member_id = member.get("id")
                    char.eqdkp_user_id = member.get("user_id")
                    char.eqdkp_main_id = member.get("main_id")
                    own_session.commit()
                    own_session.refresh(char)
                    return char
        return character

    async def create_raid(
        self,
        event_eqdkp_event_id: int,
        raid_value: int,
        raid_note: str,
        member_ids: list[int],
        raid_date: datetime | None = None,
    ) -> int:
        date_str = (raid_date or datetime.utcnow()).strftime("%Y-%m-%d %I:%M")
        data = await self._post("add_raid", {
            "raid_date": date_str,
            "raid_value": raid_value,
            "raid_event_id": event_eqdkp_event_id,
            "raid_note": raid_note,
            "raid_attendees": {"member": member_ids},
        })
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
        data = await self._post("add_item", {
            "item_date": date_str,
            "item_buyers": {"member": [member_id]},
            "item_name": item_name,
            "item_value": item_value,
            "item_raid_id": raid_id,
            "item_id": None,
            "item_game_id": None,
            "item_itempool_id": 1,
        })
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
