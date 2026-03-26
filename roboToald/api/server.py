"""REST API server implementation for RoboToald."""

import asyncio
import datetime
import json
import logging
from typing import Union
import threading

from disnake.ext import commands
from fastapi import BackgroundTasks, FastAPI, HTTPException, status, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import uvicorn

from roboToald import config
from roboToald.db.models import sso as sso_model
from roboToald.db import base
from roboToald.api.websocket import manager as ws_manager, ClientConnection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class _SuppressBareWsLifecycle(logging.Filter):
    """Drop uvicorn's generic 'connection open'/'connection closed' messages.

    Our application-level WebSocket logs include guild, user, and IP context,
    making these redundant.
    """

    _suppressed = frozenset({"connection open", "connection closed"})

    def filter(self, record):
        return record.getMessage() not in self._suppressed


logging.getLogger("uvicorn.error").addFilter(_SuppressBareWsLifecycle())


class _SuppressAdminPartials(logging.Filter):
    """Drop access-log lines for /admin/partials/ HTMX polling requests."""

    def filter(self, record):
        msg = record.getMessage()
        return "/admin/partials/" not in msg


logging.getLogger("uvicorn.access").addFilter(_SuppressAdminPartials())

# Create FastAPI app
app = FastAPI(title="RoboToald API", description="API for RoboToald SSO services")

# Mount the admin dashboard router
from roboToald.api.dashboard import router as dashboard_router  # noqa: E402

app.include_router(dashboard_router)

# Expose a function to run the API server in a thread with injected discord_client


@app.on_event("startup")
async def _on_startup():
    ws_manager.set_event_loop(asyncio.get_running_loop())
    uvicorn_logger = logging.getLogger("uvicorn.error")
    for name in ("roboToald", "roboToald.api"):
        lg = logging.getLogger(name)
        lg.handlers = uvicorn_logger.handlers
        lg.setLevel(uvicorn_logger.level)


def run_api_server(discord_client, certfile, keyfile, host, port):
    """
    Start the API server in a background thread, injecting the Discord client.
    If certfile and keyfile are provided, the server will run with TLS.
    Otherwise, it will run without TLS (HTTP).
    """
    app.state.discord_client = discord_client
    ws_manager.set_discord_client(discord_client)

    # Check if both certfile and keyfile are provided
    use_ssl = certfile and keyfile

    def _run():
        log_config = uvicorn.config.LOGGING_CONFIG
        ts_fmt = "%(asctime)s %(levelprefix)s %(message)s"
        log_config["formatters"]["default"]["fmt"] = ts_fmt
        log_config["formatters"]["access"]["fmt"] = (
            '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
        )
        uvicorn_params = {
            "app": "roboToald.api.server:app",
            "host": host,
            "port": port,
            "log_level": "info",
            "log_config": log_config,
            "proxy_headers": True,
            "forwarded_allow_ips": config.FORWARDED_ALLOW_IPS,
        }

        # Add SSL parameters if certificates are provided
        if use_ssl:
            logger.info(f"Starting API server with TLS on {host}:{port}")
            uvicorn_params["ssl_certfile"] = certfile
            uvicorn_params["ssl_keyfile"] = keyfile
        else:
            logger.warning(f"Starting API server WITHOUT TLS on {host}:{port} - THIS IS POSSIBLY INSECURE")

        # Run the server with the appropriate configuration
        uvicorn.run(**uvicorn_params)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    # Log the server start with appropriate protocol
    protocol = "https" if use_ssl else "http"
    logger.info(f"API server started in thread at {protocol}://{host}:{port}")
    return thread


# Define request and response models
class AuthRequest(BaseModel):
    """Request model for SSO authentication."""

    username: str
    password: str
    client_settings: dict | None = None


class SSOResponse(BaseModel):
    """Response model for successful SSO authentication."""

    real_user: str
    real_pass: str


class ErrorResponse(BaseModel):
    """Response model for error cases."""

    detail: str


