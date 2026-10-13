"""Aggregations for the Dashboard, Daily Report, sidebar badges and account cards.

Every "today" here is a day in the cap-reset timezone (Settings, Asia/Karachi by default) — the same day
the daily caps count against — so the Dashboard, the Daily Report and the caps always agree.
"""

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ActivityLog,
    Channel,
    Job,
    JobStatus,
    Mode,
    Video,
    VideoStatus,
)
from app.services import buffer, rules, serializers, workspace_settings
from app.services.pipeline import cap_day_start


def _count(db: Session, stmt) -> int:
    return db.scalar(stmt) or 0


def _in(mode: str, user_id: int | None):
    """Condition: the job belongs to this member, in this workspace (Shorts or Podcasts)."""
    return Job.video_id.in_(select(Video.id).where(Video.mode == mode, Video.user_id == user_id))


def _uploads(mode: str, user_id: int | None):
    """Conditions: videos uploaded to this member's watched channels — not the clips cut from a podcast."""
    return (Video.mode == mode, Video.user_id == user_id, Video.parent_id.is_(None))


def timezone_name(db: Session, user_id: int | None = None) -> str:
    return rules.global_values(db, user_id=user_id)["cap_reset_timezone"]


def day_start(db: Session, day: date | None = None, user_id: int | None = None) -> datetime:
    """Midnight (as a UTC instant) of `day`, or of today, in the member's timezone."""
    zone = ZoneInfo(timezone_name(db, user_id))
    if day is None:
        return cap_day_start(zone.key)
    return datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(ZoneInfo("UTC"))


def _daily_series(timestamps: list[datetime], end_day: datetime, days: int, zone: ZoneInfo) -> list[int]:
    counts = Counter(ts.astimezone(zone).date() for ts in timestamps if ts)
    last = end_day.astimezone(zone).date()
    return [counts.get(last - timedelta(days=days - 1 - i), 0) for i in range(days)]


def account_stats(db: Session, start: datetime | None = None, user_id: int | None = None) -> dict[int, dict]:
    """Per Buffer account: published and failed on the day that starts at `start`, and published in all."""
    start = start or day_start(db, user_id=user_id)
    end = start + timedelta(days=1)
    out: dict[int, dict] = {}

    def put(rows, key):
        for account_id, count in rows:
            if account_id is not None:
                out.setdefault(account_id, {})[key] = count

    put(db.execute(select(Job.buffer_channel_id, func.count()).where(Job.posted_at >= start, Job.posted_at < end).group_by(Job.buffer_channel_id)), "posts_today")
    put(db.execute(select(Job.buffer_channel_id, func.count()).where(Job.status == JobStatus.FAILED, Job.updated_at >= start, Job.updated_at < end).group_by(Job.buffer_channel_id)), "failed_today")
    put(db.execute(select(Job.buffer_channel_id, func.count()).where(Job.posted_at.is_not(None)).group_by(Job.buffer_channel_id)), "lifetime_posts")
    return out


