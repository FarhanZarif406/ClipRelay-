"""The helper's work: ask ClipRelay for the member's next video, download it, edit it, send the finished video back.

A second thread tells ClipRelay every 30 seconds that this PC is on; after three minutes of silence (off, asleep,
no internet) ClipRelay gives its video to the cloud instead, and refuses a late result, so nothing is made twice.
"""

import logging
import os
import shutil
import threading
import time

from cliprelay_helper import VERSION
from cliprelay_helper.client import Client, NotConnected, ServerError
from cliprelay_helper.download import DownloadError, Stop, download
from cliprelay_helper.editcore import media
from cliprelay_helper.store import Settings, sub
from cliprelay_helper.system import KeepAwake

log = logging.getLogger("cliprelay.helper")
BEAT_EVERY = 30
ASK_EVERY = 10
REPORT_EVERY = 3.0


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = Client(settings)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.lock = threading.Lock()
        self.state = {"stage": "starting", "title": "", "percent": None, "message": "", "online": False, "done_today": 0,
                      "last_error": "", "latest_version": VERSION, "download_windows": "", "download_mac": ""}
        self.listeners: list = []

    # ---- state shown in the tray and the helper window

    def set(self, **changes) -> None:
        with self.lock:
            self.state.update(changes)
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001
                pass

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.state)

    # ---- threads

    def start(self) -> None:
        threading.Thread(target=self._beat_loop, name="beat", daemon=True).start()
        threading.Thread(target=self._work_loop, name="work", daemon=True).start()

    def shutdown(self) -> None:
        self.stop_event.set()
        self.wake.set()

    def _lost(self, message: str) -> None:
        """The server no longer knows this PC: forget its key, so the window asks for a new code."""
        self.settings.update(token="")
        self.set(stage="not_connected", online=False, message=message, title="", percent=None)

    def _beat_loop(self) -> None:
        while not self.stop_event.is_set():
            if self.settings.connected:
                try:
                    answer = self.client.beat(bool(self.settings.get("paused")))
                    account = answer.get("account") or self.settings.get("account")
                    # The account's language, unless it was chosen in the helper's own window.
                    language = self.settings.get("language") if self.settings.get("language_chosen") else (answer.get("language") or self.settings.get("language"))
                    if account != self.settings.get("account") or language != self.settings.get("language"):
                        self.settings.update(account=account, language=language)
                    self.set(online=True, latest_version=answer.get("latest_version") or VERSION,
                             download_windows=answer.get("download_windows") or "", download_mac=answer.get("download_mac") or "")
                except NotConnected as exc:
                    self._lost(str(exc))
                except ServerError as exc:
                    self.set(online=False, message=str(exc))
            self.stop_event.wait(BEAT_EVERY)

    def _work_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.settings.connected:
                self.set(stage="not_connected", title="", percent=None)
                self.wake.wait(5)
                self.wake.clear()
                continue
            if self.settings.get("paused"):
                self.set(stage="paused", title="", percent=None)
                self.wake.wait(5)
                self.wake.clear()
                continue
            try:
                job = self.client.next_job()
            except NotConnected as exc:
                self._lost(str(exc))
                continue
            except ServerError as exc:
                self.set(stage="offline", online=False, message=str(exc), title="", percent=None)
                self.wake.wait(ASK_EVERY)
                self.wake.clear()
                continue
            if not job:
                self.set(stage="idle", online=True, title="", percent=None, message="")
                self.wake.wait(ASK_EVERY)
                self.wake.clear()
                continue
            try:
                with KeepAwake():
                    self._do(job)
            except NotConnected as exc:
                self._lost(str(exc))
            except Exception as exc:  # noqa: BLE001 — one video's trouble never stops the helper
                log.exception("job %s", job.get("job_id"))
                self.set(last_error=str(exc)[:300])

    # ---- one video

    def _reporter(self, job_id: int, stage: str):
        state = {"at": 0.0}

        def report(percent: float) -> None:
            self.set(percent=round(percent))
            if self.stop_event.is_set():
                raise Stop()
            if time.monotonic() - state["at"] < REPORT_EVERY:
                return
            state["at"] = time.monotonic()
            try:
                stop = self.client.progress(job_id, stage, percent)
            except ServerError:
                return  # a missed report never stops the work; three minutes of them would move it on
            if stop:
                raise Stop()

        return report

    def _files(self, job: dict) -> dict:
        """The member's font, watermark and music: kept on this PC, so each is fetched only once."""
        cache = sub("cache")
        out = {}
        for kind, item in (job.get("files") or {}).items():
            name = "".join(ch for ch in item["cache"] if ch.isalnum() or ch in "-_.")
            path = os.path.join(cache, name)
            if not os.path.exists(path):
                self.client.fetch(item["url"], path)
            out[kind] = path
        return out

    def _do(self, job: dict) -> None:
        job_id = job["job_id"]
        folder = os.path.join(sub("work"), f"job-{job_id}")
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder)
        title = job.get("title") or f"Video {job_id}"
        try:
            self.set(stage="downloading", title=title, percent=0, message="")
            self.client.progress(job_id, "download", 0)
            try:
                files = self._files(job)
                source = download(job["url"], folder, short_side=int(job.get("short_side") or 720), clip=job.get("clip"),
                                  on_progress=self._reporter(job_id, "download"), on_status=lambda text: self.set(message=text))
            except DownloadError as exc:
                self.client.failed(job_id, "download", str(exc))
                self.set(last_error=f"{title}: {exc}")
                return
            except ServerError as exc:
                self.client.failed(job_id, "download", str(exc))
                return
            self.set(stage="editing", percent=0, message="")
            if self.client.progress(job_id, "editing", 0):
                raise Stop()
            try:
                result = media.render(
                    source, job["look"], hook_text=job.get("hook_text"), font_file=files.get("font"),
                    watermark_file=files.get("watermark"), music_file=files.get("music"), on_progress=self._reporter(job_id, "editing"),
                )
            except media.RenderError as exc:
                self.client.failed(job_id, "editing", str(exc))
                self.set(last_error=f"{title}: {exc}")
                return
            self.set(stage="sending", percent=99)
            try:
                self.client.send_result(job_id, result.path)
            finally:
                if os.path.exists(result.path):
                    os.remove(result.path)
            with self.lock:
                self.state["done_today"] += 1
            self.set(stage="idle", title="", percent=None)
        except Stop:
            self.set(stage="idle", title="", percent=None, message="The video was paused, stopped or moved on")
        except ServerError as exc:
            self.set(last_error=f"{title}: {exc}")
        finally:
            shutil.rmtree(folder, ignore_errors=True)  # nothing of the video is left on this computer
