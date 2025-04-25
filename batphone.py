import os

from roboToald import discord_client
from roboToald import config
from roboToald.api import server

if __name__ == '__main__':
    # Check if SSL/TLS certificates exist
    use_tls = config.SSO_CERTFILE and config.SSO_KEYFILE
    if not(use_tls and os.path.exists(config.SSO_CERTFILE) and os.path.exists(config.SSO_KEYFILE)):
        print("WARNING: TLS certificates not found or not configured. Running in insecure mode.")
        print("To enable TLS, add ssl_certfile and ssl_keyfile paths in the [api] section of batphone.ini")
        print("Starting RoboToald API server on http://0.0.0.0:8000")
    else:
        print(f"Starting RoboToald API server with TLS on https://0.0.0.0:8443")
    
    # Start API server in background thread
    server.run_api_server(
        discord_client.DISCORD_CLIENT,
        host='0.0.0.0',
        port=8443 if use_tls else 8080,
        use_tls=use_tls,
        certfile=config.SSO_CERTFILE,
        keyfile=config.SSO_KEYFILE
    )

    discord_client.DISCORD_CLIENT.run(config.DISCORD_TOKEN)
