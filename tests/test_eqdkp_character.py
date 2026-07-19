"""Tests for shared EQdkp character validation helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from roboToald.eqdkp.client import CharacterLookupResult, EqdkpCommunicationError
from roboToald.raid.eqdkp_character import (
    EqdkpLookupStatus,
    resolve_character_for_raid,
    validate_characters_for_eqdkp,
)


@pytest.mark.asyncio
async def test_resolve_character_for_raid_binds_existing(raid_session):
    eqdkp = MagicMock()
    eqdkp.lookup_character = AsyncMock(
        return_value=CharacterLookupResult(
            status="found",
            member={"id": 7, "user_id": "9", "main_id": 1},
        )
    )

    result = await resolve_character_for_raid(eqdkp, raid_session, "Denenn", create_local=True)

    assert result.status == EqdkpLookupStatus.OK
    assert result.char is not None
    assert result.char.name == "Denenn"
    assert result.char.eqdkp_member_id == 7


@pytest.mark.asyncio
async def test_resolve_character_for_raid_rejects_missing(raid_session):
    eqdkp = MagicMock()
    eqdkp.lookup_character = AsyncMock(return_value=CharacterLookupResult(status="not_found"))

    result = await resolve_character_for_raid(eqdkp, raid_session, "Missing", create_local=True)

    assert result.status == EqdkpLookupStatus.NOT_FOUND
    assert "Unable to locate the character Missing" in (result.error_line or "")


@pytest.mark.asyncio
async def test_validate_characters_for_eqdkp_deduplicates(raid_session):
    from roboToald.db.raid_models.character import Character

    eqdkp = MagicMock()
    eqdkp.lookup_character = AsyncMock(return_value=CharacterLookupResult(status="ambiguous"))

    char = Character(name="Dup")
    raid_session.add(char)
    raid_session.commit()

    errors = await validate_characters_for_eqdkp(eqdkp, [char, char])

    assert len(errors) == 1
    assert "Dup" in errors[0]


@pytest.mark.asyncio
async def test_validate_characters_for_eqdkp_communication_error(raid_session):
    from roboToald.db.raid_models.character import Character

    eqdkp = MagicMock()
    eqdkp.lookup_character = AsyncMock(side_effect=EqdkpCommunicationError("HTTP 500"))

    char = Character(name="Bob")
    raid_session.add(char)
    raid_session.commit()

    errors = await validate_characters_for_eqdkp(eqdkp, [char])

    assert len(errors) == 1
    assert "Bob" in errors[0]
