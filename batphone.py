from roboToald import discord_client
from roboToald import config

if __name__ == '__main__':
    discord_client.DISCORD_CLIENT.run(config.DISCORD_TOKEN)
