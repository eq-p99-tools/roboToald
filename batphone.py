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
    
    # Start API server in background thread
    server.run_api_server(
        discord_client.DISCORD_CLIENT,
        certfile=config.API_CERTFILE,
        keyfile=config.API_KEYFILE,
        host=config.API_HOST,
        port=config.API_PORT
    )

    discord_client.DISCORD_CLIENT.run(config.DISCORD_TOKEN)
