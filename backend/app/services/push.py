"""YouTube push notifications: the public address the hub calls, the verify token, and today's count.

The address saved on the Integrations page wins over PUBLIC_BASE_URL from .env, so push can be pointed at a
tunnel or a new domain without touching the server. The verify token is sent with every subscribe request
and checked when the hub calls back; it is stored encrypted and never sent to the browser.
"""

import re
import secrets
import threading
import time
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import AppSetting, utcnow
from app.security import decrypt, encrypt

KEY = "push"
STATS_KEY = "push_stats"
TTL = 5.0
TOKEN_RE = re.compile(r"^[A-Za-z0-9._~-]{8,200}$")
LOCAL_HOSTS = (None, "localhost", "127.0.0.1", "0.0.0.0", "::1")

_lock = threading.Lock()
_cache: dict | None = None
_loaded_at = 0.0


class PushError(ValueError):
    pass


def bust() -> None:
    global _cache
    with _lock:
        _cache = None


def _read() -> dict:
    """The saved settings, read on a connection of their own: callers range from request handlers to the scheduler."""
    global _cache, _loaded_at
    cached = get_settings().environment != "test"
    with _lock:
        if cached and _cache is not None and time.monotonic() - _loaded_at < TTL:
            return _cache
    db = SessionLocal()
    try:
        row = db.get(AppSetting, KEY)
        value = dict(row.value) if row and isinstance(row.value, dict) else {}
    finally:
        db.close()
    with _lock:
        _cache, _loaded_at = value, time.monotonic()
    return value


def _value(db: Session, key: str = KEY) -> dict:
    row = db.get(AppSetting, key)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def _write(db: Session, value: dict, key: str = KEY) -> None:
    row = db.get(AppSetting, key)
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()
    bust()


def saved_base_url() -> str:
    return _read().get("public_base_url") or ""


def base_url() -> str:
    return (saved_base_url() or get_settings().public_base_url).rstrip("/")


def is_public(url: str) -> bool:
    """The hub can only reach a public HTTPS address."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname not in LOCAL_HOSTS


def verify_token() -> str:
    stored = _read().get("verify_token_enc")
    return (decrypt(stored) or "") if stored else ""


def ensure_token(db: Session) -> str:
    """The saved verify token; one is made the first time a channel is subscribed, so push works with no setup."""
    value = _value(db)
    token = (decrypt(value["verify_token_enc"]) or "") if value.get("verify_token_enc") else ""
    if not token:
        token = secrets.token_urlsafe(24)
        _write(db, {**value, "verify_token_enc": encrypt(token), "updated_at": utcnow().isoformat()})
    return token


def save(db: Session, *, public_base_url: str | None = None, token: str | None = None) -> bool:
    """Store the changes. Returns True when the callback address changed, so every channel must be subscribed again."""
    value = _value(db)
    before = base_url()
    if public_base_url is not None:
        address = public_base_url.strip().rstrip("/")
        if address:
            parsed = urlparse(address)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise PushError("That is not a valid URL.")
            if not is_public(address):
                raise PushError("The hub needs a public https:// address.")
        value["public_base_url"] = address
    if token is not None:
        if not TOKEN_RE.match(token):
            raise PushError("Use 8–200 letters, digits, dots, hyphens, underscores or tildes.")
        value["verify_token_enc"] = encrypt(token)
    value["updated_at"] = utcnow().isoformat()
    _write(db, value)
    after = (value.get("public_base_url") or get_settings().public_base_url).rstrip("/")
    return after != before


def info(db: Session) -> dict:
    value = _value(db)
    token = (decrypt(value["verify_token_enc"]) or "") if value.get("verify_token_enc") else ""
    saved = value.get("public_base_url") or ""
    address = (saved or get_settings().public_base_url).rstrip("/")
    public = is_public(address)
    return {
        "public_base_url": address if saved or public else "",
        "base_source": "app" if saved else "env" if public else None,
        "callback_url": f"{address}/api/youtube/webhook" if public else "",
        "available": public,
        "has_token": bool(token),
        "token_last4": token[-4:],
        "updated_at": value.get("updated_at"),
    }


# ---------------------------------------------------------------- notifications received

def note_notification(db: Session, count: int = 1) -> None:
    today = utcnow().date().isoformat()
    value = _value(db, STATS_KEY)
    if value.get("day") != today:
        value = {"day": today, "count": 0}
    value["count"] = int(value.get("count", 0)) + count
    value["last_at"] = utcnow().isoformat()
    _write(db, value, STATS_KEY)


def notifications(db: Session) -> dict:
    value = _value(db, STATS_KEY)
    return {"today": int(value.get("count", 0)) if value.get("day") == utcnow().date().isoformat() else 0, "last_at": value.get("last_at")}
