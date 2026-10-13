"""Outbound alerts: webhook and email."""

import logging

from sqlalchemy.orm import Session

from app.integrations.http import request
from app.services import mailer, workspace_settings

log = logging.getLogger(__name__)

KIND_FLAGS = {"failure": "notify_failures", "token": "notify_tokens"}
SUBJECTS = {"failure": "Job failed", "token": "A key needs attention"}


def recipients(config: dict) -> list[str]:
    return [r.strip() for r in (config.get("email") or "").replace(";", ",").split(",") if r.strip()]


def send(db: Session, kind: str, text: str, **extra) -> bool:
    """Send an alert to every configured channel. Never raises — notifications must not break the pipeline."""
    config = workspace_settings.get(db, "notifications")
    if not config.get(KIND_FLAGS.get(kind, ""), True):
        return False
    sent = False
    url = config.get("webhook_url")
    if url:
        try:
            # `text` works for Slack/Discord-compatible webhooks; `content` for Discord; extra fields for custom receivers.
            request("POST", url, json={"text": f"ClipRelay: {text}", "content": f"ClipRelay: {text}", "kind": kind, **extra}, retries=2, timeout=10)
            sent = True
        except Exception as exc:
            log.warning("webhook notification failed: %s", exc)
    to = recipients(config)
    if to and mailer.configured():
        try:
            mailer.send(to, f"ClipRelay: {SUBJECTS.get(kind, 'Alert')}", f"{text}\n\n— ClipRelay")
            sent = True
        except Exception as exc:
            log.warning("email notification failed: %s", exc)
    return sent
