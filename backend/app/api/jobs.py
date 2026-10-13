from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser, Workspace
from app.models import BufferChannel, Job, JobStatus, Mode, User, Video
from app.schemas import JobUpdate, RejectIn
from app.security import decode_token
from app.services import activity, detection, dispatch, pipeline, serializers
from app.services.storage import get_storage

router = APIRouter(tags=["jobs"])

STATUS_GROUPS = {
    "pending": JobStatus.PENDING,
    "published": JobStatus.PUBLISHED | {JobStatus.VIOLATED},
    "review": {JobStatus.AWAITING_APPROVAL},
    "failed": {JobStatus.FAILED},
    "cancelled": {JobStatus.CANCELLED},  # stopped or rejected by the operator; can be restarted
    "waiting": {JobStatus.READY, JobStatus.UPLOADING, JobStatus.SCHEDULED},  # approved or automatic, not published yet
    # Everything past the review step: the Published page shows these.
    "outbox": JobStatus.PUBLISHED | {JobStatus.VIOLATED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.READY, JobStatus.UPLOADING, JobStatus.SCHEDULED},
}


def _get(db, job_id: int, user: User) -> Job:
    job = db.get(Job, job_id)
    if not job or job.video.user_id != user.id:  # another member's video does not exist as far as this one can tell
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs")
def list_jobs(
    db: DB,
    user: CurrentUser,
    q: str | None = None,
    status: str | None = None,
    buffer_channel_id: int | None = None,
    channel_id: int | None = None,
    order: str = Query("newest", pattern="^(newest|oldest|posted)$"),
    period: str | None = Query(None, pattern="^(today|7d|30d)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    mode: Workspace = Mode.SHORTS,
):
    stmt = select(Job).join(Video, Job.video_id == Video.id).where(Video.mode == mode, Video.user_id == user.id)
    if status:
        statuses = STATUS_GROUPS.get(status, {status})
        stmt = stmt.where(Job.status.in_(statuses))
    if buffer_channel_id:
        stmt = stmt.where(Job.buffer_channel_id == buffer_channel_id)
    if channel_id:
        stmt = stmt.where(Video.channel_id == channel_id)
    if period:
        now = datetime.now(timezone.utc)
        start = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0), "7d": now - timedelta(days=7), "30d": now - timedelta(days=30)}[period]
        stmt = stmt.where(Job.created_at >= start)
    if q:
        term = q.strip().lstrip("@#")
        like = f"%{term}%"
        conditions = [
            Video.original_caption.ilike(like),
            Video.original_title.ilike(like),
            Job.rewritten_caption.ilike(like),
            Job.rewritten_title.ilike(like),
            BufferChannel.name.ilike(like),
        ]
        if term.isdigit():
            conditions.append(Job.id == int(term))
        stmt = stmt.outerjoin(BufferChannel, Job.buffer_channel_id == BufferChannel.id).where(or_(*conditions))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    ordering = {"newest": Job.id.desc(), "oldest": Job.id.asc(), "posted": func.coalesce(Job.posted_at, Job.updated_at).desc()}[order]
    jobs = db.scalars(stmt.order_by(ordering).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {"items": [serializers.job(j) for j in jobs], "total": total}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: DB, user: CurrentUser):
    return serializers.job(_get(db, job_id, user), detail=True)


