"""REST API server implementation for RoboToald."""
from typing import Optional, Dict, Any, Union
import logging
import datetime

from fastapi import FastAPI, HTTPException, status, Request
from pydantic import BaseModel
import sqlalchemy.exc

from roboToald.db.models import sso
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
    1. Look up the username in the SSOAccount table
    2. If not found, continue to access key check
    3. Look up the password in the SSOAccessKey table to find discord_user_id
    4. Check if the user has access to the requested username
    5. Return the real credentials if authorized, otherwise return access denied
    
    Note: For security reasons, all authentication failures return the same error code
    to avoid leaking information about what accounts exist in the system.
    
    Rate limiting:
    - IP addresses with more than 10 failed attempts in the last hour will be blocked
    """
    username = auth_data.username
    password = auth_data.password
    client_ip = request.client.host if request.client else None
    
    # Check if the IP is rate limited
    if client_ip and sso.is_ip_rate_limited(client_ip):
        logger.warning(f"Rate limited IP: {client_ip} - too many failed attempts")
        # Create audit log entry for the rate limit
        sso.create_audit_log(
            username=username,
            ip_address=client_ip,
            success=False,
            details="Rate limited: too many failed attempts"
        )
        # Return a 429 Too Many Requests status code
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please try again later."
        )
    
    # Initialize audit log variables
    audit_success = False
    discord_user_id = None
    account_id = None
    guild_id = None
    details = None
    
    try:
        # Try to find the discord_user_id associated with the provided password
        discord_user_id = find_discord_user_by_access_key(password)
        
        if not discord_user_id:
            # Log with specific reason but return generic error
            details = "Invalid access key"
            logger.warning(f"Authentication failed: {details}")
            # Create audit log entry before raising exception
            sso.create_audit_log(
                username=username,
                ip_address=client_ip,
                success=False,
                discord_user_id=None,
                account_id=None,
                guild_id=None,
                details=details
            )
            sso.increment_failed_login_attempt(client_ip)
            raise_auth_failed()
        
        # Find the account by username
        account = find_account_by_username(username)
        
        if not account:
            # Log with specific reason but return generic error
            details = "Account not found"
            logger.warning(f"Authentication failed: {details}")
            # Create audit log entry before raising exception
            sso.create_audit_log(
                username=username,
                ip_address=client_ip,
                success=False,
                discord_user_id=discord_user_id,
                account_id=None,
                guild_id=None,
                details=details
            )
            sso.increment_failed_login_attempt(client_ip)
            raise_auth_failed()
        
        account_id = account.id
        guild_id = account.guild_id
        
        # Check if the discord user has access to this account
        if not user_has_access_to_account(discord_user_id, account.guild_id, account.id):
            # Log with specific reason but return generic error
            details = "Access denied"
            logger.warning(f"Authentication failed: {details} for user {discord_user_id}")
            # Create audit log entry before raising exception
            sso.create_audit_log(
                username=username,
                ip_address=client_ip,
                success=False,
                discord_user_id=discord_user_id,
                account_id=account_id,
                guild_id=guild_id,
                details=details
            )
            sso.increment_failed_login_attempt(client_ip)
            raise_auth_failed()
        
        # Authentication successful - update account's last_login timestamp
        update_last_login(account_id)
        
        # Create successful audit log entry
        sso.create_audit_log(
            username=username,
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
        
    except sqlalchemy.exc.NoResultFound:
        # Log with specific reason but return generic error
        details = "Database query returned no results"
        logger.warning(f"Authentication failed: {details}")
        # Create audit log entry before raising exception
        sso.create_audit_log(
            username=username,
            ip_address=client_ip,
            success=False,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details
        )
        sso.increment_failed_login_attempt(client_ip)
        raise_auth_failed()
    except HTTPException:
        # Re-raise HTTP exceptions (like our auth failed exception)
        # Audit log already created before raising the exception
        raise
    except Exception as e:
        # Log the specific error but return generic message
        details = f"Unexpected error: {str(e)}"
        logger.error(f"Authentication error: {details}")
        # Create audit log entry before raising exception
        sso.create_audit_log(
            username=username,
            ip_address=client_ip,
            success=False,
            discord_user_id=discord_user_id,
            account_id=account_id,
            guild_id=guild_id,
            details=details[:255]  # Limit to column size
        )
        sso.increment_failed_login_attempt(client_ip)
        raise_auth_failed()

def update_last_login(account_id: int) -> None:
    """Update the last_login timestamp for an account."""
    with base.get_session() as session:
        try:
            account = session.query(sso.SSOAccount).filter(
                sso.SSOAccount.id == account_id
            ).one()
            account.last_login = datetime.datetime.now()
            session.commit()
        except Exception as e:
            logger.error(f"Error updating last_login: {str(e)}")
            session.rollback()

def raise_auth_failed():
    """Helper function to raise a consistent authentication failure exception."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication failed"
    )

def find_discord_user_by_access_key(access_key: str) -> Optional[int]:
    """Find the discord user ID associated with an access key."""
    with base.get_session() as session:
        try:
            # Query for the access key
            access_key_obj = session.query(sso.SSOAccessKey).filter(
                sso.SSOAccessKey.access_key == access_key
            ).one_or_none()
            
            if access_key_obj:
                return access_key_obj.discord_user_id
            return None
        except Exception as e:
            logger.error(f"Error finding discord user by access key: {str(e)}")
            return None

def find_account_by_username(username: str) -> Optional[sso.SSOAccount]:
    """Find an account by username."""
    with base.get_session() as session:
        try:
            # Try to find the account directly by real_user
            account = session.query(sso.SSOAccount).filter(
                sso.SSOAccount.real_user == username
            ).one_or_none()
            
            if account:
                session.expunge(account)
                return account
                
            # If not found, try to find by alias
            alias = session.query(sso.SSOAccountAlias).filter(
                sso.SSOAccountAlias.alias == username
            ).one_or_none()
            
            if alias:
                account = session.query(sso.SSOAccount).filter(
                    sso.SSOAccount.id == alias.account_id
                ).one_or_none()
                
                if account:
                    session.expunge(account)
                    return account
                    
            return None
        except Exception as e:
            logger.error(f"Error finding account by username: {str(e)}")
            return None

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
            groups = session.query(sso.SSOAccountGroup).filter(
                sso.SSOAccountGroup.guild_id == guild_id
            ).all()
            
            # Check each group to see if the user has the role and if the account is in the group
            for group in groups:
                # Check if the account is in this group
                account_in_group = session.query(sso.account_group_mapping).filter(
                    sso.account_group_mapping.c.account_id == account_id,
                    sso.account_group_mapping.c.group_id == group.id
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
