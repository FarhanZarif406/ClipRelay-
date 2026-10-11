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

from app.integrations import llm, youtube
from app.integrations.http import ApiError
from app.models import Channel, Job, SkipReason, TikTokAccount, Video, VideoStatus, utcnow
from app.services import activity, pipeline, rules, workspace_settings

log = logging.getLogger(__name__)

RENEW_BEFORE = timedelta(days=2)
LANG_LABELS = {"hi": "Hindi", "ur": "Urdu", "en": "English", "es": "Spanish", "pt": "Portuguese", "ja": "Japanese", "ar": "Arabic", "bn": "Bengali", "fr": "French", "de": "German"}


def _skip(db: Session, video: Video, code: str, reason: str) -> Video:
    video.status = VideoStatus.SKIPPED
    video.skip_reason = code
    video.rejection_reason = reason
    activity.record(db, "Filter", f"Video #{video.id} skipped ({code}): {reason}", level="warning", event="video_skipped", payload={"video_id": video.id, "reason": code})
    return video


def _language_reason(video: Video, policy: dict) -> str | None:
    """Optional language rule from Automation Rules (off by default). Returns the reason to skip, if any."""
    if not policy.get("language_gate_enabled"):
        return None
    allowed = [lang.lower() for lang in policy.get("allowed_languages", [])]
    text = f"{video.original_title}\n{video.original_caption}".strip()
    try:
        video.detected_language, video.language_confidence = llm.detect_language(text) if text else ("und", 0.0)
    except (ApiError, ValueError) as exc:
        return f"Language detection failed: {exc}"
    if allowed and video.detected_language not in allowed:
        return "Not " + " or ".join(LANG_LABELS.get(code, code) for code in allowed)
    return None


def _check(db: Session, video: Video, channel: Channel, account: TikTokAccount | None) -> tuple[str, str] | None:
    """The Shorts, duration and cap checks, counted against the videos table inside the caller's transaction."""
    values = rules.effective(db, channel.id)
    duration = video.duration_sec or 0
    if values["shorts_only"] and not youtube.is_short(video.youtube_video_id):
        return SkipReason.NOT_SHORT, f"Not a YouTube Short — a regular video of {duration:.0f}s"
    if duration > values["max_duration_seconds"]:
        return SkipReason.TOO_LONG, f"Duration {duration:.0f}s is over the {values['max_duration_seconds']}s limit — not short-form"
    if duration < values["min_duration_seconds"]:
        return SkipReason.TOO_SHORT, f"Duration {duration:.0f}s is under the {values['min_duration_seconds']}s minimum"
    reason = _language_reason(video, workspace_settings.get(db, "policy"))
    if reason:
        return SkipReason.LANGUAGE, reason

    since = pipeline.cap_day_start(values["cap_reset_timezone"])
    taken = db.scalar(
        select(func.count(Video.id)).where(
            Video.channel_id == channel.id, Video.id != video.id, Video.status == VideoStatus.ACCEPTED, Video.created_at >= since
        )
    ) or 0
    if taken >= values["videos_per_channel_per_day"]:
        return SkipReason.CHANNEL_CAP, f"{channel.display_name} already has {taken} videos today (limit {values['videos_per_channel_per_day']})"
    if account is not None:
        cap = pipeline.account_cap(account, values)
        if pipeline.account_load(db, account.id, since) >= cap:
            return SkipReason.ACCOUNT_CAP, f"@{account.username} already has {cap} uploads today (limit {cap})"
    return None


def discover(db: Session, channel: Channel, video_id: str, *, meta: youtube.VideoMeta | None = None) -> Video | None:
    """Store one upload and decide whether it enters the pipeline. Returns None when there is nothing new.

    A YouTube video id is processed once, forever: repeat notifications (YouTube sends one whenever a title
    or description is edited) find the existing row, or lose the race on the unique constraint.
    """
    if db.scalar(select(Video.id).where(Video.youtube_video_id == video_id)):
        return None
    meta = meta or youtube.video_details(video_id)
    if meta.live or not meta.duration_seconds:
        return None  # a live stream or premiere that has not finished: it is picked up once it has a duration
    if meta.channel_id and meta.channel_id != channel.youtube_channel_id:
        return None
    if meta.published_at and meta.published_at <= channel.monitoring_since:
        return None  # uploaded before monitoring started — only new uploads are republished

    video = Video(
        channel_id=channel.id, youtube_video_id=video_id, permalink=meta.url, thumbnail_url=meta.thumbnail_url,
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
        failed = _check(db, video, channel, pipeline.pick_account(db, video))
    except ApiError:
        db.delete(video)  # YouTube gave no answer yet: forget the video so the next poll or push tries again
        db.flush()
        raise
    if meta.published_at and (channel.last_upload_at is None or meta.published_at > channel.last_upload_at):
        channel.last_upload_at = meta.published_at
    activity.record(db, "Detection", f"Video #{video.id} detected on {channel.display_name}: “{meta.title[:60]}” ({video_id})", event="video_detected", payload={"video_id": video.id})

    if failed:
        return _skip(db, video, *failed)
    video.status = VideoStatus.ACCEPTED
    pipeline.create_job(db, video, pipeline.pick_account(db, video))
    return video


def process_anyway(db: Session, video: Video) -> Job:
    """Skipped screen: put a held video into the pipeline by hand, bypassing the duration and cap checks."""
    if video.status != VideoStatus.SKIPPED:
        raise ValueError("Only skipped videos can be processed by hand")
    video.status = VideoStatus.ACCEPTED
    video.forced = True
    video.skip_reason = video.rejection_reason = None
    job = pipeline.create_job(db, video, pipeline.pick_account(db, video))
    activity.record(db, "Detection", f"Video #{video.id} processed by hand", event="video_forced", job_id=job.id)
    return job


def poll_channel(db: Session, channel: Channel) -> list[Video]:
    """Polling fallback: read the channel's uploads feed so a missed push never means a missed video."""
    now = utcnow()
    interval = int(rules.global_values(db)["poll_interval_minutes"])
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
    try:
        youtube.subscribe(channel.youtube_channel_id)
    except ApiError as exc:
        channel.last_error = str(exc)[:500]
        activity.record(db, "Detection", f"Push subscription failed for {channel.display_name}: {exc}", level="warning", event="pubsub_failed")
        return False
    return True


def unsubscribe(channel: Channel) -> None:
    if youtube.push_available():
        try:
            youtube.subscribe(channel.youtube_channel_id, mode="unsubscribe")
        except ApiError as exc:
            log.warning("unsubscribe failed for %s: %s", channel.youtube_channel_id, exc)


def renew_subscriptions(db: Session) -> dict:
    """Daily: push subscriptions expire, so renew every active channel's before it lapses."""
    renewed = 0
    soon = utcnow() + RENEW_BEFORE
    for channel in db.scalars(select(Channel).where(Channel.active.is_(True))):
        if channel.pubsub_subscription_expires_at is None or channel.pubsub_subscription_expires_at <= soon:
            renewed += int(subscribe(db, channel))
    return {"renewed": renewed}
