"""HTMX admin management routes for the SSO dashboard."""

from __future__ import annotations

import datetime
import logging
from typing import Any
import urllib.parse

import sqlalchemy
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from roboToald.api import dashboard
from roboToald.api.websocket import manager as ws_manager
from roboToald.db.models import sso as sso_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/manage", tags=["admin"])

MANAGE_TEMPLATE_PREFIX = "partials/manage"
BOOL_FIELDS = (
    "key_seb",
    "key_vp",
    "key_st",
    "item_void",
    "item_neck",
    "item_thurg",
    "item_reaper",
    "item_brass_idol",
)
INT_FIELDS = ("item_lizard", "item_pearl", "item_peridot", "item_mb3", "item_mb4", "item_mb5")
CHARACTER_ITEM_FIELDS = BOOL_FIELDS + INT_FIELDS
ITEM_FIELD_LABELS = {
    "key_seb": "Trakanon Idol (Sebilis key)",
    "key_vp": "Key of Veeshan",
    "key_st": "Sleeper's Key",
    "item_void": "Box of the Void",
    "item_neck": "Necklace of Resolution",
    "item_lizard": "Lizard Blood Potion",
    "item_thurg": "Vial of Velium Vapors",
    "item_reaper": "Reaper of the Dead",
    "item_brass_idol": "Shiny Brass Idol",
    "item_pearl": "Pearl",
    "item_peridot": "Peridot",
    "item_mb3": "Mana Battery - Class Three",
    "item_mb4": "Mana Battery - Class Four",
    "item_mb5": "Mana Battery - Class Five",
}
ZONE_ALIASES = {
    "ak'anon": "akanon",
    "arena": "arena",
    "befallen": "befallen",
    "blackburrow": "blackburrow",
    "burning woods": "burningwood",
    "butcherblock mountains": "butcher",
    "cabilis east": "cabeast",
    "cabilis west": "cabwest",
    "castle mistmoore": "mistmoore",
    "cazic-thule": "cazicthule",
    "chardok": "chardok",
    "city of mist": "citymist",
    "city of thurgadin": "thurgadina",
    "clan crushbone": "crushbone",
    "clan runnyeye": "runnyeye",
    "cobalt scar": "cobaltscar",
    "crushbone": "crushbone",
    "crystal caverns": "crystal",
    "dagnor's cauldron": "cauldron",
    "dalnir": "dalnir",
    "dragon necropolis": "necropolis",
    "dreadlands": "dreadlands",
    "east cabilis": "cabeast",
    "east commonlands": "ecommons",
    "east freeport": "freporte",
    "east karana": "eastkarana",
    "eastern plains of karana": "eastkarana",
    "eastern wastelands": "eastwastes",
    "eastern wastes": "eastwastes",
    "erud's crossing": "erudsxing",
    "erudin": "erudnext",
    "erudin palace": "erudnint",
    "estate of unrest": "unrest",
    "everfrost": "everfrost",
    "everfrost peaks": "everfrost",
    "field of bone": "fieldofbone",
    "firiona vie": "firiona",
    "frontier mountains": "frontiermtns",
    "greater faydark": "gfaydark",
    "grobb": "grobb",
    "guk": "guktop",
    "halas": "halas",
    "high keep": "highkeep",
    "highkeep": "highkeep",
    "highpass hold": "highpass",
    "howling stones": "charasis",
    "iceclad ocean": "iceclad",
    "icewell keep": "thurgadinb",
    "infected paw": "paw",
    "innothule swamp": "innothule",
    "kael drakkal": "kael",
    "kael drakkel": "kael",
    "kaesora": "kaesora",
    "karnor's castle": "karnor",
    "kedge keep": "kedge",
    "kerra isle": "kerraridge",
    "kithicor forest": "kithicor",
    "kithicor woods": "kithicor",
    "kurn's tower": "kurn",
    "lake of ill omen": "lakeofillomen",
    "lake rathetear": "lakerathe",
    "lavastorm mountains": "lavastorm",
    "lesser faydark": "lfaydark",
    "lost temple of cazic-thule": "cazicthule",
    "lower guk": "gukbottom",
    "mines of nurga": "nurga",
    "misty thicket": "misty",
    "mountains of rathe": "rathemtn",
    "nagafen's lair": "soldungb",
    "najena": "najena",
    "nektulos forest": "nektulos",
    "neriak commons": "neriakb",
    "neriak foreign quarter": "neriaka",
    "neriak third gate": "neriakc",
    "north freeport": "freportn",
    "north kaladim": "kaladimb",
    "north karana": "northkarana",
    "north qeynos": "qeynos2",
    "north ro": "nro",
    "northern desert of ro": "nro",
    "northern felwithe": "felwithea",
    "northern plains of karana": "northkarana",
    "oasis of marr": "oasis",
    "ocean of tears": "oot",
    "oggok": "oggok",
    "old sebilis": "sebilis",
    "paineel": "paineel",
    "permafrost caverns": "permafrost",
    "permafrost keep": "permafrost",
    "plane of air": "airplane",
    "plane of fear": "fearplane",
    "plane of growth": "growthplane",
    "plane of hate": "hateplane",
    "plane of mischief": "mischiefplane",
    "plane of sky": "airplane",
    "qeynos aqueduct system": "qcat",
    "qeynos catacombs": "qcat",
    "qeynos hills": "qeytoqrg",
    "rathe mountains": "rathemtn",
    "rivervale": "rivervale",
    "ruins of old guk": "gukbottom",
    "ruins of old paineel": "hole",
    "ruins of sebilis": "sebilis",
    "runnyeye citadel": "runnyeye",
    "siren's grotto": "sirens",
    "sirens grotto": "sirens",
    "skyfire mountains": "skyfire",
    "skyshrine": "skyshrine",
    "sleeper's tomb": "sleeper",
    "sleepers tomb": "sleeper",
    "solusek's eye": "soldunga",
    "south cabilis": "cabwest",
    "south kaladim": "kaladima",
    "south karana": "southkarana",
    "south qeynos": "qeynos",
    "south ro": "sro",
    "southern desert of ro": "sro",
    "southern felwithe": "felwitheb",
    "southern plains of karana": "southkarana",
    "steamfont mountains": "steamfont",
    "stonebrunt mountains": "stonebrunt",
    "surefall glade": "qrg",
    "swamp of no hope": "swampofnohope",
    "temple of droga": "droga",
    "temple of solusek ro": "soltemple",
    "temple of veeshan": "templeveeshan",
    "the burning wood": "burningwood",
    "the city of mist": "citymist",
    "the emerald jungle": "emeraldjungle",
    "the feerrott": "feerrott",
    "the field of bone": "fieldofbone",
    "the hole": "hole",
    "the nektulos forest": "nektulos",
    "the overthere": "overthere",
    "the plane of hate": "hateplane",
    "the ruins of old paineel": "hole",
    "the wakening land": "wakening",
    "the wakening lands": "wakening",
    "the warrens": "warrens",
    "thurgadin": "thurgadina",
    "timorous deep": "timorous",
    "tower of frozen shadow": "frozenshadow",
    "toxxulia forest": "tox",
    "trakanon's teeth": "trakanon",
    "upper guk": "guktop",
    "veeshan's peak": "veeshan",
    "velketor's labyrinth": "velketor",
    "warrens": "warrens",
    "warsliks wood": "warslikswood",
    "warsliks woods": "warslikswood",
    "west cabilis": "cabwest",
    "west commonlands": "commons",
    "west freeport": "freportw",
    "west karana": "qey2hh1",
    "western plains of karana": "qey2hh1",
    "western wastes": "westwastes",
}
ZONE_KEY_TO_LABEL = {
    zone_key: " ".join(part.capitalize() for part in label.split()) for label, zone_key in sorted(ZONE_ALIASES.items())
}
ZONE_CHOICES = tuple(sorted(ZONE_KEY_TO_LABEL.items(), key=lambda item: item[1].lower()))


