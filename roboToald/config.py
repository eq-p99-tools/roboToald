import configparser
from typing import List

CONFIG_FILENAME = 'batphone.ini'

CONF = configparser.ConfigParser()
CONF.read(CONFIG_FILENAME)

DISCORD_TOKEN = CONF.get('discord', 'token')
TEST_GUILDS = []
for section in CONF.sections():
    if section.startswith("guild."):
        TEST_GUILDS.append(int(section.split('.')[-1]))

RT_ENDPOINT = CONF.get('raidtargets', 'endpoint')
SOON_THRESHOLD = CONF.getint(
    'raidtargets', 'soon_threshold',
    fallback=48 * 60 * 60)  # Default: 48 hours

GUILD_SETTINGS = {}
for guild in TEST_GUILDS:
    GUILD_SETTINGS[guild] = {
        'member_role': CONF.getint(
            f"guild.{guild}", 'member_role', fallback=0),
        'enable_random': CONF.getboolean(
            f"guild.{guild}", 'enable_random', fallback=True),
        'enable_timer': CONF.getboolean(
            f"guild.{guild}", 'enable_timer', fallback=True),
        'enable_batphone': CONF.getboolean(
            f"guild.{guild}", 'enable_batphone', fallback=False),
        'enable_raidtarget': CONF.getboolean(
            f"guild.{guild}", 'enable_raidtarget', fallback=False),
        'enable_ds': CONF.getboolean(
            f"guild.{guild}", 'enable_ds', fallback=False),
    }
    # for item in CONF.items(f"guild.{guild}"):
    #     GUILD_SETTINGS[guild][item[0]] = item[1]


def guilds_for_command(command_name: str) -> List[int]:
    guild_list = []
    for guild_entry in GUILD_SETTINGS:
        if GUILD_SETTINGS[guild_entry].get(f'enable_{command_name}', False):
            guild_list.append(guild_entry)
    return guild_list
