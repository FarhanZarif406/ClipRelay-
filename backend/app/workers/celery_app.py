from celery import Celery
from celery.signals import worker_process_init

from app.config import get_settings

settings = get_settings()

celery_app = Celery("cliprelay", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    task_routes={
        "app.workers.tasks.upload_job": {"queue": "uploads"},
        "app.workers.tasks.run_source": {"queue": "fetch"},
    },
    task_default_queue="default",
    # Beat only fires the lightweight tick; per-source intervals, upload delays and violation-check
    # times are read from PostgreSQL on every tick, so changing them in the UI needs no restart.
    beat_schedule={
        "scheduler-tick": {"task": "app.workers.tasks.tick", "schedule": float(settings.scheduler_tick_seconds)},
        "refresh-tokens": {"task": "app.workers.tasks.refresh_tokens", "schedule": 15 * 60.0},
        "validate-credentials": {"task": "app.workers.tasks.validate_credentials", "schedule": 24 * 60 * 60.0},
    },
)


@worker_process_init.connect
def _listen_for_credential_changes(**_kwargs) -> None:
    """Each worker process drops its credential/LLM caches when Settings change them."""
    from app.services import credentials

    credentials.start_listener()
