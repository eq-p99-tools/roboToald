import re

from roboToald.alert_services import squadcast

SQUADCAST_WEBHOOK_REGEX = re.compile(
    r"https?://api.squadcast.com/v2/incidents/api/\w+")
VALID_ALERT_PREFIXES = (
    SQUADCAST_WEBHOOK_REGEX,
)
SERVICE_MAP = {
    SQUADCAST_WEBHOOK_REGEX: squadcast.send_alert,
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
    if not service_func:
        print(f"Alert ID `{alert.id}` has invalid alert_url: `{alert.alert_url}`")
        return
    print(f"Sending Alert via `{service_func.__module__.split('.')[-1]}` to {alert.alert_url}")
    service_func("BATPHONE", message, webhook=alert.alert_url)
    alert.increment_counter()
