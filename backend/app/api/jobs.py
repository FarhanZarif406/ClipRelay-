from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.integrations.http import ApiError
from app.models import InstagramSource, Job, JobStatus, TikTokAccount, Video
from app.schemas import JobUpdate
from app.services import activity, dispatch, pipeline, serializers

router = APIRouter(tags=["jobs"])

STATUS_GROUPS = {
    "pending": JobStatus.PENDING,
    "published": JobStatus.PUBLISHED,
}


def _get(db, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs")
def list_jobs(
    db: DB,
    _: CurrentUser,
    q: str | None = None,
    status: str | None = None,
    source_id: int | None = None,
    tiktok_account_id: int | None = None,
    period: str | None = Query(None, pattern="^(today|7d|30d)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
):
    stmt = select(Job).join(Video, Job.video_id == Video.id)
    if status:
        statuses = STATUS_GROUPS.get(status, {status})
        stmt = stmt.where(Job.status.in_(statuses))
    if source_id:
        stmt = stmt.where(Video.source_id == source_id)
    if tiktok_account_id:
        stmt = stmt.where(Job.tiktok_account_id == tiktok_account_id)
    if period:
        now = datetime.now(timezone.utc)
        start = {"today": now.replace(hour=0, minute=0, second=0, microsecond=0), "7d": now - timedelta(days=7), "30d": now - timedelta(days=30)}[period]
        stmt = stmt.where(Job.created_at >= start)
    if q:
        term = q.strip().lstrip("@#")
        like = f"%{term}%"
        conditions = [
            Video.original_caption.ilike(like),
            Job.rewritten_caption.ilike(like),
            Job.rewritten_title.ilike(like),
            InstagramSource.username.ilike(like),
            TikTokAccount.username.ilike(like),
        ]
        if term.isdigit():
            conditions.append(Job.id == int(term))
        stmt = (
            stmt.outerjoin(InstagramSource, Video.source_id == InstagramSource.id)
            .outerjoin(TikTokAccount, Job.tiktok_account_id == TikTokAccount.id)
            .where(or_(*conditions))
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    jobs = db.scalars(stmt.order_by(Job.id.desc()).offset((page - 1) * page_size).limit(page_size)).unique().all()
    return {"items": [serializers.job(j) for j in jobs], "total": total}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: DB, _: CurrentUser):
    return serializers.job(_get(db, job_id), detail=True)


@router.patch("/jobs/{job_id}")
def edit_job(job_id: int, body: JobUpdate, db: DB, _: CurrentUser):
    job = _get(db, job_id)
    if job.status not in (JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.FAILED, JobStatus.FETCHED):
        raise HTTPException(409, f"Job can't be edited while {job.status}")
    data = body.model_dump(exclude_unset=True)
    if "tiktok_account_id" in data:
        if job.tiktok_publish_id:
            raise HTTPException(409, "Job was already sent to TikTok")
        account = db.get(TikTokAccount, data["tiktok_account_id"]) if data["tiktok_account_id"] else None
        if data["tiktok_account_id"] and not account:
            raise HTTPException(404, "TikTok account not found")
        clash = db.scalar(select(Job.id).where(Job.video_id == job.video_id, Job.tiktok_account_id == data["tiktok_account_id"], Job.id != job.id))
        if clash:
            raise HTTPException(409, "This video is already assigned to that account")
    if "rewritten_tags" in data and data["rewritten_tags"] is not None:
        data["rewritten_tags"] = [t.strip().lstrip("#") for t in data["rewritten_tags"] if t.strip()]
    for field, value in data.items():
        setattr(job, field, value)
    if "tiktok_account_id" in data:
        job.error = None
        job.next_check_at = None
    db.commit()
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/approve")
def approve(job_id: int, db: DB, user: CurrentUser):
    job = _get(db, job_id)
    try:
        pipeline.approve_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} approved by {user.email}", event="job_approved", job_id=job.id)
    db.commit()
    dispatch.upload_job(job.id)
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: int, db: DB, _: CurrentUser):
    job = _get(db, job_id)
    try:
        status = pipeline.retry_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ApiError as exc:
        raise HTTPException(502, f"Could not verify TikTok status before retrying: {exc}") from exc
    activity.record(db, "Publisher", f"Job #{job.id} retried", event="job_retried", job_id=job.id)
    db.commit()
    {JobStatus.FETCHED: dispatch.rewrite_job, JobStatus.READY: dispatch.upload_job, JobStatus.MONITORING: dispatch.check_job}[status](job.id)
    return serializers.job(job, detail=True)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, db: DB, _: CurrentUser):
    job = _get(db, job_id)
    try:
        pipeline.cancel_job(db, job)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    activity.record(db, "Publisher", f"Job #{job.id} cancelled", event="job_cancelled", job_id=job.id)
    db.commit()
    return serializers.job(job, detail=True)


@router.post("/jobs/process-next")
def process_next(db: DB, _: CurrentUser):
    job = db.scalar(
        select(Job).where(Job.status == JobStatus.READY, Job.tiktok_account_id.is_not(None)).order_by(Job.id).limit(1)
    )
    if not job:
        job = db.scalar(select(Job).where(Job.status == JobStatus.FETCHED).order_by(Job.id).limit(1))
        if not job:
            raise HTTPException(404, "Nothing in the queue is ready to process")
        dispatch.rewrite_job(job.id)
        return {"job_id": job.id, "action": "rewrite"}
    job.next_check_at = None
    db.commit()
    dispatch.upload_job(job.id, True)
    return {"job_id": job.id, "action": "upload"}


@router.get("/videos")
def list_videos(db: DB, _: CurrentUser, status: str | None = None, limit: int = Query(20, ge=1, le=200)):
    stmt = select(Video)
    if status:
        stmt = stmt.where(Video.status == status)
    return [serializers.video(v) for v in db.scalars(stmt.order_by(Video.id.desc()).limit(limit))]
