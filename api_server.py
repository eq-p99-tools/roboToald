"""
Standalone API server for RoboToald SSO authentication.
This server can be run independently from the Discord bot.
"""
import uvicorn
import os
from roboToald import config
from roboToald.api.server import app

if __name__ == "__main__":
    # Get SSL/TLS certificate settings from config
    ssl_keyfile = config.CONF.get('api', 'ssl_keyfile', fallback=None)
    ssl_certfile = config.CONF.get('api', 'ssl_certfile', fallback=None)
    
    # Check if SSL/TLS certificates exist
    if ssl_certfile and ssl_keyfile and os.path.exists(ssl_certfile) and os.path.exists(ssl_keyfile):
        print(f"Starting RoboToald API server with TLS on https://0.0.0.0:8443")
        uvicorn.run(
            app, 
            host="0.0.0.0", 
            port=8443, 
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile
        )
    else:
        print("WARNING: TLS certificates not found or not configured. Running in insecure mode.")
        print("To enable TLS, add ssl_certfile and ssl_keyfile paths in the [api] section of batphone.ini")
        print("Starting RoboToald API server on http://0.0.0.0:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000)
