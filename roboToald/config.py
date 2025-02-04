import configparser
import os
import random
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

POINTS_PER_MINUTE = CONF.getint(
    'ds', 'points_per_minute', fallback=3)
CONTESTED_MULTIPLIER = CONF.getint(
    'ds', 'contested_multiplier', fallback=3)
QUAKE_BONUS = CONF.getint(
    'ds', 'quake_bonus', fallback=150)

WAKEUP_AUDIOFILE = CONF.get(
    'wakeup', 'audiofile', fallback='wakeup.wav')

WAKEUP_CHANNELS = {}
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
        'ds_tod_channel': CONF.getint(
            f"guild.{guild}", 'ds_tod_channel', fallback=0),
        'ds_schedule_channel': CONF.getint(
            f"guild.{guild}", 'ds_schedule_channel', fallback=0),
        'ds_admin_role': CONF.getint(
            f"guild.{guild}", 'ds_admin_role', fallback=0),
        'wakeup_channels': CONF.get(
            f"guild.{guild}", 'wakeup_channels', fallback=None),
        'wakeup_exclusions': CONF.get(
            f"guild.{guild}", 'wakeup_exclusions', fallback=None),
    }
    if GUILD_SETTINGS[guild]['wakeup_channels']:
        for x in GUILD_SETTINGS[guild]['wakeup_channels'].split(','):
            text_channel, voice_channel = x.split(':')
            WAKEUP_CHANNELS[int(text_channel)] = int(voice_channel)
    if GUILD_SETTINGS[guild]['wakeup_exclusions']:
        GUILD_SETTINGS[guild]['wakeup_exclusions'] = [
            x.strip().lower()
            for x in GUILD_SETTINGS[guild]['wakeup_exclusions'].split(',')
        ]
    else:
        GUILD_SETTINGS[guild]['wakeup_exclusions'] = []
    # for item in CONF.items(f"guild.{guild}"):
    #     GUILD_SETTINGS[guild][item[0]] = item[1]


def get_member_role(guild_id: int) -> int:
    return GUILD_SETTINGS[guild_id].get('member_role')


def get_wakeup_exclusions(guild_id: int) -> List[str]:
    return GUILD_SETTINGS[guild_id].get('wakeup_exclusions', [])


def guilds_for_command(command_name: str) -> List[int]:
    guild_list = []
    for guild_entry in GUILD_SETTINGS:
        if GUILD_SETTINGS[guild_entry].get(f'enable_{command_name}', False):
            guild_list.append(guild_entry)
    return guild_list