class ListAccountsRequest(BaseModel):
    access_key: str


class UpdateLocationRequest(BaseModel):
    access_key: str
    character_name: str
    bind_location: str | None = None
    park_location: str | None = None
    level: int | None = None


class HeartbeatRequest(BaseModel):
    access_key: str
    character_name: str


@app.get("/")
async def root(request: Request):
    """Root endpoint for API health check."""
    discord_client = request.app.state.discord_client if hasattr(request.app.state, "discord_client") else None
    if discord_client is None:
        return {"status": "warning", "service": "RoboToald API", "message": "Discord client not initialized"}
    return {"status": "ok", "service": "RoboToald API", "message": "API server is running"}


@app.post(
    "/auth",
    response_model=Union[SSOResponse, ErrorResponse],
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Character not found"},
        401: {"model": ErrorResponse, "description": "Authentication failed"},
        410: {"model": ErrorResponse, "description": "Tag temporarily empty"},
        422: {"model": ErrorResponse, "description": "Client settings rejected"},
        # 429: {"model": ErrorResponse, "description": "Too many failed attempts"}
    },
)
async def authenticate(auth_data: AuthRequest, request: Request, background_tasks: BackgroundTasks):
    """
    Authenticate a user based on username and password.

    # Access the Discord client from app.state
    discord_client = request.app.state.discord_client if hasattr(request.app.state, 'discord_client') else None
    # You can now use discord_client in this route if needed

    The authentication process:
    1. Check if the client IP is rate limited
    2. Check the provided password is a valid access key, otherwise return access denied
    3. Find an account associated with the provided username, otherwise return access denied
    4. Check if the user has access to the requested account, otherwise return access denied
    5. Return the real credentials if authorized

    Note: For security reasons, all authentication failures return the same error code
    to avoid leaking information about what accounts exist in the system.

    Rate limiting:
    - IP addresses with more than some number of failed attempts in a rolling time period will be blocked
    """
    client_ip = _get_client_ip(request)
    client_ver = request.headers.get("X-Client-Version")

    # Check if the IP is rate limited
    if sso_model.is_ip_rate_limited(client_ip, config.RATE_LIMIT_MAX_ATTEMPTS, config.RATE_LIMIT_WINDOW_MINUTES):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise_auth_failed()

    # Initialize audit log variables
    account_id = None
    real_username = None
    guild_id = None
    discord_user_id = None

    # Find the discord_user_id associated with the provided password
    access_key = sso_model.get_access_key_by_key(auth_data.password)

    """
    If we have an access key, we can look up the account by the guild_id.
    If we don't have an access key, we'll log the failed attempt and continue.
    """
    if access_key:
        discord_user_id = access_key.discord_user_id
        guild_id = access_key.guild_id

        if sso_model.is_user_access_revoked(guild_id, discord_user_id):
            logger.warning(f"Authentication failed: Access revoked for user {discord_user_id}")
            sso_model.create_audit_log(
                username=auth_data.username,
                ip_address=client_ip,
                success=False,
                discord_user_id=discord_user_id,
                account_id=None,
                guild_id=guild_id,
                details="Access revoked",
                client_version=client_ver,
            )
            raise_auth_failed()

        discord_client = request.app.state.discord_client if hasattr(request.app.state, "discord_client") else None

        guild_settings = config.GUILD_SETTINGS.get(guild_id, {})
        min_ver = guild_settings.get("min_client_version")
        if min_ver:
            client_ver = request.headers.get("X-Client-Version", "0.0.0")
            if _parse_version(client_ver) < _parse_version(min_ver):
                update_msg = guild_settings.get("client_update_message") or (
                    f"Client update required (minimum version: {min_ver})"
                )
                logger.info(
                    "Rejecting /auth: client %s below minimum %s [account: %s, guild: %s]",
                    client_ver,
                    min_ver,
                    auth_data.username,
                    guild_id,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=update_msg,
                )

        user_role_ids = _get_user_role_ids(discord_client, guild_id, discord_user_id)
        settings_error = _validate_client_settings(auth_data.client_settings, guild_id, user_role_ids=user_role_ids)
        if settings_error:
            login_name = _resolve_display_name(discord_client, guild_id, discord_user_id)
            logger.info(
                "Rejecting /auth due to client settings: %s [account: %s, guild: %s, user: %s (%s)]",
                settings_error,
                auth_data.username,
                guild_id,
                discord_user_id,
                login_name or "unknown",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=settings_error,
            )

        try:
            account = sso_model.find_account_by_username(auth_data.username, access_key.guild_id, inactive_only=True)
        except sso_model.SSOTagTemporarilyEmptyError:
            raise_tag_temporarily_empty()
        if account:
            account_id = account.id
            real_username = account.real_user
    else:
        # Log failed authentication attempt
        details = "Invalid access key"
        logger.warning(f"Authentication failed: {details} [account: {auth_data.username}]")
        # Create audit log entry before raising exception
        sso_model.create_audit_log(
            username=auth_data.username,
            ip_address=client_ip,
            success=False,
            discord_user_id=None,
            account_id=None,
            guild_id=None,
            details=details,
            client_version=client_ver,
        )
        raise_auth_failed()

    if not account_id or not real_username:
        details = "Account not found"
        logger.warning(f"Authentication failed: {details}")
        # sso_model.create_audit_log(
        #     username=auth_data.username,
        #     ip_address=client_ip,
        #     success=False,
        #     discord_user_id=discord_user_id,
        #     account_id=None,
        #     guild_id=access_key.guild_id,
        #     details=details
        # )
        raise_invalid_character()

    # Past this point we are guaranteed to have an account_id, guild_id, and discord_user_id
    discord_client = request.app.state.discord_client if hasattr(request.app.state, "discord_client") else None

    # Check if the discord user has access to this account
    if not user_has_access_to_accounts(discord_client, discord_user_id, guild_id, [account_id]):
        # Log with specific reason but return generic error
        details = "Access denied"
        logger.warning(f"Authentication failed: {details} for user {discord_user_id}")
        # Create audit log entry before raising exception
        sso_model.create_audit_log(
            username=real_username,
            ip_address=client_ip,
            success=False,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details,
            client_version=client_ver,
        )
        raise_auth_failed()

    # Authentication successful - build audit detail
    login_name = _resolve_display_name(discord_client, guild_id, discord_user_id)
    input_name = auth_data.username.lower()
    if input_name == real_username:
        auth_detail = "Authentication successful (account name)"
    elif any(c.name.lower() == input_name for c in account.characters):
        auth_detail = f"Authentication successful via character {auth_data.username}"
    elif any(a.alias.lower() == input_name for a in account.aliases):
        auth_detail = f"Authentication successful via alias {auth_data.username}"
    else:
        auth_detail = f"Authentication successful via tag {auth_data.username}"

    def _post_auth_write():
        sso_model.update_last_login_and_log(
            account_id=account_id,
            login_by=login_name,
            username=real_username,
            ip_address=client_ip,
            discord_user_id=discord_user_id,
            guild_id=guild_id,
            details=auth_detail,
            client_version=client_ver,
        )
        ws_manager.notify_guild(guild_id)

    background_tasks.add_task(_post_auth_write)

    # Return the real credentials immediately; writes happen in background
    return SSOResponse(real_user=account.real_user, real_pass=account.real_pass)


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For from trusted proxies."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host


