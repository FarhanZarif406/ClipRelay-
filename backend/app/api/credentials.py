"""Settings → API keys: owner-managed credentials (DB first, .env fallback). Secrets never leave the server."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import DB, OwnerUser
from app.models import User
from app.services import activity, credential_checks, credentials

router = APIRouter(prefix="/credentials", tags=["credentials"])

CARDS = {
    "youtube": {"title": "YouTube Data API (optional)", "docs": "https://console.cloud.google.com/apis/library/youtube.googleapis.com"},
    "smtp": {"title": "Email (SMTP)", "docs": "https://github.com/FarhanZarif406/ClipRelay-#email-alerts"},
}
class SaveIn(BaseModel):
    values: dict[str, str] = {}


class ValidateIn(BaseModel):
    values: dict[str, str] = {}


def mask(value: str, prefix: int = 4) -> str:
    if not value:
        return ""
    return f"{value[:prefix]}••••••••{value[-4:]}" if len(value) > prefix + 6 else "••••••••"


def _check_group(group: str) -> None:
    if group not in CARDS:
        raise HTTPException(404, "Unknown credential group")


def _card(db, group: str, user: User) -> dict:
    meta = CARDS[group]
    status = credentials.group_status(db, group)
    fields = []
    for key in credentials.groups()[group]:
        spec = credentials.REGISTRY[key]
        value = credentials.get(key)
        field = {"key": key.split(".", 1)[1], "label": spec.label, "secret": spec.secret, "configured": bool(value), "source": credentials.source(key)}
        if user.is_owner:
            field["value"] = "" if spec.secret else value
            field["masked"] = mask(value) if spec.secret else value
        fields.append(field)
    card = {
        "group": group,
        "title": meta["title"],
        # Base URL / model have built-in defaults, so a card counts as set up once its secrets are.
        "configured": all(f["configured"] for f in fields if f["secret"]),
        "state": status["state"] if any(f["configured"] for f in fields if f["secret"]) else "none",
    }
    if user.is_owner:
        card.update({
            "fields": fields,
            "last_error": status["last_error"],
            "verified_at": status["verified_at"],
            "docs_url": meta.get("docs"),
        })
    return card


@router.get("")
def list_cards(db: DB, user: OwnerUser):  # admin only: members never see the API keys section
    return [_card(db, group, user) for group in CARDS]


def _effective(group: str, overrides: dict[str, str]) -> dict[str, str]:
    values = {}
    for key in credentials.groups()[group]:
        short = key.split(".", 1)[1]
        override = overrides.get(short)
        values[short] = override if override else credentials.get(key)
    return values


@router.post("/{group}/validate")
def validate(group: str, body: ValidateIn, db: DB, user: OwnerUser):
    _check_group(group)
    overrides = {k: v.strip() for k, v in body.values.items() if v and v.strip()}
    ok, message = credential_checks.VALIDATORS[group](_effective(group, overrides))
    if not overrides:  # validating what's stored → record the result
        credentials.set_status(db, group, "valid" if ok else "invalid" if ok is False else "unverified", None if ok else message)
    activity.record(db, "Settings", f"{CARDS[group]['title']} credentials validated: {'valid' if ok else 'invalid' if ok is False else 'unverified'}", event="credentials_validated", level="info" if ok is not False else "warning")
    db.commit()
    return {"ok": ok, "message": message, "card": _card(db, group, user)}


@router.put("/{group}")
def save(group: str, body: SaveIn, db: DB, user: OwnerUser):
    _check_group(group)
    allowed = {key.split(".", 1)[1]: key for key in credentials.groups()[group]}
    unknown = set(body.values) - set(allowed)
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(sorted(unknown))}")
    # Blank = keep the current value (secrets are never sent back to the browser).
    updates = {allowed[k]: v.strip() for k, v in body.values.items() if v and v.strip()}
    if not updates:
        raise HTTPException(422, "Nothing to save")
    ok, message = credential_checks.VALIDATORS[group](_effective(group, {k.split(".", 1)[1]: v for k, v in updates.items()}))
    for key, value in updates.items():
        credentials.set_value(db, key, value, user.id)
    credentials.set_status(db, group, "valid" if ok else "invalid" if ok is False else "unverified", None if ok else message)
    labels = ", ".join(credentials.REGISTRY[k].label for k in updates)
    activity.record(db, "Settings", f"{CARDS[group]['title']} credentials saved by {user.email} ({labels})", event="credentials_saved")
    db.commit()
    credentials.changed()
    return {"ok": ok, "message": message, "card": _card(db, group, user)}


@router.delete("/{group}")
def remove(group: str, db: DB, user: OwnerUser):
    _check_group(group)
    keys = credentials.groups()[group]
    fallback = {key: credentials.env_value(key) for key in keys}
    removed = credentials.remove(db, keys)
    if not removed:
        raise HTTPException(404, "Nothing saved in the app for this integration")
    env_left = any(fallback.values())
    activity.record(db, "Settings", f"{CARDS[group]['title']} credentials removed by {user.email}" + (" — using .env values" if env_left else " — now not configured"), event="credentials_removed")
    db.commit()
    credentials.changed()
    return {"fallback": "env" if env_left else "none", "card": _card(db, group, user)}