class DashboardManageError(Exception):
    """Expected user-facing management error."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=303)


def _get_authenticated_session(request: Request) -> dict | None:
    return dashboard._get_session(request)


def _csrf(session: dict) -> str:
    return str(session.get("csrf") or "")


def _base_context(request: Request, session: dict, active: str, message: str = "", error: str = "") -> dict[str, Any]:
    return {
        "request": request,
        "active": active,
        "csrf": _csrf(session),
        "message": message,
        "error": error,
    }


def _parse_int(value: str | None, field: str, *, required: bool = False) -> int | None:
    if value is None or value.strip() == "":
        if required:
            raise DashboardManageError(f"{field} is required")
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DashboardManageError(f"{field} must be a number") from exc


def _parse_bool(value: str | None) -> bool | None:
    if value in (None, ""):
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise DashboardManageError("Boolean values must be true, false, or unset")


def _parse_class(value: str | None) -> sso_model.CharacterClass | None:
    if not value:
        return None
    try:
        return sso_model.CharacterClass[value]
    except KeyError as exc:
        raise DashboardManageError(f"Invalid class: {value}") from exc


def _normalize_zone_key(value: str | None) -> str | None:
    """Normalize dashboard zone form values to the internal zone key format."""
    if not value:
        return None
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if cleaned in ZONE_KEY_TO_LABEL:
        return cleaned
    return ZONE_ALIASES.get(cleaned, cleaned)


async def _form(request: Request) -> dict[str, str]:
    data = {k: str(v) for k, v in request.query_params.items()}
    form = await request.form()
    data.update({k: str(v) for k, v in form.items()})
    return data


async def _require_mutation(request: Request, session: dict) -> dict[str, str]:
    form = await _form(request)
    if form.get("csrf") != _csrf(session):
        raise DashboardManageError("Invalid CSRF token", status_code=403)
    return form


def _allowed_guild_ids(session: dict, guild_id: int | None = None) -> list[int]:
    return dashboard._sso_guild_ids(session.get("guilds", []), guild_id)


def _require_guild(session: dict, guild_id_raw: str | int | None) -> int:
    guild_id = _parse_int(str(guild_id_raw) if guild_id_raw is not None else None, "guild_id", required=True)
    if guild_id not in _allowed_guild_ids(session):
        raise DashboardManageError("Guild is not in your dashboard scope", status_code=403)
    return guild_id


def _select_guild_ids(request: Request, session: dict) -> list[int]:
    raw = request.query_params.get("guild_id")
    if raw:
        try:
            return _allowed_guild_ids(session, int(raw))
        except ValueError:
            return []
    return _allowed_guild_ids(session)


def _resolve_role_name(discord_client, guild_id: int, role_id: int) -> str:
    return dashboard._resolve_role_name(discord_client, guild_id, role_id)


def _resolve_guild_name(discord_client, guild_id: int) -> str:
    return dashboard._resolve_guild_name(discord_client, guild_id)


def _resolve_discord_name(discord_client, guild_id: int, discord_user_id: int | None) -> str:
    if discord_user_id is None:
        return ""
    return dashboard._resolve_discord_name(discord_client, guild_id, discord_user_id)


def _quote(value: str | int) -> str:
    return urllib.parse.quote(str(value), safe="")


def _template(request: Request, name: str, context: dict[str, Any], status_code: int = 200) -> HTMLResponse:
    context.setdefault("quote", _quote)
    return dashboard.templates.TemplateResponse(
        request,
        f"{MANAGE_TEMPLATE_PREFIX}/{name}",
        context,
        status_code=status_code,
    )


def _notify_and_audit(session: dict, guild_id: int, username: str, details: str) -> None:
    ws_manager.notify_guild(guild_id, immediate=True)
    sso_model.create_audit_log(
        username=username,
        success=True,
        discord_user_id=session.get("uid"),
        guild_id=guild_id,
        details=details,
        rate_limit=False,
    )


def _format_last_login(value: datetime.datetime | None) -> str:
    if not value or value == datetime.datetime.min:
        return ""
    return value.isoformat()


def _account_rows(discord_client, guild_id: int) -> list[dict[str, Any]]:
    rows = []
    for account in sso_model.list_accounts(guild_id):
        rows.append(
            {
                "id": account.id,
                "guild_id": guild_id,
                "real_user": account.real_user,
                "owner_id": account.owner_discord_user_id,
                "owner_name": _resolve_discord_name(discord_client, guild_id, account.owner_discord_user_id),
                "groups": sorted(account.groups, key=lambda g: g.group_name),
                "tags": sorted({t.tag for t in account.tags}),
                "aliases": sorted(a.alias for a in account.aliases),
                "characters": sorted(account.characters, key=lambda c: c.name.lower()),
                "shares": sorted(account.shares, key=lambda s: s.shared_with_discord_user_id),
                "last_login_iso": _format_last_login(account.last_login),
                "last_login_by": account.last_login_by or "",
            }
        )
    return sorted(rows, key=lambda r: r["real_user"])


def _groups_for_guild(discord_client, guild_id: int) -> list[dict[str, Any]]:
    rows = []
    for group in sso_model.list_account_groups(guild_id):
        rows.append(
            {
                "guild_id": guild_id,
                "group_name": group.group_name,
                "role_id": group.role_id,
                "role_name": _resolve_role_name(discord_client, guild_id, group.role_id),
                "account_count": len(group.accounts),
            }
        )
    return sorted(rows, key=lambda r: r["group_name"].lower())


def _tags_for_guild(guild_id: int) -> list[dict[str, Any]]:
    return [
        {"guild_id": guild_id, "tag": tag, "accounts": sorted(accounts)}
        for tag, accounts in sorted(sso_model.list_tags(guild_id).items())
    ]


def _aliases_for_guild(guild_id: int) -> list[dict[str, Any]]:
    rows = []
    for alias in sso_model.list_account_aliases(guild_id):
        rows.append(
            {
                "guild_id": guild_id,
                "alias": alias.alias,
                "real_user": alias.account.real_user if alias.account else "",
            }
        )
    return sorted(rows, key=lambda r: r["alias"].lower())


def _characters_for_guild(guild_id: int) -> list[Any]:
    return sorted(sso_model.list_account_characters(guild_id), key=lambda c: c.name.lower())


def _shares_for_guild(discord_client, guild_id: int, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for account in accounts:
        for share in account["shares"]:
            rows.append(
                {
                    "guild_id": guild_id,
                    "real_user": account["real_user"],
                    "shared_with_discord_user_id": share.shared_with_discord_user_id,
                    "shared_with_name": _resolve_discord_name(
                        discord_client,
                        guild_id,
                        share.shared_with_discord_user_id,
                    ),
                    "created_by_discord_user_id": share.created_by_discord_user_id,
                    "created_by_name": _resolve_discord_name(
                        discord_client,
                        guild_id,
                        share.created_by_discord_user_id,
                    ),
                    "created_at_iso": share.created_at.isoformat() if share.created_at else "",
                }
            )
    return sorted(rows, key=lambda r: (r["real_user"], r["shared_with_discord_user_id"]))


def _roles_for_guild(discord_client, guild_id: int) -> list[dict[str, str | int]]:
    guild = discord_client.get_guild(guild_id) if discord_client else None
    if not guild:
        return []
    return sorted(
        [{"id": role.id, "name": role.name} for role in guild.roles],
        key=lambda r: str(r["name"]).lower(),
    )


def _guild_context(
    request: Request,
    session: dict,
    active: str,
    message: str = "",
    error: str = "",
    selected_guild_id: int | None = None,
) -> dict[str, Any]:
    discord_client = getattr(request.app.state, "discord_client", None)
    guild_ids = (
        _allowed_guild_ids(session, selected_guild_id) if selected_guild_id else _select_guild_ids(request, session)
    )
    guilds = []
    for gid in guild_ids:
        accounts = _account_rows(discord_client, gid)
        guilds.append(
            {
                "id": gid,
                "name": _resolve_guild_name(discord_client, gid),
                "accounts": accounts,
                "groups": _groups_for_guild(discord_client, gid),
                "roles": _roles_for_guild(discord_client, gid),
                "tags": _tags_for_guild(gid),
                "aliases": _aliases_for_guild(gid),
                "characters": _characters_for_guild(gid),
                "shares": _shares_for_guild(discord_client, gid, accounts),
            }
        )
    context = _base_context(request, session, active, message=message, error=error)
    context.update(
        {
            "guilds": guilds,
            "classes": list(sso_model.CharacterClass),
            "bool_fields": BOOL_FIELDS,
            "int_fields": INT_FIELDS,
            "character_item_fields": CHARACTER_ITEM_FIELDS,
            "item_field_labels": ITEM_FIELD_LABELS,
            "zone_choices": ZONE_CHOICES,
            "zone_labels": ZONE_KEY_TO_LABEL,
        }
    )
    return context


def _handle_error(request: Request, session: dict, active: str, exc: Exception) -> HTMLResponse:
    if isinstance(exc, DashboardManageError):
        return _template(
            request, f"{active}.html", _guild_context(request, session, active, error=exc.message), exc.status_code
        )
    logger.exception("Dashboard manage action failed")
    return _template(
        request,
        f"{active}.html",
        _guild_context(request, session, active, error="Unexpected dashboard management error"),
        500,
    )


@router.get("/partials/character_form", response_class=HTMLResponse)
async def partial_character_form(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return _redirect_login()
    try:
        guild_id = _require_guild(session, request.query_params.get("guild_id"))
        name = (request.query_params.get("name") or "").strip()
        character = None
        for candidate in sso_model.list_account_characters(guild_id):
            if candidate.name == name:
                character = candidate
                break
        if character is None:
            raise DashboardManageError(f"Character not found: {name}", status_code=404)
    except Exception as exc:
        return _handle_error(request, session, "characters", exc)
    context = _base_context(request, session, "characters")
    context.update(
        {
            "guild_id": guild_id,
            "character": character,
            "classes": list(sso_model.CharacterClass),
            "bool_fields": BOOL_FIELDS,
            "int_fields": INT_FIELDS,
            "item_field_labels": ITEM_FIELD_LABELS,
            "zone_choices": ZONE_CHOICES,
            "zone_labels": ZONE_KEY_TO_LABEL,
        }
    )
    return _template(request, "character_form.html", context)


@router.get("/partials/{active}", response_class=HTMLResponse)
async def partial_manage(request: Request, active: str):
    session = _get_authenticated_session(request)
    if not session:
        return _redirect_login()
    if active not in {"accounts", "groups", "tags", "aliases", "characters", "shares"}:
        return Response(status_code=404)
    return _template(request, f"{active}.html", _guild_context(request, session, active))


@router.post("/accounts", response_class=HTMLResponse)
async def create_account(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        real_user = (form.get("real_user") or "").strip()
        real_pass = form.get("real_pass") or ""
        if not real_user or not real_pass:
            raise DashboardManageError("Account username and password are required")
        owner_id = _parse_int(form.get("owner_discord_user_id"), "owner_discord_user_id")
        sso_model.create_account(guild_id, real_user, real_pass, form.get("group_name") or None, owner_id)
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:create account {real_user.lower()}")
        return _template(
            request,
            "accounts.html",
            _guild_context(request, session, "accounts", "Account created", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sqlalchemy.exc.IntegrityError, sso_model.SSOAccountGroupNotFoundError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Account already exists or violates a database constraint")
        return _handle_error(request, session, "accounts", exc)


@router.put("/accounts/{real_user}", response_class=HTMLResponse)
async def update_account(request: Request, real_user: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        password = form.get("real_pass") or ""
        owner_id_raw = form.get("owner_discord_user_id")
        if password:
            sso_model.update_account(guild_id, real_user, password)
        if owner_id_raw is not None:
            sso_model.set_account_owner(guild_id, real_user, _parse_int(owner_id_raw, "owner_discord_user_id"))
        if not password and owner_id_raw is None:
            raise DashboardManageError("No account update was submitted")
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:update account {real_user.lower()}")
        return _template(
            request,
            "accounts.html",
            _guild_context(request, session, "accounts", "Account updated", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountNotFoundError) as exc:
        return _handle_error(request, session, "accounts", exc)


@router.delete("/accounts/{real_user}", response_class=HTMLResponse)
async def delete_account(request: Request, real_user: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.delete_account(guild_id, real_user)
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:delete account {real_user.lower()}")
        return _template(
            request,
            "accounts.html",
            _guild_context(request, session, "accounts", "Account deleted", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sqlalchemy.exc.NoResultFound) as exc:
        if isinstance(exc, sqlalchemy.exc.NoResultFound):
            exc = DashboardManageError(f"Account not found: {real_user}", status_code=404)
        return _handle_error(request, session, "accounts", exc)


@router.post("/accounts/{real_user}/groups", response_class=HTMLResponse)
async def add_account_group(request: Request, real_user: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        group_name = (form.get("group_name") or "").strip()
        if not group_name:
            raise DashboardManageError("Group name is required")
        sso_model.add_account_to_group(guild_id, group_name, real_user)
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:add group {group_name} to {real_user}")
        return _template(
            request,
            "accounts.html",
            _guild_context(request, session, "accounts", "Group added", selected_guild_id=guild_id),
        )
    except (
        DashboardManageError,
        sso_model.SSOAccountGroupNotFoundError,
        sso_model.SSOAccountNotFoundError,
        sqlalchemy.exc.IntegrityError,
    ) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Account is already in that group")
        return _handle_error(request, session, "accounts", exc)


@router.delete("/accounts/{real_user}/groups/{group_name}", response_class=HTMLResponse)
async def remove_account_group(request: Request, real_user: str, group_name: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.remove_account_from_group(guild_id, group_name, real_user)
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:remove group {group_name} from {real_user}")
        return _template(
            request,
            "accounts.html",
            _guild_context(request, session, "accounts", "Group removed", selected_guild_id=guild_id),
        )
    except (
        DashboardManageError,
        sso_model.SSOAccountGroupNotFoundError,
        sso_model.SSOAccountNotFoundError,
        sqlalchemy.exc.IntegrityError,
    ) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Account is not in that group")
        return _handle_error(request, session, "accounts", exc)


@router.post("/groups", response_class=HTMLResponse)
async def create_group(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        group_name = (form.get("group_name") or "").strip()
        role_id = _parse_int(form.get("role_id"), "role_id", required=True)
        if not group_name:
            raise DashboardManageError("Group name is required")
        sso_model.create_account_group(guild_id, group_name, role_id)
        _notify_and_audit(session, guild_id, group_name, f"dashboard:create group {group_name}")
        return _template(
            request,
            "groups.html",
            _guild_context(request, session, "groups", "Group created", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sqlalchemy.exc.IntegrityError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Group already exists or violates a database constraint")
        return _handle_error(request, session, "groups", exc)


@router.put("/groups/{group_name}", response_class=HTMLResponse)
async def update_group(request: Request, group_name: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        new_name = (form.get("new_name") or "").strip()
        if not new_name:
            raise DashboardManageError("New group name is required")
        sso_model.update_account_group(guild_id, group_name, new_name)
        _notify_and_audit(session, guild_id, group_name, f"dashboard:rename group {group_name} to {new_name}")
        return _template(
            request,
            "groups.html",
            _guild_context(request, session, "groups", "Group renamed", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountGroupNotFoundError, sqlalchemy.exc.IntegrityError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("New group name already exists")
        return _handle_error(request, session, "groups", exc)


@router.delete("/groups/{group_name}", response_class=HTMLResponse)
async def delete_group(request: Request, group_name: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.delete_account_group(guild_id, group_name)
        _notify_and_audit(session, guild_id, group_name, f"dashboard:delete group {group_name}")
        return _template(
            request,
            "groups.html",
            _guild_context(request, session, "groups", "Group deleted", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountGroupNotFoundError) as exc:
        return _handle_error(request, session, "groups", exc)


@router.post("/tags", response_class=HTMLResponse)
async def create_tag(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        real_user = (form.get("real_user") or "").strip()
        tag = (form.get("tag") or "").strip()
        if not real_user or not tag:
            raise DashboardManageError("Account and tag are required")
        sso_model.tag_account(guild_id, real_user, tag)
        _notify_and_audit(session, guild_id, tag.lower(), f"dashboard:add tag {tag.lower()} to {real_user.lower()}")
        return _template(
            request,
            "tags.html",
            _guild_context(request, session, "tags", "Tag added", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountNotFoundError, sqlalchemy.exc.IntegrityError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Tag already exists on that account")
        return _handle_error(request, session, "tags", exc)


@router.put("/tags/{tag}", response_class=HTMLResponse)
async def update_tag(request: Request, tag: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        new_name = (form.get("new_name") or "").strip()
        if not new_name:
            raise DashboardManageError("New tag name is required")
        sso_model.update_tag(guild_id, tag, new_name=new_name)
        _notify_and_audit(session, guild_id, tag.lower(), f"dashboard:rename tag {tag.lower()} to {new_name.lower()}")
        return _template(
            request,
            "tags.html",
            _guild_context(request, session, "tags", "Tag renamed", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountTagNotFoundError, sqlalchemy.exc.IntegrityError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("New tag name conflicts with an existing account tag")
        return _handle_error(request, session, "tags", exc)


@router.delete("/tags/{tag}/accounts/{real_user}", response_class=HTMLResponse)
async def delete_tag(request: Request, tag: str, real_user: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.untag_account(guild_id, real_user, tag)
        _notify_and_audit(
            session, guild_id, tag.lower(), f"dashboard:remove tag {tag.lower()} from {real_user.lower()}"
        )
        return _template(
            request,
            "tags.html",
            _guild_context(request, session, "tags", "Tag removed", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountNotFoundError, sso_model.SSOAccountTagNotFoundError) as exc:
        return _handle_error(request, session, "tags", exc)


@router.post("/aliases", response_class=HTMLResponse)
async def create_alias(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        real_user = (form.get("real_user") or "").strip()
        alias = (form.get("alias") or "").strip()
        if not real_user or not alias:
            raise DashboardManageError("Account and alias are required")
        sso_model.create_account_alias(guild_id, real_user, alias)
        _notify_and_audit(session, guild_id, alias.lower(), f"dashboard:create alias {alias.lower()} for {real_user}")
        return _template(
            request,
            "aliases.html",
            _guild_context(request, session, "aliases", "Alias created", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountNotFoundError, sqlalchemy.exc.IntegrityError) as exc:
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            exc = DashboardManageError("Alias already exists")
        return _handle_error(request, session, "aliases", exc)


@router.delete("/aliases/{alias}", response_class=HTMLResponse)
async def delete_alias(request: Request, alias: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.delete_account_alias(guild_id, alias)
        _notify_and_audit(session, guild_id, alias.lower(), f"dashboard:delete alias {alias.lower()}")
        return _template(
            request,
            "aliases.html",
            _guild_context(request, session, "aliases", "Alias deleted", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountAliasNotFoundError) as exc:
        return _handle_error(request, session, "aliases", exc)


@router.post("/characters", response_class=HTMLResponse)
async def create_character(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        real_user = (form.get("real_user") or "").strip()
        name = (form.get("name") or "").strip()
        klass = _parse_class(form.get("klass"))
        if not real_user or not name or klass is None:
            raise DashboardManageError("Account, character name, and class are required")
        sso_model.add_account_character(guild_id, real_user, name, klass)
        kwargs = _character_update_kwargs(form)
        if kwargs:
            sso_model.update_account_character(guild_id, name, **kwargs)
        _notify_and_audit(session, guild_id, name, f"dashboard:create character {name}")
        return _template(
            request,
            "characters.html",
            _guild_context(request, session, "characters", "Character added", selected_guild_id=guild_id),
        )
    except (
        DashboardManageError,
        sso_model.SSOAccountNotFoundError,
        sso_model.SSOCharacterAlreadyExistsError,
    ) as exc:
        return _handle_error(request, session, "characters", exc)


def _character_update_kwargs(form: dict[str, str]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    klass = _parse_class(form.get("klass"))
    if klass:
        kwargs["klass"] = klass
    for field in ("bind_location", "park_location"):
        if field in form:
            value = _normalize_zone_key(form.get(field))
            if value:
                kwargs[field] = value
    if "level" in form:
        kwargs["level"] = _parse_int(form.get("level"), "level")
    for field in BOOL_FIELDS:
        if field in form:
            kwargs[field] = _parse_bool(form.get(field))
    for field in INT_FIELDS:
        if field in form:
            kwargs[field] = _parse_int(form.get(field), field)
    return kwargs


@router.put("/characters/{name}", response_class=HTMLResponse)
async def update_character(request: Request, name: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        if not sso_model.update_account_character(guild_id, name, **_character_update_kwargs(form)):
            raise DashboardManageError(f"Character not found: {name}", status_code=404)
        _notify_and_audit(session, guild_id, name, f"dashboard:update character {name}")
        return _template(
            request,
            "characters.html",
            _guild_context(request, session, "characters", "Character updated", selected_guild_id=guild_id),
        )
    except DashboardManageError as exc:
        return _handle_error(request, session, "characters", exc)


@router.delete("/characters/{name}", response_class=HTMLResponse)
async def delete_character(request: Request, name: str):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        if not sso_model.remove_account_character(guild_id, name):
            raise DashboardManageError(f"Character not found: {name}", status_code=404)
        _notify_and_audit(session, guild_id, name, f"dashboard:delete character {name}")
        return _template(
            request,
            "characters.html",
            _guild_context(request, session, "characters", "Character deleted", selected_guild_id=guild_id),
        )
    except DashboardManageError as exc:
        return _handle_error(request, session, "characters", exc)


@router.post("/shares", response_class=HTMLResponse)
async def create_share(request: Request):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        real_user = (form.get("real_user") or "").strip()
        user_id = _parse_int(form.get("shared_with_discord_user_id"), "shared_with_discord_user_id", required=True)
        if not real_user:
            raise DashboardManageError("Account is required")
        sso_model.add_account_user_share(guild_id, real_user, user_id, session.get("uid"))
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:share {real_user.lower()} with {user_id}")
        return _template(
            request,
            "shares.html",
            _guild_context(request, session, "shares", "Share added", selected_guild_id=guild_id),
        )
    except (
        DashboardManageError,
        sso_model.SSOAccountNotFoundError,
        sso_model.SSOAccountUserShareAlreadyExistsError,
    ) as exc:
        return _handle_error(request, session, "shares", exc)


@router.delete("/shares/{real_user}/{user_id}", response_class=HTMLResponse)
async def delete_share(request: Request, real_user: str, user_id: int):
    session = _get_authenticated_session(request)
    if not session:
        return Response(status_code=401)
    try:
        form = await _require_mutation(request, session)
        guild_id = _require_guild(session, form.get("guild_id"))
        sso_model.remove_account_user_share(guild_id, real_user, user_id)
        _notify_and_audit(session, guild_id, real_user.lower(), f"dashboard:unshare {real_user.lower()} from {user_id}")
        return _template(
            request,
            "shares.html",
            _guild_context(request, session, "shares", "Share removed", selected_guild_id=guild_id),
        )
    except (DashboardManageError, sso_model.SSOAccountUserShareNotFoundError) as exc:
        return _handle_error(request, session, "shares", exc)
