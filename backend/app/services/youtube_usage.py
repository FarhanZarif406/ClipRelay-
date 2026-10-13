"""How much of the YouTube Data API's daily quota ClipRelay itself has spent.

Calls are counted in memory and added to the stored total from places that already hold a database
session (the scheduler tick, the Integrations page), so a lookup in the middle of another write never
waits on the database. Google resets the quota at midnight Pacific time.
"""

import threading
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models import AppSetting, utcnow

KEY = "youtube_usage"
DAILY_QUOTA = 10_000

_lock = threading.Lock()
_pending = {"units": 0, "video_calls": 0, "last_ok_at": None}


def quota_day() -> str:
    try:
        return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    except ZoneInfoNotFoundError:  # pragma: no cover - no time zone data on the machine
        return utcnow().date().isoformat()


def note(resource: str, ok: bool) -> None:
    """One Data API call. Every call ClipRelay makes (channels, videos, the test) costs one unit."""
    with _lock:
        _pending["units"] += 1
        if resource == "videos":
            _pending["video_calls"] += 1
        if ok:
            _pending["last_ok_at"] = utcnow().isoformat()


def flush(db: Session) -> dict:
    """Add what was counted since the last flush to the stored total, and return today's figures."""
    with _lock:
        taken = dict(_pending)
        _pending.update(units=0, video_calls=0, last_ok_at=None)
    row = db.get(AppSetting, KEY)
    value = dict(row.value) if row and isinstance(row.value, dict) else {}
    today = quota_day()
    if value.get("day") != today:
        value = {"day": today, "units": 0, "video_calls": 0, "last_ok_at": value.get("last_ok_at")}
    if taken["units"] or taken["last_ok_at"]:
        value["units"] = int(value.get("units", 0)) + taken["units"]
        value["video_calls"] = int(value.get("video_calls", 0)) + taken["video_calls"]
        value["last_ok_at"] = taken["last_ok_at"] or value.get("last_ok_at")
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=KEY, value=value))
        db.flush()
    return {"units_today": int(value.get("units", 0)), "video_calls_today": int(value.get("video_calls", 0)), "last_ok_at": value.get("last_ok_at"), "daily_quota": DAILY_QUOTA}
