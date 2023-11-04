from roboToald.discord_client.commands import cmd_random
from roboToald.discord_client.commands import cmd_batphone
from roboToald.discord_client.commands import cmd_timer
from roboToald.discord_client.base import DISCORD_CLIENT

@DISCORD_CLIENT.event
async def on_ready():
    print(f'Logged in as: {DISCORD_CLIENT.user.name}')
    await cmd_timer.load_timers()
