from celery import Celery
from celery.signals import worker_init, worker_process_init

from app.config import get_settings

settings = get_settings()

celery_app = Celery("cliprelay", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    # Downloads and edits have a worker of their own ("media"), so a long edit never holds up the quick work:
    # new-video checks, captions, uploads and the scheduler tick (see docker-compose.yml).
    task_routes={
        "app.workers.tasks.upload_job": {"queue": "uploads"},
        "app.workers.tasks.process_video": {"queue": "media"},
    },
    task_default_queue="default",
    # Beat only fires the lightweight tick; channel polls, retries, upload delays and Buffer checks
    # times are read from PostgreSQL on every tick, so changing them in the UI needs no restart.
    beat_schedule={
        "scheduler-tick": {"task": "app.workers.tasks.tick", "schedule": float(settings.scheduler_tick_seconds)},
        "validate-credentials": {"task": "app.workers.tasks.validate_credentials", "schedule": 24 * 60 * 60.0},
        "renew-subscriptions": {"task": "app.workers.tasks.renew_subscriptions", "schedule": 60 * 60.0},
        "cleanup-files": {"task": "app.workers.tasks.cleanup_files", "schedule": 24 * 60 * 60.0},
        "update-ytdlp": {"task": "app.workers.tasks.update_ytdlp", "schedule": 24 * 60 * 60.0},
        "forget-skipped": {"task": "app.workers.tasks.forget_skipped", "schedule": 60 * 60.0},
    },
)


@worker_process_init.connect
def _listen_for_credential_changes(**_kwargs) -> None:
    """Each worker process drops its credential/LLM caches when Settings change them."""
    from app.services import credentials, downloader

    credentials.start_listener()
    downloader.use_shared_packages()  # a yt-dlp updated from the app is used by every worker process


@worker_init.connect
def _threads_worker(sender=None, **_kwargs) -> None:
    """The media worker runs its tasks in threads (they wait on FFmpeg and downloads, and threads need far less
    memory than processes). Threads start no worker processes, so the setup above is done once here."""
    if "thread" in str(getattr(sender, "pool_cls", "")).lower():
        _listen_for_credential_changes()