@router.patch("/jobs/{job_id}")
def edit_job(job_id: int, body: JobUpdate, db: DB, user: CurrentUser):
    job = _get(db, job_id, user)
    if job.status not in JobStatus.PROCESSING | {JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.FAILED}:
        raise HTTPException(409, f"Job can't be edited while {job.status}")
    data = body.model_dump(exclude_unset=True)
    if "buffer_channel_id" in data:
        if job.buffer_post_id:
            raise HTTPException(409, "Job was already handed to Buffer")
        chosen = db.get(BufferChannel, data["buffer_channel_id"]) if data["buffer_channel_id"] else None
        if data["buffer_channel_id"] and (not chosen or chosen.user_id != user.id or chosen.mode != job.video.mode):
            raise HTTPException(404, "Buffer account not found")
        if chosen and not chosen.enabled:
            raise HTTPException(400, "That Buffer account is switched off")
    if "rewritten_tags" in data and data["rewritten_tags"] is not None:
        data["rewritten_tags"] = [t.strip().lstrip("#") for t in data["rewritten_tags"] if t.strip()]
    for field, value in data.items():
        setattr(job, field, value)
    if "buffer_channel_id" in data:
        job.error = None
        job.next_check_at = None
    db.commit()
    db.refresh(job)  # the account it now points at
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/approve")
def approve(job_id: int, db: DB, user: CurrentUser):
    job = _get(db, job_id, user)
    try:
        pipeline.approve_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} approved by {user.email}", event="job_approved", job_id=job.id)
    db.commit()
    dispatch.upload_job(job.id)
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, db: DB, user: CurrentUser):
    job = _get(db, job_id, user)
    try:
        status = pipeline.retry_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} retried", event="job_retried", job_id=job.id)
    db.commit()
    {
        JobStatus.FETCHED: dispatch.start_job, JobStatus.REWRITING: dispatch.rewrite_job,
        JobStatus.READY: dispatch.upload_job,
    }[status](job.id)
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/reject")
def reject(job_id: int, body: RejectIn, db: DB, user: CurrentUser):
    """Review queue: this video is not published. The reason is kept with the job."""
    job = _get(db, job_id, user)
    try:
        pipeline.reject_job(db, job, body.reason)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} rejected by {user.email}: {job.reject_reason[:120]}", event="job_rejected", job_id=job.id)
    db.commit()
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, db: DB, user: CurrentUser):
    job = _get(db, job_id, user)
    try:
        pipeline.cancel_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} cancelled", event="job_cancelled", job_id=job.id)
    db.commit()
    return serializers.job(job, detail=True)


@router.get("/videos")
def list_videos(db: DB, user: CurrentUser, status: str | None = None, channel_id: int | None = None, limit: int = Query(20, ge=1, le=500), mode: Workspace = Mode.SHORTS):
    stmt = select(Video).where(Video.mode == mode, Video.user_id == user.id, Video.parent_id.is_(None))  # uploads, not the clips cut from them
    if status:
        stmt = stmt.where(Video.status == status)
    if channel_id:
        stmt = stmt.where(Video.channel_id == channel_id)
    return [serializers.video(v) for v in db.scalars(stmt.order_by(Video.id.desc()).limit(limit)).unique()]


@router.post("/videos/{video_id}/process")
def process_anyway(video_id: int, db: DB, user: CurrentUser):
    """Skipped screen: put a held video into the pipeline by hand."""
    video = db.get(Video, video_id)
    if not video or video.user_id != user.id:
        raise HTTPException(404, "Video not found")
    try:
        job = detection.process_anyway(db, video)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    dispatch.start_job(job.id)
    return serializers.job(job, detail=True)


@router.get("/videos/{video_id}/file", include_in_schema=False)
def video_file(video_id: int, token: str, db: DB):
    """The rendered file, for inline playback in the review queue (token from /auth/media-token)."""
    try:
        payload = decode_token(token)
        user = db.get(User, int(payload["sub"])) if payload.get("purpose") == "media" else None
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(401, "Invalid or expired media token")
    video = db.get(Video, video_id)
    if not video or not video.rendered_file_path or video.user_id != user.id:
        raise HTTPException(404, "The rendered file is not available")
    storage = get_storage()
    path = storage.local_path(video.rendered_file_path)
    if path:
        return FileResponse(path, media_type="video/mp4")
    url = storage.url(video.rendered_file_path)
    if not url:
        raise HTTPException(404, "The rendered file is not available")
    return RedirectResponse(url)
