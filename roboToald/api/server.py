"""REST API server implementation for RoboToald."""
import logging
from typing import Union
import threading

from disnake.ext import commands
from fastapi import FastAPI, HTTPException, status, Request
from pydantic import BaseModel
import uvicorn

from roboToald import config
from roboToald.db.models import sso as sso_model
from roboToald.db import base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="RoboToald API", description="API for RoboToald SSO services")

# Expose a function to run the API server in a thread with injected discord_client


def run_api_server(discord_client, certfile, keyfile, host, port):
    """
    Start the API server in a background thread, injecting the Discord client.
    If certfile and keyfile are provided, the server will run with TLS.
    Otherwise, it will run without TLS (HTTP).
    """
    app.state.discord_client = discord_client

    # Check if both certfile and keyfile are provided
    use_ssl = certfile and keyfile
    def _run():
        # Common parameters for both HTTP and HTTPS
        uvicorn_params = {
            "app": "roboToald.api.server:app",
            "host": host,
            "port": port,
            "log_level": "info",
            "proxy_headers": True,
            "forwarded_allow_ips": config.FORWARDED_ALLOW_IPS
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


class SSOResponse(BaseModel):
    """Response model for successful SSO authentication."""
    real_user: str
    real_pass: str


class ErrorResponse(BaseModel):
    """Response model for error cases."""
    detail: str


class ListAccountsRequest(BaseModel):
    access_key: str


@app.get("/")
async def root(request: Request):
    """Root endpoint for API health check."""
    discord_client = request.app.state.discord_client if hasattr(request.app.state, 'discord_client') else None
    if discord_client is None:
        return {"status": "warning", "service": "RoboToald API", "message": "Discord client not initialized"}
    return {"status": "ok", "service": "RoboToald API", "message": "API server is running"}


@app.post("/auth", response_model=Union[SSOResponse, ErrorResponse], 
          status_code=status.HTTP_200_OK, 
          responses={
              401: {"model": ErrorResponse, "description": "Authentication failed"},
              #429: {"model": ErrorResponse, "description": "Too many failed attempts"}
          })
async def authenticate(auth_data: AuthRequest, request: Request):
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
    client_ip = request.client.host
    
    # Check if the IP is rate limited
    if sso_model.is_ip_rate_limited(client_ip):
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        # Return a 429 Too Many Requests status code
        # raise HTTPException(
        #     status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        #     detail="Too many failed attempts. Please try again later."
        # )
        raise_auth_failed()
    
    # Initialize audit log variables
    account_id = None
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
        account = sso_model.find_account_by_username(auth_data.username, access_key.guild_id)
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
            details=details
        )
        raise_auth_failed()

    if not account_id:
        # Log with specific reason but return generic error
        details = "Account not found"
        logger.warning(f"Authentication failed: {details}")
        # Create audit log entry before raising exception
        # sso_model.create_audit_log(
        #     username=auth_data.username,
        #     ip_address=client_ip,
        #     success=False,
        #     discord_user_id=discord_user_id,
        #     account_id=None,
        #     guild_id=access_key.guild_id,
        #     details=details
        # )
        raise_auth_failed()

    # Past this point we are guaranteed to have an account_id, guild_id, and discord_user_id
    discord_client = request.app.state.discord_client if hasattr(request.app.state, 'discord_client') else None

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
            details=details
        )
        raise_auth_failed()

    # Authentication successful - update account's last_login timestamp
    sso_model.update_last_login(account_id)

    # Create successful audit log entry
    sso_model.create_audit_log(
        username=real_username,
        ip_address=client_ip,
        success=True,
        discord_user_id=discord_user_id,
        account_id=account_id,
        guild_id=guild_id,
        details="Authentication successful" + f" via tag/alias {auth_data.username}" if auth_data.username != real_username else ""
    )

    # Return the real credentials
    return SSOResponse(
        real_user=account.real_user,
        real_pass=account.real_pass
    )


@app.post("/list_accounts", status_code=status.HTTP_200_OK,
          responses={
              401: {"model": ErrorResponse, "description": "Authentication failed"},
              #429: {"model": ErrorResponse, "description": "Too many failed attempts"}
          })
