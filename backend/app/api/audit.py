from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.models import Job, JobStatus, Video, Violation, utcnow
from app.services import activity, serializers, workspace_settings

router = APIRouter(tags=["compliance"])

DISPLAY = {
    JobStatus.MONITORING: "Checking",
    JobStatus.CLEAN: "Clear",
    JobStatus.VIOLATED: "Violation",
}


@router.get("/audit")
def audit(db: DB, user: CurrentUser, limit: int = Query(30, ge=1, le=200)):
    now = utcnow()
    mine = Job.video_id.in_(select(Video.id).where(Video.user_id == user.id))
    config = workspace_settings.get(db, "audit")
    hours = sorted(config["check_hours"]) or [24]
    window = hours[-1]
    jobs = db.scalars(
        select(Job)
        .where(Job.status.in_([JobStatus.MONITORING, JobStatus.CLEAN, JobStatus.VIOLATED]), mine)
        .where(Job.posted_at >= now - timedelta(hours=window * 3))
        .order_by(Job.posted_at.desc())
        .limit(limit)
    ).all()
    # Monitoring first, then most recent.
    jobs = sorted(jobs, key=lambda j: (j.status != JobStatus.MONITORING, -(j.posted_at.timestamp() if j.posted_at else 0)))
    items = []
    for job in jobs:
        elapsed = (now - job.posted_at).total_seconds() / 3600 if job.posted_at else 0
        status = DISPLAY.get(job.status, job.status)
        if job.status == JobStatus.MONITORING and job.error:
            status = "Warning"
        items.append(
            {
                **serializers.job(job),
                "display_status": status,
                "elapsed_hours": round(elapsed, 2),
                "hours_left": max(0.0, round(window - elapsed, 2)) if job.status == JobStatus.MONITORING else 0,
                "progress": 100 if job.status != JobStatus.MONITORING else min(100, round(elapsed / window * 100)),
                "checkpoints": [{"label": "Published", "hours": 0, "done": True}]
                + [{"label": f"{h:g}h", "hours": h, "done": job.status != JobStatus.MONITORING or elapsed >= h} for h in hours],
            }
        )
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    published = db.scalar(select(func.count(Job.id)).where(Job.posted_at >= month_start, mine)) or 0
    violations = db.scalar(select(func.count(Violation.id)).where(Violation.detected_at >= month_start, Violation.job_id.in_(select(Job.id).where(mine)))) or 0
    return {
        "items": items,
        "settings": config,
        "compliance_rate": round((1 - violations / published) * 100, 1) if published else None,  # nothing published: no rate yet
        "monitoring": sum(1 for j in jobs if j.status == JobStatus.MONITORING),
    }


@router.get("/violations")
def list_violations(db: DB, user: CurrentUser, unacknowledged: bool = False, limit: int = Query(50, ge=1, le=500)):
    stmt = select(Violation).where(Violation.job_id.in_(select(Job.id).join(Video, Job.video_id == Video.id).where(Video.user_id == user.id)))
    if unacknowledged:
        stmt = stmt.where(Violation.acknowledged.is_(False))
    return [serializers.violation(v) for v in db.scalars(stmt.order_by(Violation.id.desc()).limit(limit))]


@router.post("/violations/{violation_id}/ack")
def acknowledge(violation_id: int, db: DB, user: CurrentUser):
    violation = db.get(Violation, violation_id)
    if not violation or not violation.job or violation.job.video.user_id != user.id:
        raise HTTPException(404, "Violation not found")
    violation.acknowledged = True
    if violation.removal_status == "manual_required":
        violation.removal_status = "removed_manually"
    activity.record(db, "Compliance", f"Violation on job #{violation.job_id} acknowledged by {user.email}", event="violation_ack", job_id=violation.job_id)
    db.commit()
    return serializers.violation(violation)
