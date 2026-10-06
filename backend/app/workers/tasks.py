import logging

from app.db import session_scope
from app.integrations.http import ApiError, AuthError, backoff_delay
from app.services import credential_checks, credentials, pipeline, tokens
from app.services.events import get_redis
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task
def tick() -> dict:
    with session_scope() as db:
        due = pipeline.scheduler_tick(db)
    for source_id in due["sources"]:
        run_source.delay(source_id)
    for job_id in due["rewrites"]:
        rewrite_job.delay(job_id)
    for job_id, delay in due["uploads"]:
        upload_job.apply_async((job_id,), countdown=delay)
    for job_id in due["checks"]:
        check_job.delay(job_id)
    return {k: len(v) for k, v in due.items()}


@celery_app.task(bind=True, max_retries=3)
def run_source(self, source_id: int, manual: bool = False) -> list[int]:
    lock = get_redis().lock(f"cliprelay:lock:source:{source_id}", timeout=900, blocking=False)
    if not lock.acquire():
        log.info("source %s already running, skipping", source_id)
        return []
    try:
        with session_scope() as db:
            job_ids = pipeline.run_source(db, source_id, manual=manual)
    except AuthError:
        return []  # surfaced on the source row + activity log; retrying won't help
    except ApiError as exc:
        raise self.retry(exc=exc, countdown=backoff_delay(self.request.retries, base=30))
    finally:
        try:
            lock.release()
        except Exception:
            pass
    for job_id in job_ids:
        rewrite_job.delay(job_id)
    return job_ids


@celery_app.task(bind=True, max_retries=4)
def rewrite_job(self, job_id: int) -> str | None:
    try:
        with session_scope() as db:
            status = pipeline.rewrite_job(db, job_id)
    except ApiError as exc:
        if isinstance(exc, AuthError) or self.request.retries >= self.max_retries:
            with session_scope() as db:
                pipeline.mark_failed(db, job_id, f"AI rewrite failed: {exc}")
            return "failed"
        raise self.retry(exc=exc, countdown=backoff_delay(self.request.retries, base=20))
    if status == "ready":
        upload_job.delay(job_id)
    return status


@celery_app.task
def upload_job(job_id: int, ignore_window: bool = False) -> str:
    with session_scope() as db:
        return pipeline.upload_job(db, job_id, ignore_window=ignore_window)


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
def validate_credentials() -> dict:
    """Daily: re-check stored credentials and AI models, alert on failures."""
    with session_scope() as db:
        result = credential_checks.run_daily(db)
    credentials.changed()
    return result
