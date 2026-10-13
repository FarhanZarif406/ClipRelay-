"""Credential store: values saved from Settings (encrypted in the DB) win over .env, which stays the fallback.

Reads are cached for 30 s per process. Writes bust the local cache and publish on Redis so the API and
every Celery worker drop their caches too — no restarts needed. Values are never logged.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Credential, utcnow
from app.security import decrypt, encrypt

log = logging.getLogger(__name__)
CHANNEL = "cliprelay:credentials"
TTL = 30.0


@dataclass(frozen=True)
class Spec:
    env: str  # attribute on Settings used as the .env fallback
    group: str
    label: str
    secret: bool = True


REGISTRY: dict[str, Spec] = {
    "youtube.api_key": Spec("youtube_api_key", "youtube", "YouTube Data API key"),
    "smtp.host": Spec("smtp_host", "smtp", "SMTP host", secret=False),
    "smtp.port": Spec("smtp_port", "smtp", "Port", secret=False),
    "smtp.security": Spec("smtp_security", "smtp", "Security (starttls / ssl / none)", secret=False),
    "smtp.username": Spec("smtp_username", "smtp", "Username", secret=False),
    "smtp.password": Spec("smtp_password", "smtp", "Password / app password"),
    "smtp.from_address": Spec("smtp_from_address", "smtp", "From address", secret=False),
}


def groups() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, spec in REGISTRY.items():
        out.setdefault(spec.group, []).append(key)
    return out


_lock = threading.Lock()
_cache: dict[str, str] | None = None
_loaded_at = 0.0
_bust_hooks: list[Callable[[], None]] = []


def on_bust(hook: Callable[[], None]) -> None:
    """Other caches (e.g. LLM providers) register here so one broadcast clears everything."""
    _bust_hooks.append(hook)


def bust() -> None:
    global _cache
    with _lock:
        _cache = None


def _bust_all() -> None:
    bust()
    for hook in _bust_hooks:
        hook()


def _db_values() -> dict[str, str]:
    global _cache, _loaded_at
    with _lock:
        if _cache is not None and time.monotonic() - _loaded_at < TTL:
            return _cache
    values: dict[str, str] = {}
    db = SessionLocal()
    try:
        for row in db.scalars(select(Credential)):
            try:
                values[row.key] = decrypt(row.value_enc) or ""
            except RuntimeError:
                log.error("credential %s could not be decrypted (has ENCRYPTION_KEY changed?)", row.key)
    except Exception as exc:  # table missing before migrations, DB down, …
        log.warning("credential store unavailable, falling back to .env: %s", exc)
    finally:
        db.close()
    with _lock:
        _cache, _loaded_at = values, time.monotonic()
    return values


def env_value(key: str) -> str:
    value = getattr(get_settings(), REGISTRY[key].env, "")
    return "" if value is None else str(value)


def get(key: str) -> str:
    """Effective value: saved in the app, else .env, else ''."""
    return _db_values().get(key) or env_value(key)


def source(key: str) -> str | None:
    """'app' (saved in Settings), 'env' (set in .env), 'default' (built-in default) or None."""
    if _db_values().get(key):
        return "app"
    value = env_value(key)
    if not value:
        return None
    from app.config import Settings

    default = Settings.model_fields[REGISTRY[key].env].default
    return "default" if value == ("" if default is None else str(default)) else "env"


def rows(db: Session, group: str) -> dict[str, Credential]:
    keys = groups()[group]
    return {r.key: r for r in db.scalars(select(Credential).where(Credential.key.in_(keys)))}


def set_value(db: Session, key: str, value: str, user_id: int | None) -> None:
    if key not in REGISTRY:
        raise KeyError(key)
    row = db.get(Credential, key)
    if row is None:
        row = Credential(key=key, value_enc="")
        db.add(row)
    row.value_enc = encrypt(value) or ""
    row.status, row.last_error, row.verified_at = "unverified", None, None
    row.updated_by, row.updated_at = user_id, utcnow()
    db.flush()
    bust()


def remove(db: Session, keys: list[str]) -> int:
    count = 0
    for key in keys:
        row = db.get(Credential, key)
        if row is not None:
            db.delete(row)
            count += 1
    db.flush()
    bust()
    return count


def set_status(db: Session, group: str, status: str, error: str | None = None) -> None:
    for row in rows(db, group).values():
        row.status = status
        row.last_error = error
        if status == "valid":
            row.verified_at = utcnow()
    db.flush()


def group_status(db: Session, group: str) -> dict:
    """Card state: none | env | unverified | valid | invalid, plus last_error / verified_at."""
    saved = rows(db, group)
    if not saved:
        configured = any(env_value(k) for k in groups()[group])
        return {"state": "env" if configured else "none", "last_error": None, "verified_at": None}
    statuses = {r.status for r in saved.values()}
    state = "invalid" if "invalid" in statuses else "unverified" if "unverified" in statuses else "valid"
    return {
        "state": state,
        "last_error": next((r.last_error for r in saved.values() if r.last_error), None),
        "verified_at": max((r.verified_at for r in saved.values() if r.verified_at), default=None),
    }


def changed() -> None:
    """Call after committing a credential/provider change: drop caches here and in every other process."""
    _bust_all()
    if get_settings().environment == "test":
        return
    try:
        from app.services.events import get_redis

        get_redis().publish(CHANNEL, json.dumps({"type": "credentials_changed"}))
    except Exception as exc:
        log.warning("could not broadcast credential change: %s", exc)


def start_listener() -> None:
    """Background thread that clears caches when another process changes credentials."""
    if get_settings().environment == "test":
        return

    def run() -> None:
        from app.services.events import get_redis

        while True:
            try:
                pubsub = get_redis().pubsub()
                pubsub.subscribe(CHANNEL)
                for message in pubsub.listen():
                    if message.get("type") == "message":
                        _bust_all()
            except Exception as exc:
                log.debug("credential listener reconnecting: %s", exc)
                time.sleep(5)

    threading.Thread(target=run, name="credential-listener", daemon=True).start()
