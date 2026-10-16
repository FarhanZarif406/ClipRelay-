"""Detection: which YouTube uploads enter the pipeline.

A new upload reaches us as a push notification (PubSubHubbub) or, as a fallback, from polling the channel's
uploads feed. Either way it goes through `discover`, which stores the video exactly once and applies the
duration and cap checks. A video that fails a check is never discarded: it is held as skipped, with its
reason, and can be processed by hand later.
"""

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations import youtube
from app.integrations.http import ApiError
from app.models import Channel, Job, Mode, SkipReason, Video, VideoStatus, utcnow
from app.services import activity, limits, pipeline, push, rules, system

log = logging.getLogger(__name__)

RENEW_BEFORE = timedelta(days=2)
VERIFY_TIMEOUT = timedelta(seconds=60)  # how long the hub is given to verify before a pending subscription counts as failed


def _skip(db: Session, video: Video, code: str, reason: str) -> Video:
    video.status = VideoStatus.SKIPPED
    video.skip_reason = code
    video.rejection_reason = reason
    activity.record(db, "Filter", f"Video #{video.id} skipped ({code}): {reason}", level="warning", event="video_skipped", payload={"video_id": video.id, "reason": code}, user_id=video.user_id)
    return video


def _check(db: Session, video: Video, channel: Channel) -> tuple[str, str] | None:
    """The short-form and cap checks, counted against the videos table inside the caller's transaction."""
    values = rules.effective(db, channel.id, channel.mode, channel.user_id)
    duration = video.duration_sec or 0
    since = pipeline.cap_day_start(values["cap_reset_timezone"])
    taken = db.scalar(
        select(func.count(Video.id)).where(
            Video.channel_id == channel.id, Video.id != video.id, Video.parent_id.is_(None), Video.status == VideoStatus.ACCEPTED, Video.created_at >= since
        )
    ) or 0
    if channel.mode == Mode.PODCASTS:
        # The opposite of Shorts: only long videos are podcasts. Each account's own daily limit decides when a clip goes out.
        shortest = values["min_source_duration_seconds"]
        if duration < shortest:
            return SkipReason.NOT_PODCAST, f"Too short for a podcast: {duration:.0f}s, under the {shortest}s minimum"
        if over := limits.check(db, channel.user_id, channel.mode):
            return over
        if taken >= values["videos_per_channel_per_day"]:
            return SkipReason.CHANNEL_CAP, f"{channel.display_name} already has {taken} podcasts today (limit {values['videos_per_channel_per_day']})"
        return None
    # Short-form = up to the maximum duration from Settings, or anything YouTube itself lists as a Short.
    limit = values["max_duration_seconds"]
    if duration > limit and not youtube.is_short(video.youtube_video_id):
        return SkipReason.LONG_FORM, f"Long-form video: {duration:.0f}s, over the {limit}s short-form limit"
    if duration < values["min_duration_seconds"]:
        return SkipReason.TOO_SHORT, f"Duration {duration:.0f}s is under the {values['min_duration_seconds']}s minimum"
    # A usable video over a limit: it is recorded under Not Processed, not edited.
    if over := limits.check(db, channel.user_id, channel.mode):
        return over
    if taken >= values["videos_per_channel_per_day"]:
        return SkipReason.CHANNEL_CAP, f"{channel.display_name} already has {taken} videos today (limit {values['videos_per_channel_per_day']})"
    return None


def discover(db: Session, channel: Channel, video_id: str, *, meta: youtube.VideoMeta | None = None) -> Video | None:
    """Store one upload and decide whether it enters the pipeline. Returns None when there is nothing new.

    A YouTube video id is processed once, forever: repeat notifications (YouTube sends one whenever a title
    or description is edited) find the existing row, or lose the race on the unique constraint.
    """
    if db.scalar(select(Video.id).where(Video.youtube_video_id == video_id)):
        return None
    if not system.is_on(db):
        return None  # the admin switched the system off: uploads are not even recorded (they are left alone when it is on again)
    meta = meta or youtube.video_details(video_id)
    if meta.live or not meta.duration_seconds:
        return None  # a live stream or premiere that has not finished: it is picked up once it has a duration
    if meta.channel_id and meta.channel_id != channel.youtube_channel_id:
        return None
    if meta.published_at and meta.published_at <= channel.monitoring_since:
        return None  # uploaded before monitoring started — only new uploads are republished

    video = Video(
        channel_id=channel.id, mode=channel.mode, user_id=channel.user_id, youtube_video_id=video_id, permalink=meta.url, thumbnail_url=meta.thumbnail_url,
        posted_at=meta.published_at, original_title=meta.title[:500], original_caption=meta.description,
        original_tags=[str(tag).lstrip("#") for tag in meta.tags][:50], duration_sec=round(meta.duration_seconds, 2),
    )
    try:
        with db.begin_nested():
            db.add(video)
            db.flush()
    except IntegrityError:
        return None
    video.channel = channel
    try:
        failed = _check(db, video, channel)
    except ApiError:
        db.delete(video)  # YouTube gave no answer yet: forget the video so the next poll or push tries again
        db.flush()
        raise
    if meta.published_at and (channel.last_upload_at is None or meta.published_at > channel.last_upload_at):
        channel.last_upload_at = meta.published_at
    activity.record(db, "Detection", f"Video #{video.id} detected on {channel.display_name}: “{meta.title[:60]}” ({video_id})", event="video_detected", payload={"video_id": video.id}, user_id=video.user_id)

    if failed:
        return _skip(db, video, *failed)
    video.status = VideoStatus.ACCEPTED
    if video.is_podcast_source:
        pipeline.create_podcast_job(db, video)
    else:
        pipeline.create_job(db, video)
    return video


