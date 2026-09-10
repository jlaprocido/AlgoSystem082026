import smtplib
from email.mime.text import MIMEText

from src.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD, NOTIFY_PHONE_NUMBER, NOTIFY_CARRIER

# free email-to-SMS gateways -- reliability/format support varies by carrier and can change
# without notice; this is fine for a personal low-volume bot, not something to depend on
# for anything time-critical
CARRIER_GATEWAYS = {
    "att": "txt.att.net",
    "verizon": "vtext.com",
    "tmobile": "tmomail.net",
}


def send_sms(message: str) -> None:
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and NOTIFY_PHONE_NUMBER):
        raise ValueError(
            "Notifications aren't configured -- set GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and "
            "NOTIFY_PHONE_NUMBER in .env (see .env.example)."
        )

    gateway = CARRIER_GATEWAYS[NOTIFY_CARRIER]
    to_address = f"{NOTIFY_PHONE_NUMBER}@{gateway}"

    # no Subject line on purpose -- most gateways just prepend it to the body, eating into
    # the ~160 character SMS budget for no benefit
    msg = MIMEText(message)
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_address

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [to_address], msg.as_string())
