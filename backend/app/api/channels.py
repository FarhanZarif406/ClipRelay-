"""Channels: the monitored YouTube channels, their rule overrides, and YouTube's push webhook."""

import hmac
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from app.api.deps import DB, CurrentUser, Workspace
from app.integrations import youtube
from app.integrations.http import ApiError
from app.models import Channel, Job, JobStatus, Mode, RuleSetting, User, Video, VideoStatus, utcnow
from app.services import activity, detection, dispatch, push, rules, serializers

router = APIRouter(tags=["channels"])


class ResolveIn(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class ChannelCreate(ResolveIn):
    pass


class ChannelUpdate(BaseModel):
    active: bool | None = None


class RulesIn(BaseModel):
    values: dict[str, bool | int | float | str | None]


def _owner_name(db, channel: Channel) -> str:
    owner = db.get(User, channel.user_id) if channel.user_id else None
    return (owner.name or owner.email) if owner else "another member"


def _get(db, channel_id: int, user: User) -> Channel:
    channel = db.get(Channel, channel_id)
    if not channel or channel.user_id != user.id:  # another member's channel does not exist as far as this one can tell
        raise HTTPException(404, "Channel not found")
    return channel


def _stats(db) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for channel_id, count in db.execute(
        select(Video.channel_id, func.count(Job.id)).join(Job, Job.video_id == Video.id).where(Job.posted_at.is_not(None)).group_by(Video.channel_id)
    ):
        out.setdefault(channel_id, {})["published"] = count
    # A podcast's clips are videos too; only the uploads themselves are counted as detected or skipped.
    for channel_id, status, count in db.execute(select(Video.channel_id, Video.status, func.count(Video.id)).where(Video.parent_id.is_(None)).group_by(Video.channel_id, Video.status)):
        out.setdefault(channel_id, {})["skipped" if status == VideoStatus.SKIPPED else "detected"] = count
    return out


def _resolve(query: str) -> youtube.ChannelInfo:
    try:
        return youtube.resolve_channel(query)
    except ApiError as exc:
        raise HTTPException(404 if exc.status == 404 else 400, str(exc)) from exc


@router.get("/channels")
def list_channels(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    stats = _stats(db)
    channels = db.scalars(select(Channel).where(Channel.mode == mode, Channel.user_id == user.id).order_by(Channel.id.desc())).all()
    overrides = dict(db.execute(select(RuleSetting.channel_id, func.count()).where(RuleSetting.channel_id.is_not(None)).group_by(RuleSetting.channel_id)).all())
    return {
        "items": [serializers.channel(c, stats.get(c.id), overrides.get(c.id, 0)) for c in channels],
        "push_available": youtube.push_available(),
        "poll_minutes": int(rules.global_values(db, user_id=user.id)["poll_interval_minutes"]),
    }


@router.post("/channels/resolve")
def resolve(body: ResolveIn, db: DB, user: CurrentUser):
    """Look a channel up so the operator can confirm it is the right one before saving."""
    info = _resolve(body.query)
    existing = db.scalar(select(Channel).where(Channel.youtube_channel_id == info.youtube_channel_id))
    return {
        "youtube_channel_id": info.youtube_channel_id, "display_name": info.display_name, "handle": info.handle,
        "thumbnail_url": info.thumbnail_url, "url": info.url, "already_added": bool(existing), "added_in": existing.mode if existing else None,
        "added_by": _owner_name(db, existing) if existing and existing.user_id != user.id else None,
    }


@router.post("/channels", status_code=201)
def add_channel(body: ChannelCreate, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    info = _resolve(body.query)
    existing = db.scalar(select(Channel).where(Channel.youtube_channel_id == info.youtube_channel_id))
    if existing:
        if existing.user_id != user.id:  # a channel belongs to the member who added it first
            raise HTTPException(409, f"This channel has already been added by {_owner_name(db, existing)}")
        # One channel, one workspace: its uploads are either republished whole (Shorts) or cut into clips (Podcasts).
        where = "here" if existing.mode == mode else f"in the {existing.mode.capitalize()} workspace"
        raise HTTPException(409, f"This channel is already being monitored {where}")
    now = utcnow()
    channel = Channel(
        youtube_channel_id=info.youtube_channel_id, mode=mode, user_id=user.id, handle=info.handle, display_name=info.display_name or info.youtube_channel_id,
        thumbnail_url=info.thumbnail_url,
        added_by=user.id, monitoring_since=now, next_poll_at=now,
    )
    db.add(channel)
    db.flush()
    activity.record(db, "Detection", f"Channel {channel.display_name} added by {user.email}", event="channel_added", payload={"channel_id": channel.id}, user_id=user.id)
    detection.subscribe(db, channel)
    db.commit()
    return serializers.channel(channel)


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelUpdate, db: DB, user: CurrentUser):
    channel = _get(db, channel_id, user)
    data = body.model_dump(exclude_unset=True)
    if data.get("active") is not None and data["active"] != channel.active:
        channel.active = data["active"]
        if channel.active:
            # Uploads published while the channel was switched off are not republished afterwards.
            channel.monitoring_since = channel.next_poll_at = utcnow()
            detection.subscribe(db, channel)
        else:
            detection.unsubscribe(channel)
        activity.record(db, "Detection", f"Channel {channel.display_name} {'activated' if channel.active else 'paused'} by {user.email}", event="channel_toggled", user_id=user.id)
    db.commit()
    db.refresh(channel)
    return serializers.channel(channel, _stats(db).get(channel.id))


@router.delete("/channels/{channel_id}", status_code=204)
def delete_channel(channel_id: int, db: DB, user: CurrentUser):
    channel = _get(db, channel_id, user)
    detection.unsubscribe(channel)
    # Videos that have not gone out yet stop here; what was already published keeps running its checks.
    stopped = 0
    for job in db.scalars(select(Job).join(Video, Job.video_id == Video.id).where(Video.channel_id == channel.id, Job.status.in_(JobStatus.PENDING - {JobStatus.UPLOADING}))):
        job.next_check_at = None
        job.error = f"Channel {channel.display_name} was removed"
        activity.job_event(db, job, JobStatus.CANCELLED, "Cancelled: the channel was removed")
        stopped += 1
    # The videos stay as the record of what was detected and published, but no longer point at the channel.
    # Done here, not left to the database: a later channel could otherwise be given this channel's id and inherit them.
    db.execute(update(Video).where(Video.channel_id == channel.id).values(channel_id=None).execution_options(synchronize_session=False))
    db.execute(delete(RuleSetting).where(RuleSetting.channel_id == channel.id).execution_options(synchronize_session=False))
    activity.record(db, "Detection", f"Channel {channel.display_name} removed by {user.email}" + (f" · {stopped} unfinished video(s) cancelled" if stopped else ""), event="channel_removed", user_id=user.id)
    db.flush()
    db.expire_all()
    db.delete(db.get(Channel, channel_id))
    db.commit()


@router.post("/channels/{channel_id}/check")
def check_now(channel_id: int, db: DB, user: CurrentUser):
    """Read the channel's uploads feed right now instead of waiting for the next poll."""
    channel = _get(db, channel_id, user)
    videos = detection.poll_channel(db, channel)
    job_ids = list(db.scalars(select(Job.id).where(Job.video_id.in_([v.id for v in videos])))) if videos else []
    db.commit()
    for job_id in job_ids:
        dispatch.start_job(job_id)
    return {"found": len(videos), "queued": len(job_ids), "skipped": len(videos) - len(job_ids), "error": channel.last_error}


@router.get("/channels/{channel_id}/rules")
def get_channel_rules(channel_id: int, db: DB, user: CurrentUser):
    channel = _get(db, channel_id, user)
    return _channel_rules(db, channel)


def _channel_rules(db, channel: Channel) -> dict:
    return {
        "overrides": rules.channel_overrides(db, channel.id, channel.mode), "effective": rules.effective(db, channel.id, channel.mode, channel.user_id),
        "global": rules.global_values(db, channel.mode, channel.user_id),
    }


@router.put("/channels/{channel_id}/rules")
def put_channel_rules(channel_id: int, body: RulesIn, db: DB, user: CurrentUser):
    """Set overrides for one channel. A null value removes the override, so the channel inherits the global value again."""
    channel = _get(db, channel_id, user)
    try:
        changes = rules.set_values(db, body.values, channel=channel, user=user)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if changes:
        activity.record(db, "Settings", f"{user.email} changed {', '.join(c.key for c in changes)} for {channel.display_name}", event="rules_updated", user_id=user.id)
    db.commit()
    return _channel_rules(db, channel)


# ---------------------------------------------------------------- YouTube push webhook (no login: called by the hub)

@router.get("/youtube/webhook", include_in_schema=False)
def webhook_verify(
    db: DB,
    mode: str = Query("", alias="hub.mode"),
    topic: str = Query("", alias="hub.topic"),
    challenge: str = Query("", alias="hub.challenge"),
    lease_seconds: int | None = Query(None, alias="hub.lease_seconds"),
    verify_token: str = Query("", alias="hub.verify_token"),
    reason: str = Query("", alias="hub.reason"),
):
    """The hub checks that we really asked for a subscription; echoing the challenge confirms it."""
    youtube_channel_id = youtube.channel_id_from_topic(topic)
    channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == youtube_channel_id)) if youtube_channel_id else None
    wanted = bool(channel and channel.active)
    # Only a subscription that is still waiting can be marked failed, so a stranger calling this public
    # address cannot break one that already works.
    waiting = wanted and (channel.pubsub_subscription_expires_at is None or channel.pubsub_subscription_expires_at <= utcnow())
    if mode == "denied":
        if waiting:
            channel.pubsub_error = f"Hub denied: {reason[:200] or 'no reason given'}"
            db.commit()
        return Response("", media_type="text/plain")
    expected = push.verify_token()
    if expected and not hmac.compare_digest(verify_token.encode(), expected.encode()):
        if waiting and mode == "subscribe":
            channel.pubsub_error = "The hub's verify token did not match the saved one."
            db.commit()
        raise HTTPException(404, "Verify token mismatch")
    if mode == "subscribe" and wanted:
        channel.pubsub_subscription_expires_at = utcnow() + timedelta(seconds=lease_seconds or youtube.LEASE_SECONDS)
        channel.pubsub_error = None
        db.commit()
    elif not (mode == "unsubscribe" and not wanted):
        raise HTTPException(404, "No such subscription")
    return Response(challenge, media_type="text/plain")


@router.post("/youtube/webhook", include_in_schema=False, status_code=204)
async def webhook_notify(request: Request, db: DB):
    """A new upload (or an edit of an old one). Only signed notifications are accepted; the work is queued."""
    body = await request.body()
    if not youtube.verify_signature(body, request.headers.get("x-hub-signature")):
        return Response(status_code=204)  # the PubSubHubbub spec asks for 2xx even when a signature is ignored
    try:
        pairs = youtube.parse_notification(body)
    except ApiError:
        return Response(status_code=204)
    if pairs:
        push.note_notification(db, len(pairs))
        db.commit()
    for youtube_channel_id, video_id in pairs:
        dispatch.discover_video(youtube_channel_id, video_id)
    return Response(status_code=204)
