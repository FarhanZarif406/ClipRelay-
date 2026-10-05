"""Workspace settings stored as JSON rows in the `settings` table, so they can change at runtime from the UI."""

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS: dict[str, dict[str, Any]] = {
    "policy": {
        "automations_paused": False,
        "name": "Default publishing pipeline",
        "active_window_start": "00:00",
        "active_window_end": "23:59",
        "active_days": [0, 1, 2, 3, 4, 5, 6],  # Monday = 0
        "max_duration_sec": 60,
        "language_gate_enabled": False,
        "allowed_languages": ["hi", "ur"],
        "hourly_cap": 4,
        "random_delay_min_minutes": 0,
        "random_delay_max_minutes": 0,
        "timezone": "UTC",
        "unique_video_per_account": True,
        "default_interval_minutes": 60,
        "max_videos_per_run": 25,
    },
    "audit": {
        "check_hours": [1, 6, 12, 24],
        "auto_remove": True,
        "notifications_enabled": True,
    },
    "notifications": {
        "webhook_url": "",
        "email": "",
        "notify_violations": True,
        "notify_failures": True,
        "notify_tokens": True,
    },
    "onboarding": {"completed": False},
}


def get(db: Session, key: str) -> dict[str, Any]:
    row = db.get(AppSetting, key)
    value = deepcopy(DEFAULTS.get(key, {}))
    if row and isinstance(row.value, dict):
        value.update(row.value)
    return value


def update(db: Session, key: str, changes: dict[str, Any]) -> dict[str, Any]:
    value = get(db, key)
    value.update({k: v for k, v in changes.items() if v is not None})
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()
    return value
