"""Workspace settings stored as JSON rows in the `settings` table, so they can change at runtime from the UI."""

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS: dict[str, dict[str, Any]] = {
    "notifications": {
        "webhook_url": "",
        "email": "",
        "notify_failures": True,
        "notify_tokens": True,
    },
    "onboarding": {"completed": False},
}


def get(db: Session, key: str) -> dict[str, Any]:
    row = db.get(AppSetting, key)
    value = deepcopy(DEFAULTS.get(key, {}))
    if row and isinstance(row.value, dict):
        # Keys that no longer exist (old schedule rules, for example) are ignored, not echoed back.
        value.update({k: v for k, v in row.value.items() if k in value or key not in DEFAULTS})
    return value


def update(db: Session, key: str, changes: dict[str, Any]) -> dict[str, Any]:
    value = get(db, key)
    value.update({k: v for k, v in changes.items() if v is not None and (k in value or key not in DEFAULTS)})
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()
    return value
