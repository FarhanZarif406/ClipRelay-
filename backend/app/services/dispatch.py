"""Thin wrapper around Celery `.delay()` so API handlers stay testable (tests swap `sent` in for a queue)."""

from app.config import get_settings

sent: list[tuple[str, tuple]] = []


def _send(name: str, *args, **options) -> None:
    if get_settings().environment == "test":
        sent.append((name, args))
        return
    from app.workers import tasks

    getattr(tasks, name).apply_async(args, **options)


def run_source(source_id: int, manual: bool = True) -> None:
    _send("run_source", source_id, manual)


def rewrite_job(job_id: int) -> None:
    _send("rewrite_job", job_id)


def upload_job(job_id: int, ignore_window: bool = False) -> None:
    _send("upload_job", job_id, ignore_window)


def check_job(job_id: int) -> None:
    _send("check_job", job_id)
