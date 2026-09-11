import requests

from src.config import NTFY_TOPIC

NTFY_URL = "https://ntfy.sh"


def send_notification(message: str) -> None:
    if not NTFY_TOPIC:
        raise ValueError(
            "Notifications aren't configured -- set NTFY_TOPIC in .env (see .env.example). "
            "Pick any topic name (treat it like a shared secret -- anyone who knows it can read "
            "your notifications) and subscribe to it in the ntfy app (iOS/Android)."
        )

    # unlike email-to-SMS, this is a plain synchronous HTTP call -- a delivery failure raises
    # right here, immediately, instead of arriving as a bounce email minutes later
    response = requests.post(f"{NTFY_URL}/{NTFY_TOPIC}", data=message.encode("utf-8"), timeout=10)
    response.raise_for_status()
