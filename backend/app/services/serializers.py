"""Model → JSON shapes consumed by the React frontend."""

from app.models import ActivityLog, CaptionStatus, Channel, Job, Video
from sqlalchemy.orm import object_session

from app.services import buffer
from app.services.detection import push_detail, push_status


def initials(handle: str) -> str:
    clean = "".join(ch for ch in handle if ch.isalnum() or ch in "._").replace("_", ".")
    parts = [p for p in clean.split(".") if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return clean[:2].upper() or "?"


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
        "push_status": push_status(c),
        "push_expires_at": c.pubsub_subscription_expires_at,
        "push_error": c.pubsub_error,
        "push_detail": push_detail(c),
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
    session = object_session(j)
    connected = session is None or buffer.uses_buffer(session, j.video.user_id)
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
        "waiting_for_account": j.status == "ready" and not connected,  # no Buffer key saved yet
        "post_url": j.buffer_link,
        "buffer_channel": buffer.channel_ref(j.buffer_channel),
        "buffer_due_at": j.buffer_due_at,
        "error": j.error,
        "progress": j.progress,
        "attempts": j.attempts,
        "next_check_at": j.next_check_at,
        "prompt_template_id": j.prompt_template_id,
        "video": video(j.video),
    }
    if detail:
        data["events"] = [{"id": e.id, "status": e.status, "message": e.message, "created_at": e.created_at} for e in j.events]
    return data


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
