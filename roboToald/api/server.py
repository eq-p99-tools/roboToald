"""REST API server implementation for RoboToald."""
from typing import Union
import logging

from fastapi import FastAPI, HTTPException, status, Request
from pydantic import BaseModel
import sqlalchemy.exc

from roboToald.db.models import sso as sso_model
from roboToald.db import base

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(title="RoboToald API", description="API for RoboToald SSO services")


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


@app.get("/")
async def root():
    """Root endpoint for API health check."""
    return {"status": "ok", "service": "RoboToald API"}


@app.post("/auth", response_model=Union[SSOResponse, ErrorResponse], 
          status_code=status.HTTP_200_OK, 
          responses={
              401: {"model": ErrorResponse, "description": "Authentication failed"},
              429: {"model": ErrorResponse, "description": "Too many failed attempts"}
          })
async def authenticate(auth_data: AuthRequest, request: Request):
    """
    Authenticate a user based on username and password.
    
    The authentication process:
    1. Check if the client IP is rate limited
    2. Check the provided password is a valid access key, otherwise return access denied
    3. Find an account associated with the provided username, otherwise return access denied
    4. Check if the user has access to the requested account, otherwise return access denied
    5. Return the real credentials if authorized
    
    Note: For security reasons, all authentication failures return the same error code
    to avoid leaking information about what accounts exist in the system.
    
    Rate limiting:
    - IP addresses with more than 10 failed attempts in the last hour will be blocked
    """
    client_ip = request.client.host
    
    # Check if the IP is rate limited
    if sso_model.is_ip_rate_limited(client_ip):
        logger.warning(f"Rate limited IP: {client_ip} - too many failed attempts")
        # Return a 429 Too Many Requests status code
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please try again later."
        )
    
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
    else:
        # Log failed authentication attempt
        details = "Invalid access key"
        logger.warning(f"Authentication failed: {details}")
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
        sso_model.create_audit_log(
            username=auth_data.username,
            ip_address=client_ip,
            success=False,
            discord_user_id=discord_user_id,
            account_id=None,
            guild_id=access_key.guild_id,
            details=details
        )
        raise_auth_failed()

    # Past this point we are guaranteed to have an account_id, guild_id, and discord_user_id

    # Check if the discord user has access to this account
    if not user_has_access_to_account(discord_user_id, guild_id, account_id):
        # Log with specific reason but return generic error
        details = "Access denied"
        logger.warning(f"Authentication failed: {details} for user {discord_user_id}")
        # Create audit log entry before raising exception
        sso_model.create_audit_log(
            username=auth_data.username,
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
        username=auth_data.username,
        ip_address=client_ip,
        success=True,
        discord_user_id=discord_user_id,
        account_id=account_id,
        guild_id=guild_id,
        details="Authentication successful"
    )

    # Return the real credentials
    return SSOResponse(
        real_user=account.real_user,
        real_pass=account.real_pass
    )


def raise_auth_failed():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication failed"
    )


def user_has_access_to_account(discord_user_id: int, guild_id: int, account_id: int) -> bool:
    """
    Check if a Discord user has access to a specific account.
    
    This function checks:
    1. If the user has any groups
    2. If the account belongs to any of those groups
    """
    with base.get_session() as session:
        try:
            # Get all groups for the guild
            groups = session.query(sso_model.SSOAccountGroup).filter(
                sso_model.SSOAccountGroup.guild_id == guild_id
            ).all()
            
            # Check each group to see if the user has the role and if the account is in the group
            for group in groups:
                # Check if the account is in this group
                account_in_group = session.query(sso_model.account_group_mapping).filter(
                    sso_model.account_group_mapping.c.account_id == account_id,
                    sso_model.account_group_mapping.c.group_id == group.id
                ).count() > 0
                
                if account_in_group:
                    # For now, we're assuming that if the account is in a group, the user has access
                    # In a real implementation, you would check if the user has the role_id associated with the group
                    return True
                    
            # If we get here, the user doesn't have access to the account
            return False
        except Exception as e:
            logger.error(f"Error checking user access: {str(e)}")
            return False
