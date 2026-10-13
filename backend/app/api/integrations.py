"""Integrations → YouTube Data API and YouTube Push Notifications.

Admin only. The API key and the verify token never leave the server: only their last four characters do.
"""

import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, OwnerUser
from app.integrations import youtube
from app.models import AppSetting, Channel, Credential
from app.services import activity, credentials, detection, push, youtube_usage

router = APIRouter(prefix="/integrations", tags=["integrations"])

API_KEY = "youtube.api_key"
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
HUB_GAP_SECONDS = 0.3  # requests to the hub are paced, so many channels at once never flood it
# How the Channels column's states read on the Push card: the hub's own three answers.
CARD_STATUS = {"subscribed": "verified", "pending": "pending", "failed": "failed", "expired": "failed"}


class YouTubeIn(BaseModel):
    api_key: str | None = Field(default=None, max_length=200)
    project_id: str | None = Field(default=None, max_length=60)


class PushIn(BaseModel):
    public_base_url: str | None = Field(default=None, max_length=300)
    verify_token: str | None = Field(default=None, max_length=200)


class SubscribeIn(BaseModel):
    channel_id: str = Field(min_length=1, max_length=60)


# ---------------------------------------------------------------- YouTube Data API

def _youtube(db) -> dict:
    key = credentials.get(API_KEY)
    row = db.get(Credential, API_KEY)
    settings = db.get(AppSetting, "youtube")
    return {
        "has_key": bool(key),
        "key_last4": key[-4:] if len(key) > 8 else "",
        "source": credentials.source(API_KEY),
        "project_id": (settings.value or {}).get("project_id", "") if settings else "",
        "updated_at": row.updated_at if row else None,
        "usage": youtube_usage.flush(db),
    }


@router.get("/youtube")
def youtube_status(db: DB, _: OwnerUser):
    status = _youtube(db)
    db.commit()
    return status


@router.put("/youtube")
def save_youtube(body: YouTubeIn, db: DB, user: OwnerUser):
    changed = []
    if body.api_key is not None:
        key = body.api_key.strip()
        if not KEY_RE.match(key):
            raise HTTPException(422, "That does not look like an API key.")
        credentials.set_value(db, API_KEY, key, user.id)
        changed.append("API key")
    if body.project_id is not None:
        project = body.project_id.strip()
        if project and not PROJECT_RE.match(project):
            raise HTTPException(422, "A project ID is 6–30 lowercase letters, digits or hyphens, starting with a letter.")
        row = db.get(AppSetting, "youtube")
        if row:
            row.value = {**(row.value or {}), "project_id": project}
        else:
            db.add(AppSetting(key="youtube", value={"project_id": project}))
        changed.append("project ID")
    if changed:
        activity.record(db, "Settings", f"{user.email} changed the YouTube Data API {' and '.join(changed)}", event="credentials_saved", user_id=user.id)
    db.commit()
    credentials.changed()
    return _youtube(db)


@router.delete("/youtube/key")
def remove_youtube_key(db: DB, user: OwnerUser):
    """Back to working without a key (or to the key in .env, when there is one)."""
    if not credentials.remove(db, [API_KEY]):
        raise HTTPException(404, "No API key is saved in the app.")
    activity.record(db, "Settings", f"{user.email} removed the YouTube Data API key", event="credentials_removed", user_id=user.id)
    db.commit()
    credentials.changed()
    return _youtube(db)


@router.post("/youtube/test")
def test_youtube(db: DB, _: OwnerUser):
    """The cheapest real call (one quota unit); Google's own answer is reported."""
    result = youtube.test_key(credentials.get(API_KEY))
    if db.get(Credential, API_KEY) and result["status"]:
        credentials.set_status(db, "youtube", "valid" if result["ok"] else "invalid", None if result["ok"] else result["message"])
    status = _youtube(db)
    db.commit()
    return {**result, "status_info": status}


# ---------------------------------------------------------------- YouTube push notifications

def _push(db) -> dict:
    subscriptions = []
    for channel in db.scalars(select(Channel).where(Channel.active.is_(True)).order_by(Channel.id)):
        status = detection.push_status(channel)
        if status in CARD_STATUS:
            subscriptions.append({
                "channel_id": channel.youtube_channel_id, "status": CARD_STATUS[status], "detail": detection.push_detail(channel) or "",
                "expires_at": channel.pubsub_subscription_expires_at,
            })
    return {**push.info(db), "subscriptions": subscriptions, "notifications": push.notifications(db)}


def _resubscribe(db, channels: list[Channel]) -> None:
    for index, channel in enumerate(channels):
        if index:
            time.sleep(HUB_GAP_SECONDS)
        detection.subscribe(db, channel)


@router.get("/push")
def push_status(db: DB, _: OwnerUser):
    return _push(db)


@router.put("/push")
def save_push(body: PushIn, db: DB, user: OwnerUser):
    try:
        moved = push.save(db, public_base_url=body.public_base_url, token=body.verify_token)
    except push.PushError as exc:
        raise HTTPException(422, str(exc)) from exc
    what = " and ".join(name for name, value in (("public address", body.public_base_url), ("verify token", body.verify_token)) if value is not None)
    activity.record(db, "Settings", f"{user.email} changed the push notifications' {what}", event="push_updated", user_id=user.id)
    db.commit()
    push.bust()
    if moved:
        # The hub knows each subscription by its callback address, so a new address means subscribing again.
        channels = list(db.scalars(select(Channel).where(Channel.active.is_(True))))
        for channel in channels:
            channel.pubsub_subscription_expires_at = channel.pubsub_requested_at = channel.pubsub_error = None
        _resubscribe(db, channels)
        db.commit()
    return _push(db)


@router.post("/push/subscribe")
def subscribe_channel(body: SubscribeIn, db: DB, _: OwnerUser):
    channel_id = body.channel_id.strip()
    if not youtube.CHANNEL_ID_RE.match(channel_id):
        raise HTTPException(422, "A channel ID starts with UC and is 24 characters long.")
    if not youtube.push_available():
        raise HTTPException(422, "Set the public base URL first.")
    channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == channel_id))
    if not channel:
        raise HTTPException(404, "That channel is not being monitored. Add it on the Channels page first; it is then subscribed by itself.")
    if not channel.active:
        raise HTTPException(422, "That channel is switched off. Switch it on from the Channels page.")
    detection.subscribe(db, channel)
    db.commit()
    return _push(db)


@router.post("/push/retry-failed")
def retry_failed(db: DB, _: OwnerUser):
    """Only the channels whose last attempt failed — never the whole list."""
    failed = [c for c in db.scalars(select(Channel).where(Channel.active.is_(True))) if CARD_STATUS.get(detection.push_status(c)) == "failed"]
    for channel in failed:
        channel.pubsub_subscription_expires_at = None
    _resubscribe(db, failed)
    db.commit()
    return _push(db)
