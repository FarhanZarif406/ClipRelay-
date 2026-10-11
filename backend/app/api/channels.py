"""Channels: the monitored YouTube channels, their rule overrides, and YouTube's push webhook."""

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.integrations import youtube
from app.integrations.http import ApiError
from app.models import Channel, Job, TikTokAccount, TikTokStatus, Video, VideoStatus, utcnow
from app.services import activity, detection, dispatch, rules, serializers

router = APIRouter(tags=["channels"])


class ResolveIn(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ChannelCreate(ResolveIn):
    default_tiktok_account_id: int | None = None


class ChannelUpdate(BaseModel):
    active: bool | None = None
    default_tiktok_account_id: int | None = None


class RulesIn(BaseModel):
    values: dict[str, bool | int | float | str | None]


def _get(db, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if not channel:
        raise HTTPException(404, "Channel not found")
    return channel


def _account(db, account_id: int | None) -> TikTokAccount | None:
    if not account_id:
        return None
    account = db.get(TikTokAccount, account_id)
    if not account or account.status == TikTokStatus.REVOKED:
        raise HTTPException(404, "TikTok account not found")
    return account


def _stats(db) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for channel_id, count in db.execute(
        select(Video.channel_id, func.count(Job.id)).join(Job, Job.video_id == Video.id).where(Job.posted_at.is_not(None)).group_by(Video.channel_id)
    ):
        out.setdefault(channel_id, {})["published"] = count
    for channel_id, status, count in db.execute(select(Video.channel_id, Video.status, func.count(Video.id)).group_by(Video.channel_id, Video.status)):
        out.setdefault(channel_id, {})["skipped" if status == VideoStatus.SKIPPED else "detected"] = count
    return out


def _resolve(query: str) -> youtube.ChannelInfo:
    try:
        return youtube.resolve_channel(query)
    except ApiError as exc:
        raise HTTPException(404 if exc.status == 404 else 400, str(exc)) from exc


@router.get("/channels")
def list_channels(db: DB, _: CurrentUser):
    stats = _stats(db)
    channels = db.scalars(select(Channel).order_by(Channel.id.desc())).all()
    overrides = dict(db.execute(select(rules.RuleSetting.channel_id, func.count()).where(rules.RuleSetting.channel_id.is_not(None)).group_by(rules.RuleSetting.channel_id)).all())
    return {
        "items": [serializers.channel(c, stats.get(c.id), overrides.get(c.id, 0)) for c in channels],
        "push_available": youtube.push_available(),
    }


@router.post("/channels/resolve")
def resolve(body: ResolveIn, db: DB, _: CurrentUser):
    """Look a channel up so the operator can confirm it is the right one before saving."""
    info = _resolve(body.query)
    existing = db.scalar(select(Channel.id).where(Channel.youtube_channel_id == info.youtube_channel_id))
    return {
        "youtube_channel_id": info.youtube_channel_id, "display_name": info.display_name, "handle": info.handle,
        "thumbnail_url": info.thumbnail_url, "url": info.url, "already_added": bool(existing),
    }


@router.post("/channels", status_code=201)
def add_channel(body: ChannelCreate, db: DB, user: CurrentUser):
    account = _account(db, body.default_tiktok_account_id)
    info = _resolve(body.query)
    if db.scalar(select(Channel.id).where(Channel.youtube_channel_id == info.youtube_channel_id)):
        raise HTTPException(409, "This channel is already being monitored")
    now = utcnow()
    channel = Channel(
        youtube_channel_id=info.youtube_channel_id, handle=info.handle, display_name=info.display_name or info.youtube_channel_id,
        thumbnail_url=info.thumbnail_url, default_tiktok_account_id=account.id if account else None,
        added_by=user.id, monitoring_since=now, next_poll_at=now,
    )
    db.add(channel)
    db.flush()
    activity.record(db, "Detection", f"Channel {channel.display_name} added by {user.email}", event="channel_added", payload={"channel_id": channel.id})
    detection.subscribe(db, channel)
    db.commit()
    return serializers.channel(channel)


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelUpdate, db: DB, user: CurrentUser):
    channel = _get(db, channel_id)
    data = body.model_dump(exclude_unset=True)
    if "default_tiktok_account_id" in data:
        account = _account(db, data["default_tiktok_account_id"])
        channel.default_tiktok_account_id = account.id if account else None
    if data.get("active") is not None and data["active"] != channel.active:
        channel.active = data["active"]
        if channel.active:
            # Uploads published while the channel was switched off are not republished afterwards.
            channel.monitoring_since = channel.next_poll_at = utcnow()
            detection.subscribe(db, channel)
        else:
            channel.pubsub_subscription_expires_at = None
            detection.unsubscribe(channel)
        activity.record(db, "Detection", f"Channel {channel.display_name} {'activated' if channel.active else 'paused'} by {user.email}", event="channel_toggled")
    db.commit()
    db.refresh(channel)
    return serializers.channel(channel, _stats(db).get(channel.id))


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: DB, user: CurrentUser):
    channel = _get(db, channel_id)
    detection.unsubscribe(channel)
    activity.record(db, "Detection", f"Channel {channel.display_name} removed by {user.email}", event="channel_removed")
    db.delete(channel)  # its videos stay as the record of what was published
    db.commit()


