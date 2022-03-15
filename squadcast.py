import requests

import config


def send_alert(title, message):
    requests.post(config.ALERT_WEBHOOK, json={
        "message": title,
        "description": message,
        "status": "trigger",
    })
