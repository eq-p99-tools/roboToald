import os

from roboToald import discord_client
from roboToald import config
from roboToald.api import server

if __name__ == '__main__':
    # Check if SSL/TLS certificates exist
    valid_tls = config.API_CERTFILE and config.API_KEYFILE and os.path.exists(config.API_CERTFILE) and os.path.exists(config.API_KEYFILE)
    if not(valid_tls):
        print("ERROR: TLS certificates not found or not configured.")
        print("To enable TLS, add ssl_certfile and ssl_keyfile paths in the [api] section of batphone.ini")
        exit(1)
    else:
        print(f"Starting RoboToald API server with TLS on https://{config.API_HOST}:{config.API_PORT}")
    
    # Start API server in background thread
    server.run_api_server(
        discord_client.DISCORD_CLIENT,
        certfile=config.API_CERTFILE,
        keyfile=config.API_KEYFILE,
        host=config.API_HOST,
        port=config.API_PORT
    )

    discord_client.DISCORD_CLIENT.run(config.DISCORD_TOKEN)
