import configparser

CONFIG_FILENAME = 'batphone.ini'

CONF = configparser.ConfigParser()
CONF.read(CONFIG_FILENAME)

DISCORD_TOKEN = CONF.get('discord', 'token')
TEST_GUILDS = list(
    map(lambda x: int(x.strip()),
        CONF.get('discord', 'test_guilds').split(',')))
