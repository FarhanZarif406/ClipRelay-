"""Runs the scheduler and the pipeline inside the API process (INLINE_WORKER=true), for installs without Redis.

Production uses Celery (worker + beat). This runner executes the very same task functions on a small thread
pool, with a background thread standing in for beat.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings

log = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="cliprelay-task")
_started = False
_lock = threading.Lock()
DAILY = 24 * 60 * 60.0
PERIODIC = {"refresh_tokens": 15 * 60.0, "renew_subscriptions": 60 * 60.0, "cleanup_files": DAILY, "validate_credentials": DAILY}


def _run(name: str, *args) -> None:
    from app.workers import tasks

    try:
        getattr(tasks, name)(*args)  # the task function itself; its follow-ups come back through `submit`
    except Exception:
        log.exception("inline task %s%s failed", name, args)


def submit(name: str, *args, delay: float = 0) -> None:
    if delay:
        timer = threading.Timer(delay, _pool.submit, (_run, name, *args))
        timer.daemon = True
        timer.start()
    else:
        _pool.submit(_run, name, *args)


def _loop() -> None:
    interval = max(5, get_settings().scheduler_tick_seconds)
    last = {name: time.monotonic() - period + 60 for name, period in PERIODIC.items()}  # first run after a minute
    while True:
        time.sleep(interval)
        _run("tick")
        now = time.monotonic()
        for name, period in PERIODIC.items():
            if now - last[name] >= period:
                last[name] = now
                submit(name)


def start() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="cliprelay-scheduler", daemon=True).start()
    log.info("inline worker started: the pipeline runs inside the API process")
