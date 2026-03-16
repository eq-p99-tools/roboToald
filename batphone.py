import logging

from roboToald import discord_client
from roboToald import config
from roboToald.api import server
from roboToald.db import base

if __name__ == '__main__':
    _fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5.5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _handler = logging.StreamHandler()
    _handler.setFormatter(_fmt)
    logging.root.addHandler(_handler)
    logging.root.setLevel(logging.INFO)

    # Initialize database and run migrations
    print("Initializing database and running migrations...")
    base.initialize_database()

    from roboToald.db.models import sso as sso_model
    audit_archived, sessions_archived = sso_model.archive_old_records(
        retention_days=config.AUDIT_RETENTION_DAYS,
        archive_dir=config.AUDIT_ARCHIVE_DIR,
    )
    if audit_archived or sessions_archived:
        logging.getLogger(__name__).info(
            "Archived %d audit log entries and %d session records",
            audit_archived, sessions_archived,
        )

    # Start API server in background thread
    server.run_api_server(
        discord_client.DISCORD_CLIENT,
        certfile=config.API_CERTFILE,
        keyfile=config.API_KEYFILE,
        host=config.API_HOST,
        port=config.API_PORT
    )

    discord_client.DISCORD_CLIENT.run(config.DISCORD_TOKEN)
