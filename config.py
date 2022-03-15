import configparser

CONFIG_FILENAME = 'batphone.ini'

CONF = configparser.ConfigParser()
CONF.read(CONFIG_FILENAME)

DISCORD_TOKEN = CONF.get('discord', 'token')
BATPHONE_CHANNELS = list(
    map(lambda x: int(x.strip()),
        CONF.get('discord', 'channels').split(',')))

ALERT_WEBHOOK = CONF.get('squadcast', 'url')
