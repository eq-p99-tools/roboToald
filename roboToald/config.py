import configparser

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
        'member_role': CONF.getint(f"guild.{guild}", 'member_role', fallback=0)
    }
    # for item in CONF.items(f"guild.{guild}"):
    #     GUILD_SETTINGS[guild][item[0]] = item[1]
