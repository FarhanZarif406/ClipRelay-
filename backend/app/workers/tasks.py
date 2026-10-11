import logging

from app.config import get_settings
from app.db import session_scope
from app.integrations.http import ApiError, AuthError, backoff_delay
from app.models import Channel, Job, JobStatus
from app.services import credential_checks, credentials, detection, pipeline, tokens
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def enqueue(task, *args, countdown: float = 0) -> None:
    """Queue a follow-up task: on Celery, or on the in-process runner when INLINE_WORKER is on."""
    if get_settings().inline_worker:
        from app.services import local_runner

        local_runner.submit(task.name.rsplit(".", 1)[-1], *args, delay=countdown)
    else:
        task.apply_async(args, countdown=countdown or None)


@celery_app.task
def tick() -> dict:
    with session_scope() as db:
        due = pipeline.scheduler_tick(db)
        due["polls"] = detection.due_channels(db)
    for channel_id in due["polls"]:
        enqueue(poll_channel, channel_id)
    for job_id in due["process"]:
        enqueue(process_video, job_id)
    for job_id in due["rewrites"]:
        enqueue(rewrite_job, job_id)
    for job_id, delay in due["uploads"]:
        enqueue(upload_job, job_id, countdown=delay)
    for job_id in due["checks"]:
        enqueue(check_job, job_id)
    return {k: len(v) for k, v in due.items()}


def _start(job_ids: list[int]) -> None:
    """A newly detected video: the download/edit and the caption rewrite run side by side."""
    for job_id in job_ids:
        enqueue(process_video, job_id)
        enqueue(rewrite_job, job_id)


@celery_app.task
def poll_channel(channel_id: int) -> int:
    with session_scope() as db:
        channel = db.get(Channel, channel_id)
        if not channel or not channel.active:
            return 0
        videos = detection.poll_channel(db, channel)
        job_ids = [job.id for job in db.query(Job).filter(Job.video_id.in_([v.id for v in videos]))] if videos else []
    _start(job_ids)
    return len(job_ids)


@celery_app.task(bind=True, max_retries=3)
def discover_video(self, youtube_channel_id: str, video_id: str) -> int | None:
    """A push notification from YouTube."""
    try:
        with session_scope() as db:
            video = detection.discover_by_ids(db, youtube_channel_id, video_id)
            job = db.query(Job).filter(Job.video_id == video.id).first() if video else None
            job_id = job.id if job else None
    except ApiError as exc:
        raise self.retry(exc=exc, countdown=backoff_delay(self.request.retries, base=30))
    if job_id:
        _start([job_id])
    return job_id


@celery_app.task
def process_video(job_id: int) -> str | None:
    with session_scope() as db:
        status = pipeline.process_video(db, job_id)
    if status == JobStatus.READY:
        enqueue(upload_job, job_id)
    return status


@celery_app.task
def rewrite_job(job_id: int) -> str | None:
    with session_scope() as db:
        status = pipeline.rewrite_job(db, job_id)
    if status == JobStatus.READY:
        enqueue(upload_job, job_id)
    return status


@celery_app.task
def upload_job(job_id: int) -> str:
    with session_scope() as db:
        return pipeline.upload_job(db, job_id)


@celery_app.task(bind=True, max_retries=5)
def check_job(self, job_id: int) -> str | None:
    try:
        with session_scope() as db:
            return pipeline.check_job(db, job_id)
    except AuthError:
        return None  # account must be reconnected; the lease re-queues the check later
    except ApiError as exc:
        raise self.retry(exc=exc, countdown=backoff_delay(self.request.retries, base=60))


@celery_app.task
def refresh_tokens() -> dict:
    with session_scope() as db:
        return tokens.refresh_all(db)


@celery_app.task
def renew_subscriptions() -> dict:
    """Hourly: YouTube push subscriptions expire, so each is renewed before it lapses."""
    with session_scope() as db:
        return detection.renew_subscriptions(db)


@celery_app.task
def cleanup_files() -> int:
    """Daily: delete source and rendered files past the retention period."""
    with session_scope() as db:
        return pipeline.cleanup_files(db)


@celery_app.task
def validate_credentials() -> dict:
    """Daily: re-check stored credentials and AI models, alert on failures."""
    with session_scope() as db:
        result = credential_checks.run_daily(db)
    credentials.changed()
    return result
