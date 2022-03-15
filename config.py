import configparser

CONFIG_FILENAME = 'batphone.ini'

CONF = configparser.ConfigParser()
CONF.read(CONFIG_FILENAME)

DISCORD_TOKEN = CONF.get('discord', 'token')
BATPHONE_CHANNELS = list(
    map(lambda x: int(x.strip()),
        CONF.get('discord', 'channels').split(',')))

OUR_EMAIL = CONF.get('gmail', 'email')
TO_EMAIL = CONF.get('gmail', 'alert_email')
GMAIL_CREDENTIALS = CONF.get('gmail', 'credentials')

ALERT_WEBHOOK = ""