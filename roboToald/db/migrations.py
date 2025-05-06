"""Database migration utilities for RoboToald."""
import os
import logging
from alembic import command
from alembic.config import Config
from pathlib import Path

logger = logging.getLogger(__name__)

def get_alembic_config():
    """Get Alembic configuration."""
    # Get the project root directory
    project_root = Path(__file__).parent.parent.parent.absolute()
    
    # Create Alembic config
    alembic_cfg = Config(os.path.join(project_root, "alembic.ini"))
    
    # Set the script location
    alembic_cfg.set_main_option("script_location", os.path.join(project_root, "migrations"))
    
    return alembic_cfg

def upgrade_database():
    """Upgrade database schema to latest version."""
    try:
        logger.info("Checking for database schema updates...")
        alembic_cfg = get_alembic_config()
        command.upgrade(alembic_cfg, "head")
        logger.info("Database schema is up to date.")
    except Exception as e:
        logger.error(f"Error upgrading database schema: {e}")
        # Don't raise the exception - we want the application to continue
        # even if migrations fail, as the schema might already be up to date

def create_migration(message):
    """Create a new migration with the given message."""
    try:
        logger.info(f"Creating new migration: {message}")
        alembic_cfg = get_alembic_config()
        command.revision(alembic_cfg, autogenerate=True, message=message)
        logger.info("Migration created successfully.")
    except Exception as e:
        logger.error(f"Error creating migration: {e}")
        raise
