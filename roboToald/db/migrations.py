"""Database migration utilities for RoboToald."""
import os
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def get_alembic_config():
    """Get Alembic configuration."""
    project_root = Path(__file__).parent.parent.parent.absolute()
    alembic_cfg = Config(os.path.join(project_root, "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(project_root, "migrations"),
    )
    return alembic_cfg


def upgrade_database():
    """Upgrade database schema to latest version."""
    logger.info("Checking for database schema updates...")
    alembic_cfg = get_alembic_config()
    command.upgrade(alembic_cfg, "head")
    logger.info("Database schema is up to date.")


def stamp_database(revision="head"):
    """Stamp the database with a revision without running migrations.

    Used to mark a database (created by create_all or pre-Alembic) as
    being at a specific revision so that future upgrade calls start from
    the correct point.
    """
    logger.info("Stamping database at revision '%s'...", revision)
    alembic_cfg = get_alembic_config()
    command.stamp(alembic_cfg, revision)
    logger.info("Database stamped successfully.")


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
