import re

import disnake

from roboToald.alert_services import squadcast

SQUADCAST_WEBHOOK_REGEX_US = re.compile(
    r"https?://api.squadcast.com/v2/incidents/api/\w+")
SQUADCAST_WEBHOOK_REGEX_EU = re.compile(
    r"https?://api.eu.squadcast.com/v2/incidents/api/\w+")
VALID_ALERT_PREFIXES = (
    SQUADCAST_WEBHOOK_REGEX_US,
    SQUADCAST_WEBHOOK_REGEX_EU,
)
SERVICE_MAP = {
    SQUADCAST_WEBHOOK_REGEX_US: squadcast.send_alert,
    SQUADCAST_WEBHOOK_REGEX_EU: squadcast.send_alert,
}


def validate_url(url):
    for prefix in VALID_ALERT_PREFIXES:
        if prefix.match(url):
            return True

    return False


def send_function(url):
    for service in SERVICE_MAP:
        if service.match(url):
            return SERVICE_MAP[service]


def send_alert(alert, message):
    service_func = send_function(alert.alert_url)
    # Strip non-printable characters
    message = ''.join(c for c in message if c.isprintable())
    if not service_func:
        print(f"Alert ID `{alert.id}` has invalid alert_url: "
              f"`{alert.alert_url}`")
        return
    print(f"Sending Alert via `{service_func.__module__.split('.')[-1]}` "
          f"to {alert.alert_url}: {message}")
    # Remove @everyone from the message if present
    message = message.removeprefix("@everyone").strip()
    service_func(message[:12], message, webhook=alert.alert_url)
    alert.increment_counter()


async def send_and_split(
        inter: disnake.ApplicationCommandInteraction, long_message: str):
    # Messages can only be 2000 chars so break it up if necessary
    if len(long_message) < 2000:
        await inter.send(
            content=long_message,
            allowed_mentions=disnake.AllowedMentions(users=False)
        )
    else:
        messages = split_message(long_message)
        for message in messages:
            await inter.send(
                content=message,
                allowed_mentions=disnake.AllowedMentions(users=False)
            )


def split_message(long_message: str):
    messages = []
    message_builder = ""
    for line in long_message.splitlines():
        if len(message_builder) + len(line) > 2000:
            messages.append(message_builder)
            message_builder = ""
        message_builder += f"{line}\n"
    if message_builder:
        messages.append(message_builder)

    return messages