def _check_auth(request: Request, access_key_in: str, query_type: str | None):
    client_ip = _get_client_ip(request)
    client_ver = request.headers.get("X-Client-Version")

    # Check rate limiting
    if sso_model.is_ip_rate_limited(client_ip, config.RATE_LIMIT_MAX_ATTEMPTS, config.RATE_LIMIT_WINDOW_MINUTES):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        raise_auth_failed()

    # Validate access key
    access_key = None
    discord_user_id = None
    guild_id = None

    try:
        access_key = sso_model.get_access_key_by_key(access_key_in)
        if access_key:
            discord_user_id = access_key.discord_user_id
            guild_id = access_key.guild_id
    except Exception as e:
        logger.error(f"Error validating access key: {e}")
        raise_auth_failed()

    if not access_key:
        # Log failed authentication attempt
        details = "Invalid access key"
        logger.warning(f"Authentication failed: {details}")
        # Create audit log entry before raising exception
        if query_type:
            sso_model.create_audit_log(
                username=query_type,
                ip_address=client_ip,
                success=False,
                discord_user_id=None,
                account_id=None,
                guild_id=None,
                details=details,
                client_version=client_ver,
            )
        raise_auth_failed()

    # Past this point we are guaranteed to have a discord_user_id and guild_id
    if sso_model.is_user_access_revoked(guild_id, discord_user_id):
        logger.warning(f"Authentication failed: Access revoked for user {discord_user_id}")
        if query_type:
            sso_model.create_audit_log(
                username=query_type,
                ip_address=client_ip,
                success=False,
                discord_user_id=discord_user_id,
                account_id=None,
                guild_id=guild_id,
                details="Access revoked",
                client_version=client_ver,
            )
        raise_auth_failed()

    discord_client = request.app.state.discord_client if hasattr(request.app.state, "discord_client") else None
    return discord_client, discord_user_id, guild_id, client_ip, client_ver


