import logging
import uuid

from sqlalchemy.orm import Session

from app.models import ActivityLog, Job, JobEvent
from app.services.events import publish

log = logging.getLogger("cliprelay")
LEVELS = {"info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:8]}"


def record(
    db: Session,
    service: str,
    message: str,
    *,
    level: str = "info",
    event: str = "",
    job_id: int | None = None,
    payload: dict | None = None,
    request_id: str | None = None,
) -> ActivityLog:
    """Write an activity-log row (shown in Logs + Recent activity) and push a live event."""
    entry = ActivityLog(
        service=service,
        message=message,
        level=level,
        event=event,
        job_id=job_id,
        payload=payload,
        request_id=request_id or new_request_id(),
    )
    db.add(entry)
    db.flush()
    log.log(LEVELS.get(level, logging.INFO), "[%s] %s", service, message)
    publish("activity", service=service, level=level, event=event, message=message, job_id=job_id)
    return entry


def job_event(db: Session, job: Job, status: str, message: str) -> None:
    """Change a job's status and append a timeline entry for the job drawer."""
    job.status = status
    db.add(JobEvent(job_id=job.id, status=status, message=message))
    log.info("[pipeline] video=%s job=%s stage=%s %s", job.video_id, job.id, status, message)
    db.flush()
    publish("job", job_id=job.id, status=status)
