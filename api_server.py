"""
Standalone API server for RoboToald SSO authentication.
This server can be run independently from the Discord bot.
"""
import uvicorn

from roboToald.api.server import app

if __name__ == "__main__":
    print("Starting RoboToald API server on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
