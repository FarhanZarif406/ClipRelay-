"""Email alerts over SMTP. Settings come from the credential store (Settings → Notifications) or .env."""

import smtplib
import ssl
from email.message import EmailMessage

from app.services import credentials


def config() -> dict[str, str]:
    return {key.split(".", 1)[1]: credentials.get(key) for key in credentials.groups()["smtp"]}


def configured() -> bool:
    c = config()
    return bool(c["host"] and c["from_address"])


def _connect(c: dict[str, str]) -> smtplib.SMTP:
    port = int(c.get("port") or 587)
    security = (c.get("security") or "starttls").lower()
    if security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(c["host"], port, timeout=15, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(c["host"], port, timeout=15)
        if security == "starttls":
            server.starttls(context=ssl.create_default_context())
    if c.get("username"):
        server.login(c["username"], c.get("password", ""))
    return server


def check(c: dict[str, str]) -> None:
    """Connect and authenticate without sending anything."""
    server = _connect(c)
    try:
        server.noop()
    finally:
        server.quit()


def send(to: list[str], subject: str, body: str) -> None:
    c = config()
    if not configured():
        raise RuntimeError("Email isn't configured — add SMTP settings in Settings → Notifications")
    msg = EmailMessage()
    msg["From"] = c["from_address"]
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    server = _connect(c)
    try:
        server.send_message(msg)
    finally:
        server.quit()