@app.post(
    "/list_accounts",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Authentication failed"},
        # 429: {"model": ErrorResponse, "description": "Too many failed attempts"}
    },
)
async def list_accounts(access_data: ListAccountsRequest, request: Request):
    """
    Returns a list of accounts, aliases, and tags that the user with the given access key has access to.
    """
    discord_client, discord_user_id, guild_id, client_ip, client_ver = _check_auth(request, access_data.access_key, "list_accounts")

    # Get all accounts for this guild
    all_accounts = sso_model.list_accounts(guild_id)

    # Filter accounts based on user access
    accessible_accounts = user_has_access_to_accounts(
        discord_client, discord_user_id, guild_id, [account.id for account in all_accounts]
    )

    ### Build v2/v3 response data
    active_characters = sso_model.get_active_characters(guild_id)
    account_tree = {
        account.real_user: {
            "aliases": [alias.alias for alias in account.aliases],
            "tags": [tag.tag for tag in account.tags],
            # Added in v3
            "characters": {
                character.name: {
                    "class": character.klass,
                    "bind": character.bind_location,
                    "park": character.park_location,
                    "level": character.level,
                }
                for character in account.characters
            },
            # Added in v3
            "last_login": (
                account.last_login.astimezone(datetime.timezone.utc).isoformat()
                if account.last_login and account.last_login.year > 1
                else None
            ),
            "last_login_by": account.last_login_by,
            "active_character": active_characters.get(account.id),
        }
        for account in accessible_accounts
    }

    dynamic_tag_zones, dynamic_tag_classes = sso_model.get_dynamic_tags()
    response = {
        # v2 call data
        "account_tree": account_tree,
        # v3 call data
        "dynamic_tag_zones": list(dynamic_tag_zones.keys()),
        "dynamic_tag_classes": list(dynamic_tag_classes.keys()),
    }

    # Log successful request
    sso_model.create_audit_log(
        username="list_accounts",
        ip_address=client_ip,
        success=True,
        discord_user_id=discord_user_id,
        account_id=None,
        guild_id=guild_id,
        details="Successfully retrieved resources list",
        client_version=client_ver,
    )

    return response


