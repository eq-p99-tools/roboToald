import requests

from roboToald import config


def send_alert(title, message, webhook=None):
    webhook = webhook or config.ALERT_WEBHOOK
    requests.post(webhook, json={
        "message": title,
        "description": message,
        "status": "trigger",
    })
