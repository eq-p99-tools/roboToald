import requests


def send_alert(title, message, webhook):
    requests.post(webhook, json={
        "message": title,
        "description": message,
        "status": "trigger",
    })