@app.post(
    "/update_location",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Character not found"},
        401: {"model": ErrorResponse, "description": "Authentication failed"},
    },
)
async def update_location(location_data: UpdateLocationRequest, request: Request):
    """
    Update the bind/park location of a character assuming the access key has access to it.
    """
    discord_client, discord_user_id, guild_id, client_ip, client_ver = _check_auth(
        request, location_data.access_key, "update_location"
    )

    # Get the account for the character
    account = sso_model.find_account_by_character(guild_id, location_data.character_name)
    if not account:
        logger.warning(f"Character {location_data.character_name} not found")
        raise_invalid_character()

    # Check if the discord user has access to this account
    if not user_has_access_to_accounts(discord_client, discord_user_id, guild_id, [account.id]):
        # Log with specific reason but return generic error
        details = "Access denied"
        logger.warning(
            f"Authentication failed: {details} for user {discord_user_id} to character {location_data.character_name}"
        )
        # Create audit log entry before raising exception
        sso_model.create_audit_log(
            username=location_data.character_name,
            ip_address=client_ip,
            success=False,
            discord_user_id=discord_user_id,
            account_id=account.id,
            guild_id=guild_id,
            details=details,
            client_version=client_ver,
        )
        raise_auth_failed()

    # Authentication successful - update account's last_login timestamp because why not, it's still online
    login_name = _resolve_display_name(discord_client, guild_id, discord_user_id)
    sso_model.update_last_login(account.id, login_by=login_name)

    # Update location
    sso_model.update_account_character(
        guild_id=guild_id,
        name=location_data.character_name,
        bind_location=location_data.bind_location,
        park_location=location_data.park_location,
        level=location_data.level,
    )

    # Log successful request
    sso_model.create_audit_log(
        username=location_data.character_name,
        ip_address=client_ip,
        success=True,
        discord_user_id=discord_user_id,
        account_id=account.id,
        guild_id=guild_id,
        details=f"Successfully updated location: "
        f"bind = {location_data.bind_location is not None}, "
        f"park = {location_data.park_location is not None}, "
        f"level = {location_data.level}",
        client_version=client_ver,
    )

    return {"status": "success"}


@app.post(
    "/heartbeat",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse, "description": "Character not found"},
        401: {"model": ErrorResponse, "description": "Authentication failed"},
    },
)
async def heartbeat(heartbeat_data: HeartbeatRequest, request: Request):
    """
    Authenticates and updates last_login for the character's account.
    """
    discord_client, discord_user_id, guild_id, _, _ = _check_auth(request, heartbeat_data.access_key, None)

    account = sso_model.find_account_by_character(guild_id, heartbeat_data.character_name)
    if not account:
        raise_invalid_character()

    if not user_has_access_to_accounts(discord_client, discord_user_id, guild_id, [account.id]):
        raise_auth_failed()

    login_name = _resolve_display_name(discord_client, guild_id, discord_user_id)
    sso_model.update_last_login(account.id, login_by=login_name)
    sso_model.record_heartbeat_session(guild_id, account.id, heartbeat_data.character_name, discord_user_id)

    return {"status": "success"}


WS_PING_INTERVAL = 30


