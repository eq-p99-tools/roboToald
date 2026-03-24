"""Raid database migration utilities."""

import os
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def get_raid_alembic_config(db_path: str):
    """Get Alembic configuration for a raid database at *db_path*."""
    project_root = Path(__file__).parent.parent.parent.absolute()
    alembic_cfg = Config(os.path.join(project_root, "alembic.ini"), ini_section="alembic:raid")
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(project_root, "raid_migrations"),
    )
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return alembic_cfg


def upgrade_raid_database(db_path: str):
    logger.info("Checking for raid database schema updates (%s)...", db_path)
    alembic_cfg = get_raid_alembic_config(db_path)
    command.upgrade(alembic_cfg, "head")
    logger.info("Raid database schema is up to date (%s).", db_path)


def stamp_raid_database(revision="head", db_path: str = "data/raids.db"):
    logger.info("Stamping raid database at revision '%s' (%s)...", revision, db_path)
    alembic_cfg = get_raid_alembic_config(db_path)
    command.stamp(alembic_cfg, revision)
    logger.info("Raid database stamped successfully (%s).", db_path)
