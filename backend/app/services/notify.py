"""Outbound alerts (webhook). Dashboard alerts come from the violations table itself."""

import logging

from sqlalchemy.orm import Session

from app.integrations.http import request
from app.services import workspace_settings

log = logging.getLogger(__name__)

KIND_FLAGS = {"violation": "notify_violations", "failure": "notify_failures", "token": "notify_tokens"}


def send(db: Session, kind: str, text: str, **extra) -> bool:
    config = workspace_settings.get(db, "notifications")
    audit = workspace_settings.get(db, "audit")
    url = config.get("webhook_url")
    if not url or not audit.get("notifications_enabled", True) or not config.get(KIND_FLAGS.get(kind, ""), True):
        return False
    try:
        # `text` works for Slack/Discord-compatible webhooks; `content` for Discord; extra fields for custom receivers.
        request("POST", url, json={"text": f"ClipRelay: {text}", "content": f"ClipRelay: {text}", "kind": kind, **extra}, retries=2, timeout=10)
        return True
    except Exception as exc:  # notifications must never break the pipeline
        log.warning("webhook notification failed: %s", exc)
        return False
