"""Thin wrapper around Celery `.delay()` so API handlers stay testable (tests swap `sent` in for a queue).

With INLINE_WORKER=true the tasks run on a small thread pool inside the API process instead (no Redis).
"""

from app.config import get_settings

sent: list[tuple[str, tuple]] = []


def _send(name: str, *args, **options) -> None:
    settings = get_settings()
    if settings.environment == "test":
        sent.append((name, args))
        return
    if settings.inline_worker:
        from app.services import local_runner

        local_runner.submit(name, *args)
        return
    from app.workers import tasks

    getattr(tasks, name).apply_async(args, **options)


def process_video(job_id: int) -> None:
    _send("process_video", job_id)


def rewrite_job(job_id: int) -> None:
    _send("rewrite_job", job_id)


def start_job(job_id: int) -> None:
    """A new job: the download/edit and the caption rewrite run side by side."""
    process_video(job_id)
    rewrite_job(job_id)


def upload_job(job_id: int) -> None:
    _send("upload_job", job_id)


def poll_channel(channel_id: int) -> None:
    _send("poll_channel", channel_id)


def discover_video(youtube_channel_id: str, video_id: str, title: str | None = None, published: str | None = None) -> None:
    _send("discover_video", youtube_channel_id, video_id, title, published)
