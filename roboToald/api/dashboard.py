"""Admin dashboard for SSO monitoring."""

import base64
import datetime
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from roboToald import config
from roboToald.db.models import sso as sso_model
from roboToald.api.websocket import manager as ws_manager

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/admin", tags=["admin"])

COOKIE_NAME = "admin_session"
COOKIE_MAX_AGE = 86400
STATE_COOKIE_NAME = "oauth_state"
STATE_COOKIE_MAX_AGE = 300
_USE_SECURE_COOKIE = bool(config.DASHBOARD_BASE_URL and config.DASHBOARD_BASE_URL.startswith("https://"))

DISCORD_AUTHORIZE_URL = "https://discord.com/api/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"


def _oauth_redirect_uri() -> str:
    return f"{config.DASHBOARD_BASE_URL.rstrip('/')}/admin/callback"


def _hmac_sign(data: bytes) -> str:
    return hmac.new(
        config.ENCRYPTION_KEY.encode(), data, hashlib.sha256
    ).hexdigest()


def _make_session_cookie(session: dict) -> str:
    """Encode a session dict as ``base64json.hmac``."""
    payload = base64.urlsafe_b64encode(json.dumps(session).encode()).decode()
    sig = _hmac_sign(payload.encode())
    return f"{payload}.{sig}"


def _get_session(request: Request) -> dict | None:
    """Decode and verify the session cookie. Returns the session dict or None."""
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie or "." not in cookie:
        return None
    payload, sig = cookie.rsplit(".", 1)
    expected = _hmac_sign(payload.encode())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        session = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None
    if time.time() - session.get("iat", 0) > COOKIE_MAX_AGE:
        return None
    return session


def _is_authenticated(request: Request) -> bool:
    return _get_session(request) is not None


def _dashboard_enabled() -> bool:
    return bool(config.DISCORD_OAUTH_CLIENT_ID and config.DISCORD_OAUTH_CLIENT_SECRET and config.DASHBOARD_BASE_URL)


def _resolve_discord_name(discord_client, guild_id: int, discord_user_id: int) -> str:
    if not discord_client:
        return str(discord_user_id)
    guild = discord_client.get_guild(guild_id)
    if not guild:
        return str(discord_user_id)
    member = guild.get_member(discord_user_id)
    return member.display_name if member else str(discord_user_id)


def _resolve_guild_name(discord_client, guild_id: int) -> str:
    if not discord_client:
        return str(guild_id)
    guild = discord_client.get_guild(guild_id)
    return guild.name if guild else str(guild_id)


def _sso_guild_ids(
    session_guilds: list[int],
    filter_guild_id: int | None = None,
) -> list[int]:
    """Return the SSO-enabled guild IDs scoped to the session's authorized guilds."""
    ids = [
        gid for gid in session_guilds
        if config.GUILD_SETTINGS.get(gid, {}).get("enable_sso")
    ]
    if filter_guild_id and filter_guild_id in ids:
        return [filter_guild_id]
    return ids


def _parse_guild_filter(request: Request) -> int | None:
    raw = request.query_params.get("guild_id")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return None


# -- Auth routes --------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if not _dashboard_enabled():
        return HTMLResponse(
            "<h1>Dashboard disabled</h1>"
            "<p>Set discord_oauth_client_id, discord_oauth_client_secret, "
            "and dashboard_base_url in batphone.ini</p>",
            status_code=503,
        )
    if _is_authenticated(request):
        return RedirectResponse("/admin", status_code=303)

    state = secrets.token_urlsafe(32)
    params = urllib.parse.urlencode({
        "client_id": config.DISCORD_OAUTH_CLIENT_ID,
        "redirect_uri": _oauth_redirect_uri(),
        "response_type": "code",
        "scope": "identify",
        "state": state,
    })
    authorize_url = f"{DISCORD_AUTHORIZE_URL}?{params}"
    response = templates.TemplateResponse(request, "login.html", {
        "error": error,
        "authorize_url": authorize_url,
    })
    response.set_cookie(
        STATE_COOKIE_NAME, state,
        max_age=STATE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_USE_SECURE_COOKIE,
    )
    return response


