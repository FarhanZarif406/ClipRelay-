"""Model → JSON shapes consumed by the React frontend."""

from app.models import ActivityLog, InstagramSource, Job, TikTokAccount, Video, Violation


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


def source_ref(source: InstagramSource | None) -> dict | None:
    if not source:
        return None
    return {"id": source.id, "username": source.username, "color": source.color, "initials": initials(source.username)}


def source(s: InstagramSource) -> dict:
    return {
        **source_ref(s),
        "name": s.name,
        "profile_picture_url": s.profile_picture_url,
        "is_active": s.is_active,
        "refresh_interval_minutes": s.refresh_interval_minutes,
        "next_run_at": s.next_run_at,
        "last_checked_at": s.last_checked_at,
        "last_run_status": s.last_run_status,
        "last_error": s.last_error,
        "approval_mode": s.approval_mode,
        "prompt_template_id": s.prompt_template_id,
        "prompt_template_name": s.prompt_template.name if s.prompt_template else None,
        "videos_found": s.videos_found,
        "token_expires_at": s.token_expires_at,
        "tiktok_accounts": [tiktok_ref(a) for a in s.tiktok_accounts],
    }


def tiktok_account(a: TikTokAccount, stats: dict | None = None) -> dict:
    stats = stats or {}
    return {
        **tiktok_ref(a),
        "display_name": a.display_name,
        "avatar_url": a.avatar_url,
        "daily_cap": a.daily_cap,
        "default_privacy": a.default_privacy,
        "token_expires_at": a.token_expires_at,
        "refresh_expires_at": a.refresh_expires_at,
        "last_error": a.last_error,
        "last_posted_at": a.last_posted_at,
        "created_at": a.created_at,
        "sources": [source_ref(s) for s in a.sources],
        "posts_today": stats.get("posts_today", 0),
        "failed_today": stats.get("failed_today", 0),
        "lifetime_posts": stats.get("lifetime_posts", 0),
        "violations": stats.get("violations", 0),
    }


def video(v: Video) -> dict:
    return {
        "id": v.id,
        "ig_media_id": v.ig_media_id,
        "permalink": v.permalink,
        "thumbnail_url": v.thumbnail_url,
        "posted_at": v.posted_at,
        "original_title": v.original_title,
        "original_caption": v.original_caption,
        "original_tags": v.original_tags or [],
        "duration_sec": v.duration_sec,
        "detected_language": v.detected_language,
        "language_confidence": v.language_confidence,
        "status": v.status,
        "rejection_reason": v.rejection_reason,
        "created_at": v.created_at,
        "source": source_ref(v.source),
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
        "privacy_level": j.privacy_level,
        "tiktok_post_id": j.tiktok_post_id,
        "error": j.error,
        "violation_reason": j.violation_reason,
        "check_count": j.check_count,
        "next_check_at": j.next_check_at,
        "monitor_until": j.monitor_until,
        "prompt_template_id": j.prompt_template_id,
        "video": video(j.video),
        "source": source_ref(j.video.source),
        "tiktok_account": tiktok_ref(j.tiktok_account),
    }
    if detail:
        data["events"] = [{"id": e.id, "status": e.status, "message": e.message, "created_at": e.created_at} for e in j.events]
        data["video"]["transcript"] = j.video.transcript
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
