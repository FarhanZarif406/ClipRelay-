"""Aggregations for the Dashboard, Daily Report, sidebar badges and account cards."""

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    ActivityLog,
    InstagramSource,
    Job,
    JobStatus,
    TikTokAccount,
    TikTokStatus,
    Video,
    VideoStatus,
    Violation,
    utcnow,
)
from app.services import serializers, workspace_settings
from app.services.pipeline import start_of_day


def _count(db: Session, stmt) -> int:
    return db.scalar(stmt) or 0


def _daily_series(timestamps: list[datetime], end_day: datetime, days: int) -> list[int]:
    counts = Counter(ts.date() for ts in timestamps if ts)
    return [counts.get((end_day - timedelta(days=days - 1 - i)).date(), 0) for i in range(days)]


def account_stats(db: Session, day: datetime | None = None) -> dict[int, dict]:
    start = start_of_day(day)
    end = start + timedelta(days=1)
    out: dict[int, dict] = {}

    def put(rows, key):
        for account_id, count in rows:
            if account_id is not None:
                out.setdefault(account_id, {})[key] = count

    put(db.execute(select(Job.tiktok_account_id, func.count()).where(Job.posted_at >= start, Job.posted_at < end).group_by(Job.tiktok_account_id)), "posts_today")
    put(db.execute(select(Job.tiktok_account_id, func.count()).where(Job.status == JobStatus.FAILED, Job.updated_at >= start, Job.updated_at < end).group_by(Job.tiktok_account_id)), "failed_today")
    put(db.execute(select(Job.tiktok_account_id, func.count()).where(Job.posted_at.is_not(None)).group_by(Job.tiktok_account_id)), "lifetime_posts")
    put(db.execute(select(Violation.tiktok_account_id, func.count()).group_by(Violation.tiktok_account_id)), "violations")
    return out


def nav(db: Session) -> dict:
    now = utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return {
        "pending_jobs": _count(db, select(func.count(Job.id)).where(Job.status.in_(JobStatus.PENDING))),
        "unacknowledged_violations": _count(db, select(func.count(Violation.id)).where(Violation.acknowledged.is_(False))),
        "monthly_jobs": _count(db, select(func.count(Job.id)).where(Job.created_at >= month_start)),
        "monthly_quota": get_settings().monthly_job_quota,
        "reset_in_days": (next_month - now).days + 1,
        "onboarding_completed": workspace_settings.get(db, "onboarding")["completed"],
        "active_sources": _count(db, select(func.count(InstagramSource.id)).where(InstagramSource.is_active.is_(True))),
        "tiktok_accounts": _count(db, select(func.count(TikTokAccount.id))),
    }