@router.get("/callback")
async def oauth_callback(request: Request, code: str = "", error: str = "", state: str = ""):
    if error or not code:
        return RedirectResponse("/admin/login?error=Discord+auth+cancelled", status_code=303)

    if not _dashboard_enabled():
        return RedirectResponse("/admin/login?error=Dashboard+disabled", status_code=303)

    expected_state = request.cookies.get(STATE_COOKIE_NAME, "")
    if not expected_state or not hmac.compare_digest(state, expected_state):
        return RedirectResponse("/admin/login?error=Invalid+state+parameter", status_code=303)

    # Exchange code for access token
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(DISCORD_TOKEN_URL, data={
            "client_id": config.DISCORD_OAUTH_CLIENT_ID,
            "client_secret": config.DISCORD_OAUTH_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _oauth_redirect_uri(),
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})

        if token_resp.status_code != 200:
            logger.warning("Discord token exchange failed: %s", token_resp.text)
            return RedirectResponse("/admin/login?error=Token+exchange+failed", status_code=303)

        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return RedirectResponse("/admin/login?error=No+access+token", status_code=303)

        # Fetch Discord user identity
        user_resp = await client.get(DISCORD_USER_URL, headers={
            "Authorization": f"Bearer {access_token}",
        })

    if user_resp.status_code != 200:
        logger.warning("Discord /users/@me failed: %s", user_resp.text)
        return RedirectResponse("/admin/login?error=Failed+to+get+user+info", status_code=303)

    user_data = user_resp.json()
    discord_user_id = int(user_data["id"])
    display_name = user_data.get("global_name") or user_data.get("username", "Unknown")
    avatar = user_data.get("avatar", "")

    # Check which SSO-enabled guilds this user is admin for
    is_super = discord_user_id in config.DASHBOARD_SUPER_ADMINS
    discord_bot = getattr(request.app.state, "discord_client", None)
    authorized_guilds: list[int] = []

    for gid in config.TEST_GUILDS:
        settings = config.GUILD_SETTINGS.get(gid, {})
        if not settings.get("enable_sso"):
            continue
        if is_super:
            authorized_guilds.append(gid)
            continue
        admin_roles = settings.get("sso_admin_roles", [])
        if not discord_bot:
            continue
        guild = discord_bot.get_guild(gid)
        if not guild:
            continue
        member = guild.get_member(discord_user_id)
        if not member:
            continue
        member_role_ids = {r.id for r in member.roles}
        if member_role_ids & set(admin_roles):
            authorized_guilds.append(gid)

    if not authorized_guilds:
        return templates.TemplateResponse(request, "login.html", {
            "error": "You do not have SSO admin access in any guild.",
            "authorize_url": "",
        }, status_code=403)

    session = {
        "uid": discord_user_id,
        "name": display_name,
        "avatar": avatar,
        "guilds": authorized_guilds,
        "iat": int(time.time()),
    }
    if is_super:
        session["super"] = True
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _make_session_cookie(session),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_USE_SECURE_COOKIE,
    )
    response.delete_cookie(STATE_COOKIE_NAME)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# -- Main dashboard -----------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    session = _get_session(request)
    if not session:
        return RedirectResponse("/admin/login", status_code=303)

    discord_client = getattr(request.app.state, "discord_client", None)
    guilds = []
    for gid in session.get("guilds", []):
        if config.GUILD_SETTINGS.get(gid, {}).get("enable_sso"):
            guilds.append({"id": gid, "name": _resolve_guild_name(discord_client, gid)})

    return templates.TemplateResponse(request, "dashboard.html", {
        "guilds": guilds,
        "user_name": session.get("name", ""),
    })


# -- HTMX partial endpoints --------------------------------------------------