def nav(db: Session, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict:
    return {
        "pending_jobs": _count(db, select(func.count(Job.id)).where(Job.status.in_(JobStatus.PENDING), _in(mode, user_id))),
        "onboarding_completed": workspace_settings.get(db, "onboarding")["completed"],
        "buffer_connected": buffer.uses_buffer(db, user_id),
        "buffer_accounts": sum(1 for c in buffer.channels(db, user_id, mode) if c.enabled) if user_id else 0,
        "review_jobs": _count(db, select(func.count(Job.id)).where(Job.status == JobStatus.AWAITING_APPROVAL, _in(mode, user_id))),
        "failed_jobs": _count(db, select(func.count(Job.id)).where(Job.status == JobStatus.FAILED, _in(mode, user_id))),
        "skipped_videos": _count(db, select(func.count(Video.id)).where(Video.status == VideoStatus.SKIPPED, *_uploads(mode, user_id))),
        "channels": _count(db, select(func.count(Channel.id)).where(Channel.mode == mode, Channel.user_id == user_id)),
    }


def summary(db: Session, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict:
    zone = ZoneInfo(timezone_name(db, user_id))
    today = day_start(db, user_id=user_id)
    yesterday = today - timedelta(days=1)
    spark_start = today - timedelta(days=9)

    mine = _in(mode, user_id)
    fetched_ts = list(db.scalars(select(Video.created_at).where(Video.created_at >= spark_start, *_uploads(mode, user_id))))
    posted_ts = list(db.scalars(select(Job.posted_at).where(Job.posted_at >= spark_start, mine)))
    failed_ts = list(db.scalars(select(Job.updated_at).where(Job.status == JobStatus.FAILED, Job.updated_at >= spark_start, mine)))
    pending_ts = list(db.scalars(select(Job.created_at).where(Job.created_at >= spark_start, Job.status.in_(JobStatus.PENDING), mine)))

    def today_yesterday(ts):
        return sum(1 for t in ts if t >= today), sum(1 for t in ts if yesterday <= t < today)

    def delta(a, b):
        if b == 0:
            return None if a == 0 else 100
        return round((a - b) / b * 100)

    def series(ts):
        return _daily_series(ts, today, 10, zone)

    fetched, fetched_y = today_yesterday(fetched_ts)
    published, published_y = today_yesterday(posted_ts)
    failed, failed_y = today_yesterday(failed_ts)
    pending = _count(db, select(func.count(Job.id)).where(Job.status.in_(JobStatus.PENDING), mine))
    processing = _count(db, select(func.count(Job.id)).where(Job.status.in_(JobStatus.PROCESSING | {JobStatus.UPLOADING}), mine))
    podcasts = mode == Mode.PODCASTS

    kpis = [
        {"key": "fetched", "label": "Podcasts detected" if podcasts else "Videos detected", "value": fetched, "delta": delta(fetched, fetched_y), "tone": "primary", "series": series(fetched_ts)},
        {"key": "published", "label": "Clips published" if podcasts else "Published", "value": published, "delta": delta(published, published_y), "tone": "success", "series": series(posted_ts)},
        {"key": "pending", "label": "Pending", "value": pending, "meta": f"{processing} processing", "tone": "warning", "series": series(pending_ts)},
        {"key": "failed", "label": "Failed", "value": failed, "delta": delta(failed, failed_y), "tone": "danger", "series": series(failed_ts)},
    ]

    statuses = Counter(db.scalars(select(Job.status).where(Job.created_at >= today, mine)))
    distribution = {
        "published": sum(statuses[s] for s in JobStatus.PUBLISHED),
        "pending": sum(statuses[s] for s in JobStatus.PENDING),
        "failed": statuses[JobStatus.FAILED],
    }

    accounts = buffer.channels(db, user_id, mode) if user_id else []
    per_account = account_stats(db, today)

    skipped = db.scalars(select(Video).where(Video.status == VideoStatus.SKIPPED, *_uploads(mode, user_id)).order_by(Video.id.desc()).limit(5)).unique().all()
    accepted_today = _count(db, select(func.count(Video.id)).where(Video.created_at >= today, Video.status == VideoStatus.ACCEPTED, *_uploads(mode, user_id)))
    skipped_today = _count(db, select(func.count(Video.id)).where(Video.created_at >= today, Video.status == VideoStatus.SKIPPED, *_uploads(mode, user_id)))
    values = rules.global_values(db, mode, user_id)
    # Each workspace shows its own activity: Podcasts sees what happened to podcasts and their clips, Shorts the rest.
    podcast_log = (ActivityLog.service == "Podcasts") | ActivityLog.job_id.in_(select(Job.id).where(_in(Mode.PODCASTS, user_id)))
    activity_log = select(ActivityLog).where(podcast_log if podcasts else ~podcast_log | ActivityLog.job_id.is_(None) & (ActivityLog.service != "Podcasts"))
    activity_log = activity_log.where(ActivityLog.user_id == user_id)  # a member sees only what concerns them

    return {
        "kpis": kpis,
        "distribution": distribution,
        "recent_activity": [serializers.log(e) for e in db.scalars(activity_log.order_by(ActivityLog.id.desc()).limit(4))],
        "mode": mode,
        "timezone": zone.key,
        "rejections": {
            "items": [serializers.video(v) for v in skipped],
            "removed_today": skipped_today,
            "acceptance_rate": round(accepted_today / (accepted_today + skipped_today) * 100, 1) if (accepted_today + skipped_today) else None,
            "max_duration_seconds": values.get("max_duration_seconds"),
            "min_source_duration_seconds": values.get("min_source_duration_seconds"),
        },
        "accounts": [
            {**buffer.account_ref(a), "posts_today": per_account.get(a.id, {}).get("posts_today", 0), "lifetime_posts": per_account.get(a.id, {}).get("lifetime_posts", 0)}
            for a in accounts
        ],
    }


def performance(db: Session, days: int, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict:
    zone = ZoneInfo(timezone_name(db, user_id))
    today = day_start(db, user_id=user_id)
    start = today - timedelta(days=days - 1)
    posted = list(db.scalars(select(Job.posted_at).where(Job.posted_at >= start, _in(mode, user_id))))
    first = today.astimezone(zone).date() - timedelta(days=days - 1)
    return {"labels": [(first + timedelta(days=i)).strftime("%a %d") for i in range(days)], "values": _daily_series(posted, today, days, zone)}


def daily_report(db: Session, day: date | None = None, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict:
    zone = ZoneInfo(timezone_name(db, user_id))
    start = day_start(db, day, user_id)
    end = start + timedelta(days=1)
    accounts = buffer.channels(db, user_id, mode) if user_id else []
    per_account = account_stats(db, start)

    posted = [t.astimezone(zone) for t in db.scalars(select(Job.posted_at).where(Job.posted_at >= start, Job.posted_at < end, _in(mode, user_id)))]
    failed = [t.astimezone(zone) for t in db.scalars(select(Job.updated_at).where(Job.status == JobStatus.FAILED, Job.updated_at >= start, Job.updated_at < end, _in(mode, user_id)))]
    hourly = [
        {"hour": h * 2, "published": sum(1 for t in posted if h * 2 <= t.hour < h * 2 + 2), "failed": sum(1 for t in failed if h * 2 <= t.hour < h * 2 + 2)}
        for h in range(12)
    ]
    in_day = (Video.created_at >= start, Video.created_at < end, *_uploads(mode, user_id))
    rows = []
    for a in accounts:
        stats = per_account.get(a.id, {})
        rows.append(
            {
                **buffer.account_ref(a),
                "posts_today": stats.get("posts_today", 0),
                "failed_today": stats.get("failed_today", 0),
                "lifetime_posts": stats.get("lifetime_posts", 0),
            }
        )
    return {
        "date": start.astimezone(zone).date().isoformat(),
        "timezone": zone.key,
        "uploaded": len(posted),
        "failed": len(failed),
        "accounts": rows,
        "active_accounts": sum(1 for a in accounts if a.enabled),
        "lifetime_uploads": sum(r["lifetime_posts"] for r in rows),
        "accepted": _count(db, select(func.count(Video.id)).where(*in_day, Video.status == VideoStatus.ACCEPTED)),
        "filtered_out": _count(db, select(func.count(Video.id)).where(*in_day, Video.status == VideoStatus.SKIPPED)),
        "hourly": hourly,
    }


# ---------------------------------------------------------------- Live Status page

STAGES = [
    ("waiting", "Waiting to download", JobStatus.FETCHED),
    ("downloading", "Downloading", JobStatus.DOWNLOADING),
    ("editing", "Editing", JobStatus.RENDERING),
    ("caption", "Writing caption", JobStatus.REWRITING),
    ("review", "Waiting for approval", JobStatus.AWAITING_APPROVAL),
    ("upload_wait", "Waiting to upload", JobStatus.READY),
    ("uploading", "Uploading", JobStatus.UPLOADING),
    ("scheduled", "At Buffer, waiting for its time", JobStatus.SCHEDULED),
]
STAGE_LIMIT = 100


def _status_item(job: Job) -> dict:
    video = job.video
    return {
        "id": job.id,
        "video_id": video.id,
        "title": video.original_title or video.youtube_video_id or f"Video {video.id}",
        "channel": video.channel.display_name if video.channel else None,
        "thumbnail_url": video.thumbnail_url,
        "permalink": video.permalink,
        "duration_sec": video.duration_sec,
        "progress": job.progress,
        "since": job.updated_at,
        "attempts": job.attempts,
        "note": job.error,
        "retry_at": job.next_check_at if job.attempts and job.status in (JobStatus.DOWNLOADING, JobStatus.RENDERING) else None,
        "podcast": video.is_podcast_source,  # a whole podcast being analysed, not a clip
        "clip": {"start": video.clip_start, "end": video.clip_end, "podcast_title": video.parent.original_title if video.parent else ""} if video.parent_id else None,
        "buffer_channel": serializers.buffer.channel_ref(job.buffer_channel),
        "due_at": job.buffer_due_at,
    }


def pipeline_status(db: Session, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict:
    """Everything that is on its way right now, stage by stage, plus how far today's videos have got."""
    mine = _in(mode, user_id)
    stages = []
    for key, label, status in STAGES:
        total = _count(db, select(func.count(Job.id)).where(Job.status == status, mine))
        jobs = db.scalars(select(Job).where(Job.status == status, mine).order_by(Job.updated_at).limit(STAGE_LIMIT)).unique().all()
        stages.append({"key": key, "label": label, "total": total, "items": [_status_item(j) for j in jobs]})

    # Today's videos (a podcast's clips count, the podcast itself does not): how many have passed each step.
    today = day_start(db, user_id=user_id)
    rows = db.execute(
        select(Job.status, Job.posted_at, Video.source_file_path, Video.rendered_file_path, Video.files_deleted_at)
        .join(Video, Job.video_id == Video.id)
        .where(Job.created_at >= today, Video.mode == mode, Video.user_id == user_id, ~((Video.mode == Mode.PODCASTS) & Video.parent_id.is_(None)))
    ).all()
    alive = [r for r in rows if r.status != JobStatus.CANCELLED]
    edited = sum(1 for r in alive if r.rendered_file_path or r.files_deleted_at or r.posted_at)
    downloaded = sum(1 for r in alive if r.source_file_path or r.rendered_file_path or r.files_deleted_at or r.posted_at)
    uploaded = sum(1 for r in alive if r.posted_at)
    failed = sum(1 for r in alive if r.status == JobStatus.FAILED)
    total = len(alive)
    return {
        "mode": mode,
        "timezone": timezone_name(db, user_id),
        "today": {
            "total": total,
            "downloaded": downloaded, "download_left": total - downloaded - sum(1 for r in alive if r.status == JobStatus.FAILED and not r.source_file_path and not r.rendered_file_path),
            "edited": edited, "edit_left": max(0, downloaded - edited - sum(1 for r in alive if r.status == JobStatus.FAILED and r.source_file_path and not r.rendered_file_path)),
            "uploaded": uploaded, "upload_left": sum(1 for r in alive if not r.posted_at and r.status in (JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.UPLOADING, JobStatus.SCHEDULED, JobStatus.REWRITING)),
            "failed": failed,
        },
        "stages": stages,
        "podcasts_analysing": _count(db, select(func.count(Job.id)).where(mine, Job.status.in_([JobStatus.FETCHED, JobStatus.DOWNLOADING]), Job.video_id.in_(select(Video.id).where(Video.mode == Mode.PODCASTS, Video.parent_id.is_(None))))),
    }
