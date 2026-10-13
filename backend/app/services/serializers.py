"""Model → JSON shapes consumed by the React frontend."""

from app.models import ActivityLog, CaptionStatus, Channel, Job, TikTokAccount, Video, Violation
from app.services.detection import push_status


def initials(handle: str) -> str:
    clean = "".join(ch for ch in handle if ch.isalnum() or ch in "._").replace("_", ".")
    parts = [p for p in clean.split(".") if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return clean[:2].upper() or "?"


def tiktok_ref(account: TikTokAccount | None) -> dict | None:
    if not account:
        return None
    return {"id": account.id, "username": account.username, "color": account.color, "initials": initials(account.username), "status": account.status}


def tiktok_account(a: TikTokAccount, stats: dict | None = None, default_cap: int = 7) -> dict:
    stats = stats or {}
    return {
        **tiktok_ref(a),
        "display_name": a.display_name,
        "avatar_url": a.avatar_url,
        "daily_cap": a.daily_cap or default_cap,
        "daily_cap_override": a.daily_cap,  # None = follows the uploads_per_tiktok_account_per_day rule
        "default_privacy": a.default_privacy,
        "token_expires_at": a.token_expires_at,
        "refresh_expires_at": a.refresh_expires_at,
        "last_error": a.last_error,
        "last_posted_at": a.last_posted_at,
        "created_at": a.created_at,
        "posts_today": stats.get("posts_today", 0),
        "failed_today": stats.get("failed_today", 0),
        "lifetime_posts": stats.get("lifetime_posts", 0),
        "violations": stats.get("violations", 0),
    }


def channel_ref(c: Channel | None) -> dict | None:
    if not c:
        return None
    return {"id": c.id, "display_name": c.display_name, "handle": c.handle, "thumbnail_url": c.thumbnail_url}


def channel(c: Channel, stats: dict | None = None, overrides: int = 0) -> dict:
    stats = stats or {}
    return {
        **channel_ref(c),
        "youtube_channel_id": c.youtube_channel_id,
        "mode": c.mode,
        "url": f"https://www.youtube.com/channel/{c.youtube_channel_id}",
        "active": c.active,
        "default_tiktok_account": tiktok_ref(c.default_tiktok_account),
        "push_status": push_status(c),
        "push_expires_at": c.pubsub_subscription_expires_at,
        "push_error": c.pubsub_error,
        "last_checked_at": c.last_checked_at,
        "last_upload_at": c.last_upload_at,
        "last_error": c.last_error,
        "created_at": c.created_at,
        "videos_published": stats.get("published", 0),
        "videos_detected": stats.get("detected", 0) + stats.get("skipped", 0),
        "videos_skipped": stats.get("skipped", 0),
        "override_count": overrides,
    }


def video(v: Video) -> dict:
    return {
        "id": v.id,
        "youtube_video_id": v.youtube_video_id,
        "channel": channel_ref(v.channel),
        "permalink": v.permalink,
        "has_file": bool(v.rendered_file_path),
        "files_deleted_at": v.files_deleted_at,
        "skip_reason": v.skip_reason,
        "forced": v.forced,
        "mode": v.mode,
        "clip": {
            "start": v.clip_start, "end": v.clip_end, "podcast_id": v.parent_id,
            "podcast_title": v.parent.original_title if v.parent else "", "podcast_url": v.parent.permalink if v.parent else None,
        } if v.parent_id else None,
        "thumbnail_url": v.thumbnail_url,
        "posted_at": v.posted_at,
        "original_title": v.original_title,
        "original_caption": v.original_caption,
        "original_tags": v.original_tags or [],
        "duration_sec": v.duration_sec,
        "status": v.status,
        "rejection_reason": v.rejection_reason,
        "created_at": v.created_at,
    }


def job(j: Job, *, detail: bool = False) -> dict:
    data = {
        "id": j.id,
        "status": j.status,
        "created_at": j.created_at,
        "updated_at": j.updated_at,
        "posted_at": j.posted_at,
        "approval_required": j.approval_required,
        "rewritten_title": j.rewritten_title,
        "rewritten_caption": j.rewritten_caption,
        "rewritten_tags": j.rewritten_tags or [],
        "caption_status": j.caption_status,
        "caption_fallback": j.caption_status == CaptionStatus.FALLBACK,
        "publish_mode": j.publish_mode,
        "reject_reason": j.reject_reason,
        "waiting_for_account": j.status == "ready" and (j.tiktok_account is None or j.tiktok_account.status not in ("active", "expiring")),
        "tiktok_url": f"https://www.tiktok.com/@{j.tiktok_account.username}/video/{j.tiktok_post_id}" if j.tiktok_post_id and j.tiktok_account else None,
        "privacy_level": j.privacy_level,
        "tiktok_post_id": j.tiktok_post_id,
        "error": j.error,
        "progress": j.progress,
        "attempts": j.attempts,
        "violation_reason": j.violation_reason,
        "check_count": j.check_count,
        "next_check_at": j.next_check_at,
        "monitor_until": j.monitor_until,
        "prompt_template_id": j.prompt_template_id,
        "video": video(j.video),
        "tiktok_account": tiktok_ref(j.tiktok_account),
    }
    if detail:
        data["events"] = [{"id": e.id, "status": e.status, "message": e.message, "created_at": e.created_at} for e in j.events]
    return data


def violation(v: Violation) -> dict:
    return {
        "id": v.id,
        "job_id": v.job_id,
        "reason": v.reason,
        "removal_status": v.removal_status,
        "acknowledged": v.acknowledged,
        "detected_at": v.detected_at,
        "tiktok_account": tiktok_ref(v.tiktok_account),
        "title": (v.job.rewritten_title or v.job.video.original_title) if v.job else "",
    }


def log(entry: ActivityLog) -> dict:
    return {
        "id": entry.id,
        "created_at": entry.created_at,
        "level": entry.level,
        "service": entry.service,
        "event": entry.event,
        "message": entry.message,
        "request_id": entry.request_id,
        "job_id": entry.job_id,
        "payload": entry.payload,
    }