@router.get("/partials/overview", response_class=HTMLResponse)
async def partial_overview(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(session["guilds"], filter_gid)

    guild_stats = []
    total_accounts = 0
    total_characters = 0
    total_groups = 0

    for gid in guild_ids:
        accounts = sso_model.list_accounts(gid)
        groups = sso_model.list_account_groups(gid)
        char_count = sum(len(a.characters) for a in accounts)
        guild_stats.append({
            "name": _resolve_guild_name(discord_client, gid),
            "accounts": len(accounts),
            "characters": char_count,
            "groups": len(groups),
        })
        total_accounts += len(accounts)
        total_characters += char_count
        total_groups += len(groups)

    allowed = set(guild_ids)
    all_connections = [c for c in ws_manager.get_connections_summary() if c["guild_id"] in allowed]

    active_session_count = 0
    for gid in guild_ids:
        active_session_count += len(sso_model.get_active_characters(gid))

    return templates.TemplateResponse(request, "partials/overview.html", {
        "guild_stats": guild_stats,
        "total_accounts": total_accounts,
        "total_characters": total_characters,
        "total_groups": total_groups,
        "ws_client_count": len(all_connections),
        "active_session_count": active_session_count,
    })


@router.get("/partials/connections", response_class=HTMLResponse)
async def partial_connections(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    filter_gid = _parse_guild_filter(request)
    allowed = set(_sso_guild_ids(session["guilds"], filter_gid))
    connections = [c for c in ws_manager.get_connections_summary() if c["guild_id"] in allowed]

    now = datetime.datetime.now()
    for conn in connections:
        conn["connected_at_iso"] = conn["connected_at"].astimezone().isoformat()
        delta = now - conn["connected_at"]
        minutes = int(delta.total_seconds() // 60)
        if minutes < 60:
            conn["uptime"] = f"{minutes}m"
        else:
            conn["uptime"] = f"{minutes // 60}h {minutes % 60}m"

    return templates.TemplateResponse(request, "partials/connections.html", {
        "connections": connections,
        "is_super": session.get("super", False),
    })


@router.get("/partials/sessions", response_class=HTMLResponse)
async def partial_sessions(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(session["guilds"], filter_gid)

    now = datetime.datetime.now()
    threshold = now - datetime.timedelta(seconds=config.SSO_INACTIVITY_SECONDS)
    all_sessions = []

    for gid in guild_ids:
        sessions = sso_model.get_sessions_in_range(gid, threshold, now)
        for s in sessions:
            duration = s.last_seen - s.first_seen
            minutes = int(duration.total_seconds() // 60)
            character = None
            for c in (s.account.characters if s.account else []):
                if c.name == s.character_name:
                    character = c
                    break
            all_sessions.append({
                "guild_name": _resolve_guild_name(discord_client, gid),
                "character_name": s.character_name,
                "account_name": s.account.real_user if s.account else "?",
                "discord_user_id": s.discord_user_id,
                "user_name": _resolve_discord_name(discord_client, gid, s.discord_user_id),
                "klass": character.klass.value if character and character.klass else "",
                "park": (character.park_location or "") if character else "",
                "first_seen": s.first_seen.strftime("%H:%M:%S"),
                "last_seen": s.last_seen.strftime("%H:%M:%S"),
                "duration": f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m",
            })

    all_sessions.sort(key=lambda s: (s["character_name"], s["account_name"]))
    return templates.TemplateResponse(request, "partials/sessions.html", {
        "sessions": all_sessions,
    })


def _format_audit_entries(logs, discord_client) -> list[dict]:
    """Format audit log ORM objects into template-friendly dicts."""
    entries = []
    for log in logs:
        ip = log.ip_address or ""
        entries.append({
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
            "username": log.username,
            "ip_cc": sso_model.ip_country_code(ip) if ip else "",
            "ip_address": sso_model.hash_ip(ip) if ip else "",
            "success": log.success,
            "discord_user_id": log.discord_user_id,
            "user_name": (
                _resolve_discord_name(discord_client, log.guild_id, log.discord_user_id)
                if log.discord_user_id and log.guild_id else ""
            ),
            "details": log.details or "",
            "client_version": log.client_version or "",
        })
    return entries


@router.get("/partials/audit_log", response_class=HTMLResponse)
async def partial_audit_log(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(session["guilds"], filter_gid)
    allowed = set(guild_ids)
    logs = sso_model.get_audit_logs(limit=50, guild_id=filter_gid)
    logs = [log for log in logs if log.guild_id in allowed]

    return templates.TemplateResponse(request, "partials/audit_log.html", {
        "entries": _format_audit_entries(logs, discord_client),
        "is_super": session.get("super", False),
    })


@router.get("/partials/audit_modal", response_class=HTMLResponse)
async def partial_audit_modal(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    account = request.query_params.get("account")
    user_id_raw = request.query_params.get("user_id")
    guild_ids = _sso_guild_ids(session["guilds"])
    allowed = set(guild_ids)

    if user_id_raw:
        try:
            uid = int(user_id_raw)
        except ValueError:
            return Response(status_code=400)
        logs = sso_model.get_audit_logs_for_user_id(uid, limit=50)
        logs = [log for log in logs if log.guild_id in allowed]
    elif account:
        logs = sso_model.get_audit_logs(limit=50, username=account)
        logs = [log for log in logs if log.guild_id in allowed]
    else:
        return Response(status_code=400)

    return templates.TemplateResponse(request, "partials/audit_modal.html", {
        "entries": _format_audit_entries(logs, discord_client),
        "is_super": session.get("super", False),
    })


def _resolve_role_name(discord_client, guild_id: int, role_id: int) -> str:
    if not discord_client:
        return str(role_id)
    guild = discord_client.get_guild(guild_id)
    if not guild:
        return str(role_id)
    role = guild.get_role(role_id)
    return role.name if role else str(role_id)


@router.get("/partials/accounts", response_class=HTMLResponse)
async def partial_accounts(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(session["guilds"], filter_gid)

    guilds = []
    for gid in guild_ids:
        guild_name = _resolve_guild_name(discord_client, gid)
        accounts = sso_model.list_accounts(gid)
        rows = []
        for acct in accounts:
            chars = sorted(
                [
                    {
                        "name": c.name,
                        "klass": c.klass.value if c.klass else "",
                        "level": c.level,
                    }
                    for c in acct.characters
                ],
                key=lambda c: c["name"],
            )
            groups = sorted(
                [
                    {
                        "name": g.group_name,
                        "role": _resolve_role_name(discord_client, gid, g.role_id),
                    }
                    for g in acct.groups
                ],
                key=lambda g: g["name"],
            )
            aliases = sorted(a.alias for a in acct.aliases)
            tags = sorted({t.tag for t in acct.tags})
            last_login_ts = ""
            if acct.last_login and acct.last_login != datetime.datetime.min:
                last_login_ts = acct.last_login.isoformat()
            rows.append({
                "account": acct.real_user,
                "characters": chars,
                "groups": groups,
                "aliases": aliases,
                "tags": tags,
                "last_login_iso": last_login_ts,
                "last_login_by": acct.last_login_by or "",
            })
        rows.sort(key=lambda r: r["account"])
        guilds.append({"id": gid, "name": guild_name, "accounts": rows})

    return templates.TemplateResponse(request, "partials/accounts.html", {
        "guilds": guilds,
    })


@router.get("/partials/rate_limited", response_class=HTMLResponse)
async def partial_rate_limited(request: Request):
    session = _get_session(request)
    if not session:
        return Response(status_code=401)

    is_super = session.get("super", False)
    rate_limited = sso_model.get_rate_limited_ips(
        config.RATE_LIMIT_MAX_ATTEMPTS, config.RATE_LIMIT_WINDOW_MINUTES
    )
    hashed = [
        (sso_model.ip_country_code(ip), sso_model.hash_ip(ip), count)
        for ip, count in rate_limited
    ]

    return templates.TemplateResponse(request, "partials/rate_limited.html", {
        "rate_limited": hashed,
        "is_super": is_super,
    })
