"""Admin dashboard for SSO monitoring."""

import datetime
import hashlib
import hmac
import logging
import time
from pathlib import Path

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
_USE_SECURE_COOKIE = bool(config.API_CERTFILE and config.API_KEYFILE)


def _sign(payload: str) -> str:
    return hmac.new(
        config.ENCRYPTION_KEY.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def _make_cookie_value(token: str) -> str:
    """Build a timestamped, signed cookie: ``<timestamp>:<hmac>``."""
    ts = str(int(time.time()))
    sig = _sign(f"{token}|{ts}")
    return f"{ts}:{sig}"


def _is_authenticated(request: Request) -> bool:
    if not config.ADMIN_DASHBOARD_TOKEN:
        return False
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie or ":" not in cookie:
        return False
    ts_str, sig = cookie.split(":", 1)
    try:
        issued_at = int(ts_str)
    except ValueError:
        return False
    if time.time() - issued_at > COOKIE_MAX_AGE:
        return False
    expected = _sign(f"{config.ADMIN_DASHBOARD_TOKEN}|{ts_str}")
    return hmac.compare_digest(sig, expected)


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


def _sso_guild_ids(filter_guild_id: int | None = None) -> list[int]:
    """Return the SSO-enabled guild IDs, optionally filtered to one."""
    ids = [
        gid for gid in config.TEST_GUILDS
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
    if not config.ADMIN_DASHBOARD_TOKEN:
        return HTMLResponse(
            "<h1>Dashboard disabled</h1><p>Set admin_dashboard_token in batphone.ini</p>",
            status_code=503,
        )
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    token = form.get("token", "")

    if not config.ADMIN_DASHBOARD_TOKEN:
        return RedirectResponse("/admin/login?error=Dashboard+disabled", status_code=303)

    if not hmac.compare_digest(str(token), config.ADMIN_DASHBOARD_TOKEN):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid token"},
            status_code=401,
        )

    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _make_cookie_value(config.ADMIN_DASHBOARD_TOKEN),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_USE_SECURE_COOKIE,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/admin/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# -- Main dashboard -----------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/admin/login", status_code=303)

    discord_client = getattr(request.app.state, "discord_client", None)
    guilds = []
    for gid in config.TEST_GUILDS:
        if config.GUILD_SETTINGS.get(gid, {}).get("enable_sso"):
            guilds.append({"id": gid, "name": _resolve_guild_name(discord_client, gid)})

    return templates.TemplateResponse(request, "dashboard.html", {"guilds": guilds})


# -- HTMX partial endpoints --------------------------------------------------


@router.get("/partials/overview", response_class=HTMLResponse)
async def partial_overview(request: Request):
    if not _is_authenticated(request):
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(filter_gid)

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

    all_connections = ws_manager.get_connections_summary()
    if filter_gid:
        all_connections = [c for c in all_connections if c["guild_id"] == filter_gid]

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
    if not _is_authenticated(request):
        return Response(status_code=401)

    filter_gid = _parse_guild_filter(request)
    connections = ws_manager.get_connections_summary()
    if filter_gid:
        connections = [c for c in connections if c["guild_id"] == filter_gid]

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
    })


@router.get("/partials/sessions", response_class=HTMLResponse)
async def partial_sessions(request: Request):
    if not _is_authenticated(request):
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    guild_ids = _sso_guild_ids(filter_gid)

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
                "user_name": _resolve_discord_name(discord_client, gid, s.discord_user_id),
                "klass": character.klass.value if character and character.klass else "",
                "park": (character.park_location or "") if character else "",
                "first_seen": s.first_seen.strftime("%H:%M:%S"),
                "last_seen": s.last_seen.strftime("%H:%M:%S"),
                "duration": f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m",
            })

    all_sessions.sort(key=lambda s: s["last_seen"], reverse=True)
    return templates.TemplateResponse(request, "partials/sessions.html", {
        "sessions": all_sessions,
    })


@router.get("/partials/audit_log", response_class=HTMLResponse)
async def partial_audit_log(request: Request):
    if not _is_authenticated(request):
        return Response(status_code=401)

    discord_client = getattr(request.app.state, "discord_client", None)
    filter_gid = _parse_guild_filter(request)
    logs = sso_model.get_audit_logs(limit=50, guild_id=filter_gid)
    entries = []
    for log in logs:
        ip = log.ip_address or ""
        entries.append({
            "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
            "username": log.username,
            "ip_flag": sso_model.ip_country_flag(ip) if ip else "",
            "ip_address": sso_model.hash_ip(ip) if ip else "",
            "success": log.success,
            "user_name": (
                _resolve_discord_name(discord_client, log.guild_id, log.discord_user_id)
                if log.discord_user_id and log.guild_id else ""
            ),
            "details": log.details or "",
        })

    return templates.TemplateResponse(request, "partials/audit_log.html", {
        "entries": entries,
    })


@router.get("/partials/rate_limited", response_class=HTMLResponse)
async def partial_rate_limited(request: Request):
    if not _is_authenticated(request):
        return Response(status_code=401)

    rate_limited = sso_model.get_rate_limited_ips(
        config.RATE_LIMIT_MAX_ATTEMPTS, config.RATE_LIMIT_WINDOW_MINUTES
    )
    hashed = [
        (sso_model.ip_country_flag(ip), sso_model.hash_ip(ip), count)
        for ip, count in rate_limited
    ]

    return templates.TemplateResponse(request, "partials/rate_limited.html", {
        "rate_limited": hashed,
    })