async def list_accounts(access_data: ListAccountsRequest, request: Request):
    """
    Returns a list of accounts, aliases, and tags that the user with the given access key has access to.
    """
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(',')[0].strip()
    else:
        client_ip = request.client.host

    # Check rate limiting
    if sso_model.is_ip_rate_limited(client_ip):
        # If rate limited, log and return 429
        logger.warning(f"Rate limit exceeded for IP: {client_ip}")
        # raise HTTPException(
        #     status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        #     detail="Too many failed attempts. Please try again later."
        # )
        raise_auth_failed()

    # Validate access key
    access_key = None
    discord_user_id = None
    guild_id = None

    try:
        access_key = sso_model.get_access_key_by_key(access_data.access_key)
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
        sso_model.create_audit_log(
            username="list_accounts",
            ip_address=client_ip,
            success=False,
            discord_user_id=None,
            account_id=None,
            guild_id=None,
            details=details
        )
        raise_auth_failed()

    # Past this point we are guaranteed to have a discord_user_id and guild_id
    discord_client = request.app.state.discord_client if hasattr(request.app.state, 'discord_client') else None

    # Get all accounts for this guild
    all_accounts = sso_model.list_accounts(guild_id)
    
    # Filter accounts based on user access
    accessible_accounts = user_has_access_to_accounts(discord_client, discord_user_id, guild_id, [account.id for account in all_accounts])
    
    ### Build v1 response data
    # Get all aliases for accessible accounts
    accessible_aliases = []
    for account in accessible_accounts:
        aliases = account.aliases
        accessible_aliases.extend(aliases)
    
    # Get all tags for accessible accounts
    accessible_tags = []
    for account in accessible_accounts:
        tags = account.tags
        accessible_tags.extend(tags)
    
    account_name_list = [account.real_user for account in accessible_accounts]
    alias_name_list = [alias.alias for alias in accessible_aliases]
    tag_name_list = [tag.tag for tag in accessible_tags]

    ### Build v2 response data
    account_tree = {
        account.real_user: {
            "aliases": [
                alias.alias for alias in account.aliases
            ],
            "tags": [
                tag.tag for tag in account.tags
            ]
        } for account in accessible_accounts
    }

    response = {
        # Old v1 call data
        "accounts": account_name_list + alias_name_list + tag_name_list,
        "count": len(account_name_list),

        # New v2 call data
        "account_tree": account_tree,
    }
    
    # Log successful request
    sso_model.create_audit_log(
        username="list_accounts",
        ip_address=client_ip,
        success=True,
        discord_user_id=discord_user_id,
        account_id=None,
        guild_id=guild_id,
        details="Successfully retrieved resources list"
    )
    
    return response


def raise_auth_failed():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication failed"
    )


def user_has_access_to_accounts(discord_client: commands.Bot, discord_user_id: int, guild_id: int, account_ids: list[int]) -> list[int]:
    """
    Check if a Discord user has access to a specific account.
    
    This function checks:
    1. If the user has any groups
    2. If the accounts belong to any of those groups
    """
    with base.get_session() as session:
        try:
            # Get all groups for the guild
            groups = session.query(sso_model.SSOAccountGroup).filter(
                sso_model.SSOAccountGroup.guild_id == guild_id
            ).all()

            # Check if discord is available
            try:
                guild = discord_client.get_guild(guild_id)
                verify_discord_role = True
            except Exception:
                verify_discord_role = False

            if verify_discord_role:
                member = guild.get_member(discord_user_id)
                role_ids = [role.id for role in member.roles]
            else:
                role_ids = []

            valid_accounts = set()
            for account_id in account_ids:
                # Check each group to see if the user has the role and if the account is in the group
                for group in groups:
                    # Check if the account is in this group
                    account_in_group = session.query(sso_model.account_group_mapping).filter(
                        sso_model.account_group_mapping.c.account_id == account_id,
                        sso_model.account_group_mapping.c.group_id == group.id
                    ).count() > 0
                
                    if account_in_group:
                        # Check if the user has the role_id associated with the group
                        if group.role_id in role_ids:
                            valid_accounts.add(sso_model.get_account_by_id(account_id))
                            continue
                    
            # Return the list of valid accounts
            return list(valid_accounts)
        except Exception as e:
            logger.error(f"Error checking user access: {str(e)}")
            return []