def summary(db: Session) -> dict:
    now = utcnow()
    today = start_of_day(now)
    yesterday = today - timedelta(days=1)
    spark_start = today - timedelta(days=9)

    fetched_ts = list(db.scalars(select(Video.created_at).where(Video.created_at >= spark_start)))
    posted_ts = list(db.scalars(select(Job.posted_at).where(Job.posted_at >= spark_start)))
    failed_ts = list(db.scalars(select(Job.updated_at).where(Job.status == JobStatus.FAILED, Job.updated_at >= spark_start)))
    violation_ts = list(db.scalars(select(Violation.detected_at).where(Violation.detected_at >= spark_start)))
    pending_ts = list(db.scalars(select(Job.created_at).where(Job.created_at >= spark_start, Job.status.in_(JobStatus.PENDING))))

    def today_yesterday(ts):
        return sum(1 for t in ts if t >= today), sum(1 for t in ts if yesterday <= t < today)

    def delta(a, b):
        if b == 0:
            return None if a == 0 else 100
        return round((a - b) / b * 100)

    fetched, fetched_y = today_yesterday(fetched_ts)
    published, published_y = today_yesterday(posted_ts)
    failed, failed_y = today_yesterday(failed_ts)
    removed, _ = today_yesterday(violation_ts)
    pending = _count(db, select(func.count(Job.id)).where(Job.status.in_(JobStatus.PENDING)))
    processing = _count(db, select(func.count(Job.id)).where(Job.status.in_([JobStatus.REWRITING, JobStatus.UPLOADING])))

    kpis = [
        {"key": "fetched", "label": "Videos fetched", "value": fetched, "delta": delta(fetched, fetched_y), "tone": "primary", "series": _daily_series(fetched_ts, today, 10)},
        {"key": "published", "label": "Published", "value": published, "delta": delta(published, published_y), "tone": "success", "series": _daily_series(posted_ts, today, 10)},
        {"key": "pending", "label": "Pending", "value": pending, "meta": f"{processing} processing", "tone": "warning", "series": _daily_series(pending_ts, today, 10)},
        {"key": "failed", "label": "Failed", "value": failed, "delta": delta(failed, failed_y), "tone": "danger", "series": _daily_series(failed_ts, today, 10)},
        {"key": "removed", "label": "Removed by audit", "value": removed, "meta": f"{(removed / published * 100) if published else 0:.1f}% rate", "tone": "neutral", "series": _daily_series(violation_ts, today, 10)},
    ]

    statuses = Counter(db.scalars(select(Job.status).where(Job.created_at >= today)))
    distribution = {
        "published": sum(statuses[s] for s in JobStatus.PUBLISHED),
        "pending": sum(statuses[s] for s in JobStatus.PENDING),
        "failed": statuses[JobStatus.FAILED],
        "removed": statuses[JobStatus.VIOLATED],
    }

    active_sources = db.scalars(
        select(InstagramSource).where(InstagramSource.is_active.is_(True)).order_by(InstagramSource.next_run_at.asc().nulls_first())
    ).all()
    next_source = active_sources[0] if active_sources else None
    policy = workspace_settings.get(db, "policy")

    accounts = db.scalars(select(TikTokAccount).order_by(TikTokAccount.id)).all()
    per_account = account_stats(db)
    attention = [
        {"username": a.username, "status": a.status, "refresh_expires_at": a.refresh_expires_at}
        for a in accounts
        if a.status in (TikTokStatus.EXPIRING, TikTokStatus.EXPIRED, TikTokStatus.REVOKED)
    ]

    rejected = db.scalars(select(Video).where(Video.status == VideoStatus.REJECTED).order_by(Video.id.desc()).limit(5)).all()
    accepted_today = _count(db, select(func.count(Video.id)).where(Video.created_at >= today, Video.status == VideoStatus.ACCEPTED))
    rejected_today = _count(db, select(func.count(Video.id)).where(Video.created_at >= today, Video.status == VideoStatus.REJECTED))

    return {
        "kpis": kpis,
        "distribution": distribution,
        "attention": attention,
        "unacknowledged_violations": _count(db, select(func.count(Violation.id)).where(Violation.acknowledged.is_(False))),
        "recent_activity": [serializers.log(e) for e in db.scalars(select(ActivityLog).order_by(ActivityLog.id.desc()).limit(4))],
        "next_run": {
            "at": next_source.next_run_at if next_source else None,
            "interval_minutes": next_source.refresh_interval_minutes if next_source else None,
            "paused": policy["automations_paused"],
            "active_sources": len(active_sources),
            "sources": [serializers.source_ref(s) for s in active_sources[:3]],
        },
        "rejections": {
            "items": [serializers.video(v) for v in rejected],
            "removed_today": rejected_today,
            "acceptance_rate": round(accepted_today / (accepted_today + rejected_today) * 100, 1) if (accepted_today + rejected_today) else None,
            "language_gate_enabled": policy["language_gate_enabled"],
            "allowed_languages": policy["allowed_languages"],
        },
        "accounts": [
            {**serializers.tiktok_ref(a), "posts_today": per_account.get(a.id, {}).get("posts_today", 0), "lifetime_posts": per_account.get(a.id, {}).get("lifetime_posts", 0)}
            for a in accounts
        ],
    }


def performance(db: Session, days: int) -> dict:
    today = start_of_day()
    start = today - timedelta(days=days - 1)
    posted = list(db.scalars(select(Job.posted_at).where(Job.posted_at >= start)))
    series = _daily_series(posted, today, days)
    labels = [(start + timedelta(days=i)).strftime("%a %d") for i in range(days)]
    return {"labels": labels, "values": series}


def daily_report(db: Session, day: datetime) -> dict:
    start = start_of_day(day)
    end = start + timedelta(days=1)
    accounts = db.scalars(select(TikTokAccount).order_by(TikTokAccount.id)).all()
    per_account = account_stats(db, start)

    posted = list(db.scalars(select(Job.posted_at).where(Job.posted_at >= start, Job.posted_at < end)))
    failed = list(db.scalars(select(Job.updated_at).where(Job.status == JobStatus.FAILED, Job.updated_at >= start, Job.updated_at < end)))
    hourly = [
        {"hour": h * 2, "published": sum(1 for t in posted if h * 2 <= t.hour < h * 2 + 2), "failed": sum(1 for t in failed if h * 2 <= t.hour < h * 2 + 2)}
        for h in range(12)
    ]
    languages = Counter(
        db.scalars(select(Video.detected_language).where(Video.created_at >= start, Video.created_at < end, Video.status == VideoStatus.ACCEPTED))
    )
    filtered = _count(db, select(func.count(Video.id)).where(Video.created_at >= start, Video.created_at < end, Video.status == VideoStatus.REJECTED))
    rows = []
    for a in accounts:
        stats = per_account.get(a.id, {})
        rows.append(
            {
                **serializers.tiktok_ref(a),
                "sources": len(a.sources),
                "posts_today": stats.get("posts_today", 0),
                "failed_today": stats.get("failed_today", 0),
                "lifetime_posts": stats.get("lifetime_posts", 0),
            }
        )
    return {
        "date": start.date().isoformat(),
        "uploaded": len(posted),
        "failed": len(failed),
        "accounts": rows,
        "active_accounts": sum(1 for a in accounts if a.status in (TikTokStatus.ACTIVE, TikTokStatus.EXPIRING)),
        "lifetime_uploads": sum(r["lifetime_posts"] for r in rows),
        "accepted": sum(languages.values()),
        "accepted_by_language": {k or "n/a": v for k, v in languages.items()},
        "filtered_out": filtered,
        "hourly": hourly,
    }
