from roboToald import discord_client
from roboToald import config
from roboToald.api import server
from roboToald.db import base

if __name__ == '__main__':
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