@router.post("/channels/{channel_id}/check")
def check_now(channel_id: int, db: DB, _: CurrentUser):
    """Read the channel's uploads feed right now instead of waiting for the next poll."""
    channel = _get(db, channel_id)
    videos = detection.poll_channel(db, channel)
    job_ids = list(db.scalars(select(Job.id).where(Job.video_id.in_([v.id for v in videos])))) if videos else []
    db.commit()
    for job_id in job_ids:
        dispatch.start_job(job_id)
    return {"found": len(videos), "queued": len(job_ids), "skipped": len(videos) - len(job_ids), "error": channel.last_error}


@router.get("/channels/{channel_id}/rules")
def get_channel_rules(channel_id: int, db: DB, _: CurrentUser):
    channel = _get(db, channel_id)
    return {"overrides": rules.channel_overrides(db, channel.id), "effective": rules.effective(db, channel.id), "global": rules.global_values(db)}


@router.put("/channels/{channel_id}/rules")
def put_channel_rules(channel_id: int, body: RulesIn, db: DB, user: CurrentUser):
    """Set overrides for one channel. A null value removes the override, so the channel inherits the global value again."""
    channel = _get(db, channel_id)
    try:
        changes = rules.set_values(db, body.values, channel=channel, user=user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if changes:
        activity.record(db, "Settings", f"{user.email} changed {', '.join(c.key for c in changes)} for {channel.display_name}", event="rules_updated")
    db.commit()
    return {"overrides": rules.channel_overrides(db, channel.id), "effective": rules.effective(db, channel.id), "global": rules.global_values(db)}


# ---------------------------------------------------------------- YouTube push webhook (no login: called by the hub)

@router.get("/youtube/webhook", include_in_schema=False)
def webhook_verify(
    db: DB,
    mode: str = Query("", alias="hub.mode"),
    topic: str = Query("", alias="hub.topic"),
    challenge: str = Query("", alias="hub.challenge"),
    lease_seconds: int | None = Query(None, alias="hub.lease_seconds"),
):
    """The hub checks that we really asked for a subscription; echoing the challenge confirms it."""
    youtube_channel_id = youtube.channel_id_from_topic(topic)
    channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)) if youtube_channel_id else None
    wanted = bool(channel and channel.active)
    if mode == "subscribe" and wanted:
        from datetime import timedelta

        channel.pubsub_subscription_expires_at = utcnow() + timedelta(seconds=lease_seconds or youtube.LEASE_SECONDS)
        db.commit()
    elif not (mode == "unsubscribe" and not wanted):
        raise HTTPException(404, "No such subscription")
    return Response(challenge, media_type="text/plain")


@router.post("/youtube/webhook", include_in_schema=False, status_code=204)
async def webhook_notify(request: Request):
    """A new upload (or an edit of an old one). Only signed notifications are accepted; the work is queued."""
    body = await request.body()
    if not youtube.verify_signature(body, request.headers.get("x-hub-signature")):
        return Response(status_code=204)  # the PubSubHubbub spec asks for 2xx even when a signature is ignored
    try:
        pairs = youtube.parse_notification(body)
    except ApiError:
        return Response(status_code=204)
    for youtube_channel_id, video_id in pairs:
        dispatch.discover_video(youtube_channel_id, video_id)
    return Response(status_code=204)