@app.websocket("/ws/accounts")
async def websocket_accounts(websocket: WebSocket):
    """WebSocket endpoint for real-time account data streaming.

    Protocol:
        1. Client sends: {"type": "auth", "access_key": "..."}
        2. Server validates and sends full_state
        3. Server pushes delta messages on changes
        4. Client may send heartbeat / update_location messages
    """
    await websocket.accept()

    # --- Phase 1: authenticate ---
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=15)
        msg = json.loads(raw)
    except (asyncio.TimeoutError, json.JSONDecodeError, WebSocketDisconnect):
        await _ws_close(websocket, 4001, "Auth timeout or bad payload")
        return

    if msg.get("type") != "auth" or not msg.get("access_key"):
        await _ws_close(websocket, 4002, "Expected auth message")
        return

    client_host = websocket.client.host if websocket.client else "unknown"

    if sso_model.is_ip_rate_limited(client_host, config.RATE_LIMIT_MAX_ATTEMPTS, config.RATE_LIMIT_WINDOW_MINUTES):
        logger.warning("WebSocket rejected: rate limit exceeded for IP %s", client_host)
        await _ws_close(websocket, 4003, "Invalid access key")
        return

    ws_client_ver = msg.get("client_version")

    access_key = sso_model.get_access_key_by_key(msg["access_key"])
    if not access_key:
        logger.warning("WebSocket auth failed: invalid access key from %s", client_host)
        sso_model.create_audit_log(
            username="ws_auth",
            ip_address=client_host,
            success=False,
            discord_user_id=None,
            account_id=None,
            guild_id=None,
            details="Invalid access key (WebSocket)",
            client_version=ws_client_ver,
        )
        await _ws_close(websocket, 4003, "Invalid access key")
        return

    guild_id = access_key.guild_id
    discord_user_id = access_key.discord_user_id

    # --- Wait for Discord cache to be ready ---
    discord_client = app.state.discord_client if hasattr(app.state, "discord_client") else None
    if discord_client and not discord_client.is_ready():
        ws_label_early = f"guild={guild_id} user={discord_user_id} ip={client_host}"
        logger.info("WebSocket waiting for Discord to be ready: %s", ws_label_early)
        for _ in range(30):
            await asyncio.sleep(1)
            if discord_client.is_ready():
                break
        else:
            await _ws_close(websocket, 4004, "Server still initializing, try again shortly")
            return

    # --- Resolve friendly guild/user names for logging ---
    if discord_client:
        guild = discord_client.get_guild(guild_id)
        member = guild.get_member(discord_user_id) if guild else None
        guild_label = f"{guild_id} ({guild.name})" if guild else str(guild_id)
        user_label = f"{discord_user_id} ({member.display_name})" if member else str(discord_user_id)
    else:
        guild_label = str(guild_id)
        user_label = str(discord_user_id)
    client_ver = msg.get("client_version", "unknown")
    ws_label = f"guild={guild_label} user={user_label} v={client_ver} ip={client_host}"

    # --- Check revocation ---
    if sso_model.is_user_access_revoked(guild_id, discord_user_id):
        logger.warning("WebSocket rejected: access revoked: %s", ws_label)
        await _ws_close(websocket, 4003, "Access revoked")
        return

    # --- Check client version against guild minimum ---
    guild_settings = config.GUILD_SETTINGS.get(guild_id, {})
    min_ver = guild_settings.get("min_client_version")
    if min_ver:
        client_ver = msg.get("client_version", "0.0.0")
        if _parse_version(client_ver) < _parse_version(min_ver):
            update_msg = guild_settings.get("client_update_message") or (
                f"Client update required (minimum version: {min_ver})"
            )
            logger.info("Rejecting outdated client %s (minimum %s): %s", client_ver, min_ver, ws_label)
            await _ws_close(websocket, 4010, update_msg)
            return

    # --- Check client settings against guild requirements ---
    user_role_ids = _get_user_role_ids(discord_client, guild_id, discord_user_id)
    settings_error = _validate_client_settings(msg.get("client_settings"), guild_id, user_role_ids=user_role_ids)
    if settings_error:
        logger.info("Rejecting client due to settings: %s: %s", settings_error, ws_label)
        await _ws_close(websocket, 4011, settings_error)
        return

    # --- Phase 2: send full state ---
    account_tree = await ws_manager.build_full_state(guild_id, discord_user_id)
    dynamic_tag_zones, dynamic_tag_classes = sso_model.get_dynamic_tags()

    conn = ClientConnection(
        websocket=websocket,
        guild_id=guild_id,
        discord_user_id=discord_user_id,
        last_sent_state=account_tree,
        client_version=msg.get("client_version", "unknown"),
        client_ip=client_host,
    )
    ws_manager.register(conn)

    try:
        await websocket.send_json(
            {
                "type": "full_state",
                "account_tree": account_tree,
                "count": len(account_tree),
                "dynamic_tag_zones": list(dynamic_tag_zones.keys()),
                "dynamic_tag_classes": list(dynamic_tag_classes.keys()),
            }
        )
        logger.info("WebSocket connected: %s (%d accounts)", ws_label, len(account_tree))

        # --- Phase 3: listen for client messages + send keepalive pings ---
        await _ws_message_loop(websocket, conn)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", ws_label)
    except Exception:
        logger.exception("WebSocket error: %s", ws_label)
    finally:
        ws_manager.unregister(websocket)


