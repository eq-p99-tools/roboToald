"""Shared EQdkp character lookup and binding for raid commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from roboToald.db.raid_models.character import Character
from roboToald.eqdkp.client import EqdkpApiError, EqdkpClient, EqdkpCommunicationError


class EqdkpLookupStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    COMMUNICATION_ERROR = "communication_error"
    API_ERROR = "api_error"


@dataclass
class EqdkpCharacterResult:
    status: EqdkpLookupStatus
    char: Character | None = None
    error_line: str | None = None


def _not_found_line(name: str) -> str:
    return f"- Unable to locate the character {name} on EQDKP Site. Please make sure that character exists there first."


def _ambiguous_line(name: str) -> str:
    return f"- {name}: multiple EQdkp matches; resolve duplicates on the EQdkp site first."


def _communication_line(name: str, exc: Exception) -> str:
    return f"- {name}: EQdkp lookup failed ({exc}). Try again later."


def _api_line(name: str, exc: Exception) -> str:
    return f"- {name}: EQdkp rejected lookup ({exc}). Try again later."


def bind_member_ids(char: Character, member: dict) -> None:
    char.eqdkp_member_id = member.get("id")
    char.eqdkp_user_id = member.get("user_id")
    char.eqdkp_main_id = member.get("main_id")


async def resolve_character_for_raid(
    eqdkp: EqdkpClient,
    session,
    name: str,
    *,
    create_local: bool = True,
    klass: str | None = None,
) -> EqdkpCharacterResult:
    """Look up *name* in EQdkp, optionally creating a local Character row, and bind EQdkp IDs."""
    normalized = name.strip().capitalize()
    if not normalized:
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.NOT_FOUND,
            error_line="- Character name is required.",
        )

    char = session.query(Character).filter(Character.name.ilike(normalized)).first()
    try:
        lookup = await eqdkp.lookup_character(normalized)
    except EqdkpCommunicationError as exc:
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.COMMUNICATION_ERROR,
            error_line=_communication_line(normalized, exc),
        )
    except EqdkpApiError as exc:
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.API_ERROR,
            error_line=_api_line(normalized, exc),
        )
    except Exception as exc:
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.COMMUNICATION_ERROR,
            error_line=_communication_line(normalized, exc),
        )

    if lookup.status == "not_found":
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.NOT_FOUND,
            error_line=_not_found_line(normalized),
        )
    if lookup.status == "ambiguous":
        return EqdkpCharacterResult(
            status=EqdkpLookupStatus.AMBIGUOUS,
            error_line=_ambiguous_line(normalized),
        )

    member = lookup.member
    if char is None:
        if not create_local:
            return EqdkpCharacterResult(status=EqdkpLookupStatus.NOT_FOUND, error_line=_not_found_line(normalized))
        char = Character(name=normalized, klass=klass)
        session.add(char)
        session.flush()
    elif klass and not char.klass:
        char.klass = klass

    bind_member_ids(char, member)
    session.flush()
    return EqdkpCharacterResult(status=EqdkpLookupStatus.OK, char=char)


async def validate_characters_for_eqdkp(eqdkp: EqdkpClient, characters: list[Character]) -> list[str]:
    """Return deduplicated user-facing error lines for characters that cannot be bound."""
    errors: list[str] = []
    seen: set[str] = set()
    for char in characters:
        name = char.name
        if name in seen:
            continue
        seen.add(name)
        try:
            lookup = await eqdkp.lookup_character(name)
        except EqdkpCommunicationError as exc:
            errors.append(_communication_line(name, exc))
            continue
        except EqdkpApiError as exc:
            errors.append(_api_line(name, exc))
            continue
        except Exception as exc:
            errors.append(_communication_line(name, exc))
            continue

        if lookup.status == "not_found":
            errors.append(_not_found_line(name))
        elif lookup.status == "ambiguous":
            errors.append(_ambiguous_line(name))
    return errors