def process_anyway(db: Session, video: Video) -> Job:
    """Skipped and Not Processed screens: put a held video into the pipeline by hand, bypassing the duration checks and the limits."""
    if video.status != VideoStatus.SKIPPED:
        raise ValueError("Only skipped videos can be processed by hand")
    video.status = VideoStatus.ACCEPTED
    video.forced = True
    video.skip_reason = video.rejection_reason = None
    job = pipeline.create_podcast_job(db, video) if video.is_podcast_source else pipeline.create_job(db, video)
    activity.record(db, "Detection", f"Video #{video.id} processed by hand", event="video_forced", job_id=job.id)
    return job


def poll_channel(db: Session, channel: Channel) -> list[Video]:
    """Polling fallback: read the channel's uploads feed so a missed push never means a missed video."""
    now = utcnow()
    interval = int(rules.global_values(db, user_id=channel.user_id)["poll_interval_minutes"])
    channel.last_checked_at = now
    channel.next_poll_at = now + timedelta(minutes=interval)
    try:
        entries = youtube.feed(channel.youtube_channel_id)
    except ApiError as exc:
        channel.last_error = str(exc)[:500]
        log.warning("poll failed for channel %s: %s", channel.youtube_channel_id, exc)
        return []
    channel.last_error = None
    known = set(db.scalars(select(Video.youtube_video_id).where(Video.youtube_video_id.in_([e.video_id for e in entries])))) if entries else set()
    found = []
    for entry in entries:
        if entry.video_id in known or (entry.published_at and entry.published_at <= channel.monitoring_since):
            continue
        try:
            video = discover(db, channel, entry.video_id)
        except ApiError as exc:
            channel.last_error = str(exc)[:500]
            log.warning("could not read video %s: %s", entry.video_id, exc)
            continue
        if video:
            found.append(video)
    return found


def discover_by_ids(db: Session, youtube_channel_id: str, video_id: str) -> Video | None:
    """A push notification: look the channel up and run the same discovery as polling."""
    channel = db.scalar(select(Channel).where(Channel.youtube_channel_id == youtube_channel_id, Channel.active.is_(True)))
    return discover(db, channel, video_id) if channel else None


def due_channels(db: Session) -> list[int]:
    if not system.is_on(db):
        return []  # switched off: no channel is checked
    now = utcnow()
    rows = db.scalars(
        select(Channel).where(Channel.active.is_(True), (Channel.next_poll_at.is_(None)) | (Channel.next_poll_at <= now)).order_by(Channel.id).limit(50)
    ).all()
    for channel in rows:
        channel.next_poll_at = now + timedelta(minutes=10)  # lease; the poll sets the real time
    db.flush()
    return [channel.id for channel in rows]


def subscribe(db: Session, channel: Channel) -> bool:
    """Ask the hub to push this channel's uploads to us. Returns False where push cannot work (no public HTTPS URL)."""
    if not youtube.push_available():
        return False
    channel.pubsub_requested_at = utcnow()
    try:
        youtube.subscribe(channel.youtube_channel_id, verify_token=push.ensure_token(db))
    except ApiError as exc:
        channel.pubsub_error = str(exc)[:500]
        activity.record(db, "Detection", f"Push subscription failed for {channel.display_name}: {exc}", level="warning", event="pubsub_failed", user_id=channel.user_id)
        return False
    channel.pubsub_error = None
    return True


def push_status(channel: Channel) -> str:
    """off (paused) · unavailable (no public HTTPS address) · failed · subscribed · expired · pending."""
    if not channel.active:
        return "off"
    if not youtube.push_available():
        return "unavailable"
    if channel.pubsub_error:
        return "failed"
    if channel.pubsub_subscription_expires_at:
        return "subscribed" if channel.pubsub_subscription_expires_at > utcnow() else "expired"
    if channel.pubsub_requested_at and utcnow() - channel.pubsub_requested_at > VERIFY_TIMEOUT:
        return "failed"  # the hub accepted the request but never came back to verify it
    return "pending"


def push_detail(channel: Channel) -> str | None:
    """One line saying why the push status is what it is."""
    status = push_status(channel)
    if status == "failed":
        return channel.pubsub_error or "The hub accepted the request but never verified it — no request reached the callback URL. Is the public address right?"
    if status == "subscribed":
        return "Verified by the hub."
    if status == "expired":
        return "The subscription ran out; it is renewed within the hour."
    if status == "pending":
        return "Hub accepted the request; waiting for it to verify the callback." if channel.pubsub_requested_at else "Not subscribed yet; it is requested within the hour."
    if status == "unavailable":
        return "No public address is set, so the upload feed is checked instead."
    return None


def unsubscribe(channel: Channel) -> None:
    channel.pubsub_subscription_expires_at = channel.pubsub_requested_at = channel.pubsub_error = None
    if youtube.push_available():
        try:
            youtube.subscribe(channel.youtube_channel_id, mode="unsubscribe", verify_token=push.verify_token())
        except ApiError as exc:
            log.warning("unsubscribe failed for %s: %s", channel.youtube_channel_id, exc)


def renew_subscriptions(db: Session) -> dict:
    """Hourly: push subscriptions expire, so renew every active channel's well before it lapses."""
    renewed = 0
    soon = utcnow() + RENEW_BEFORE
    for channel in db.scalars(select(Channel).where(Channel.active.is_(True))):
        if channel.pubsub_subscription_expires_at is None or channel.pubsub_subscription_expires_at <= soon:
            renewed += int(subscribe(db, channel))
    return {"renewed": renewed}