async def _ws_message_loop(websocket: WebSocket, conn: ClientConnection):
    """Process inbound messages and send periodic pings."""
    ping_task = asyncio.create_task(_ws_ping_loop(websocket))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "heartbeat":
                await _ws_handle_heartbeat(conn, msg)

            elif msg_type == "update_location":
                await _ws_handle_update_location(conn, msg)
    finally:
        ping_task.cancel()
        try:
            await ping_task
        except asyncio.CancelledError:
            pass


async def _ws_handle_heartbeat(conn: ClientConnection, msg: dict):
    """Process a heartbeat message: update last_login, then push delta."""
    character_name = msg.get("character_name")
    if not character_name:
        return
    account = sso_model.find_account_by_character(conn.guild_id, character_name)
    if not account:
        return

    if not user_has_access_to_accounts(ws_manager._discord_client, conn.discord_user_id, conn.guild_id, [account.id]):
        return

    login_name = _resolve_display_name(ws_manager._discord_client, conn.guild_id, conn.discord_user_id)
    sso_model.update_last_login(account.id, login_by=login_name)
    sso_model.record_heartbeat_session(conn.guild_id, account.id, character_name, conn.discord_user_id)
    sso_model.expire_other_sessions(conn.guild_id, conn.discord_user_id, account.id)
    await ws_manager.notify_guild_async(conn.guild_id)


async def _ws_handle_update_location(conn: ClientConnection, msg: dict):
    """Process an update_location message: update character, then push delta."""
    character_name = msg.get("character_name")
    if not character_name:
        return
    account = sso_model.find_account_by_character(conn.guild_id, character_name)
    if not account:
        return

    if not user_has_access_to_accounts(ws_manager._discord_client, conn.discord_user_id, conn.guild_id, [account.id]):
        return

    login_name = _resolve_display_name(ws_manager._discord_client, conn.guild_id, conn.discord_user_id)
    sso_model.update_last_login(account.id, login_by=login_name)
    sso_model.record_heartbeat_session(conn.guild_id, account.id, character_name, conn.discord_user_id)
    sso_model.expire_other_sessions(conn.guild_id, conn.discord_user_id, account.id)
    sso_model.update_account_character(
        guild_id=conn.guild_id,
        name=character_name,
        bind_location=msg.get("bind_location"),
        park_location=msg.get("park_location"),
        level=msg.get("level"),
    )
    await ws_manager.notify_guild_async(conn.guild_id)


async def _ws_ping_loop(websocket: WebSocket):
    """Send application-level pings at a regular interval."""
    try:
        while True:
            await asyncio.sleep(WS_PING_INTERVAL)
            await websocket.send_json({"type": "ping"})
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass


def _parse_version(ver: str) -> tuple:
    """Parse a semver-ish string into a comparable tuple of ints.

    Pre-release suffixes (e.g. '1.2.0-rc3') sort below the release
    they're attached to, which is the standard semver expectation.
    A version with any pre-release or build suffix is considered older
    than the same base version without one.
    """
    base, _, pre = ver.partition("-")
    parts = []
    for seg in base.split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    # No suffix → release (1), any suffix → pre-release (0)
    parts.append(0 if pre else 1)
    return tuple(parts)


async def _ws_close(websocket: WebSocket, code: int, reason: str):
    """Send an error message and close the WebSocket."""
    try:
        await websocket.send_json({"type": "error", "detail": reason})
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


def _resolve_display_name(discord_client, guild_id: int, discord_user_id: int) -> str | None:
    """Resolve a Discord user ID to their guild display name."""
    if not discord_client:
        return None
    guild = discord_client.get_guild(guild_id)
    if not guild:
        return None
    member = guild.get_member(discord_user_id)
    return member.display_name if member else None


def _get_user_role_ids(discord_client, guild_id: int, discord_user_id: int) -> list[int]:
    """Return the Discord role IDs for a guild member, or an empty list."""
    if not discord_client:
        return []
    guild = discord_client.get_guild(guild_id)
    member = guild.get_member(discord_user_id) if guild else None
    if member is None:
        return []
    return [role.id for role in member.roles]


def _validate_client_settings(
    client_settings: dict | None,
    guild_id: int,
    user_role_ids: list[int] | None = None,
) -> str | None:
    """Return an error message if client settings fail guild requirements, else None.

    Older clients that omit client_settings entirely are allowed through for
    backward compatibility. Enforcement only applies when the field is present
    but contains a failing value. Use min_client_version to close this loophole.
    """
    if not client_settings:
        return None

    guild_settings = config.GUILD_SETTINGS.get(guild_id, {})

    if guild_settings.get("require_log") and "log_enabled" in client_settings and not client_settings["log_enabled"]:
        return (
            "Logging must be enabled in eqclient.ini (Log=TRUE in [Defaults] section). "
            "The login proxy attempted to set this automatically but the file may be read-only."
        )

    if guild_settings.get("block_rustle") and "rustle_present" in client_settings and client_settings["rustle_present"]:
        exempt_roles = guild_settings.get("block_rustle_exempt_roles", [])
        if not exempt_roles or not user_role_ids or not any(r in exempt_roles for r in user_role_ids):
            return (
                "A UI skin with modified inventory slots was detected in your "
                "EverQuest uifiles directory. Please remove it to continue."
            )

    return None


def raise_auth_failed():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed")


def raise_invalid_character():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Character not found")


def raise_tag_temporarily_empty():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE, detail="Tag is empty (possibly temporarily, due to inactivity requirements)"
    )


def user_has_access_to_accounts(
    discord_client: commands.Bot, discord_user_id: int, guild_id: int, account_ids: list[int]
) -> list[sso_model.SSOAccount]:
    """Return the subset of *account_ids* accessible to the Discord user.

    Uses a single bulk query instead of per-account/per-group lookups.
    """
    import sqlalchemy.orm

    role_ids = _get_user_role_ids(discord_client, guild_id, discord_user_id)
    if not role_ids or not account_ids:
        return []

    with base.get_session() as session:
        try:
            accessible_ids = {
                row[0]
                for row in session.query(sso_model.account_group_mapping.c.account_id)
                .join(
                    sso_model.SSOAccountGroup,
                    sso_model.account_group_mapping.c.group_id == sso_model.SSOAccountGroup.id,
                )
                .filter(
                    sso_model.account_group_mapping.c.account_id.in_(account_ids),
                    sso_model.SSOAccountGroup.guild_id == guild_id,
                    sso_model.SSOAccountGroup.role_id.in_(role_ids),
                )
                .all()
            }
            if not accessible_ids:
                return []
            accounts = (
                session.query(sso_model.SSOAccount)
                .options(
                    sqlalchemy.orm.joinedload(sso_model.SSOAccount.groups),
                    sqlalchemy.orm.joinedload(sso_model.SSOAccount.characters),
                    sqlalchemy.orm.joinedload(sso_model.SSOAccount.tags),
                    sqlalchemy.orm.joinedload(sso_model.SSOAccount.aliases),
                )
                .filter(sso_model.SSOAccount.id.in_(accessible_ids))
                .all()
            )
            session.expunge_all()
            return accounts
        except Exception as e:
            logger.error(f"Error checking user access: {e}")
            return []
