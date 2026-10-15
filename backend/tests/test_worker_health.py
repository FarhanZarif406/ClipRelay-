"""The worker says it is alive and what it sees; a yt-dlp updated from the app reaches every process."""

import os
import shutil
import sys
from datetime import timedelta

from app.models import AppSetting, utcnow
from app.services import downloader


def test_the_worker_checks_in_and_the_page_sees_it(client, auth, db, monkeypatch):
    assert downloader.worker_status() == {"alive": False, "last_seen": None}
    assert client.get("/api/dashboard/nav", headers=auth).json()["worker_alive"] is False

    monkeypatch.setattr(downloader, "js_runtime", lambda: {"name": "deno 2.9.7", "problem": None})
    downloader.worker_beat(inline=False)
    status = downloader.worker_status()
    assert status["alive"] is True and status["js_runtime"] == "deno 2.9.7" and status["cookies"] is False and status["inline"] is False
    assert client.get("/api/dashboard/nav", headers=auth).json()["worker_alive"] is True

    # A worker that stopped checking in a few minutes ago is reported as not running.
    db.expire_all()
    row = db.get(AppSetting, downloader.WORKER_KEY)
    row.value = {**row.value, "at": (utcnow() - timedelta(minutes=10)).isoformat()}
    db.commit()
    assert downloader.worker_status()["alive"] is False


def _fake_update(folder: str, version: str) -> None:
    os.makedirs(os.path.join(folder, "yt_dlp"), exist_ok=True)
    with open(os.path.join(folder, "yt_dlp", "version.py"), "w", encoding="utf-8") as fh:
        fh.write(f"__version__ = '{version}'\n")
    marker = os.path.join(folder, ".updated")
    with open(marker, "w", encoding="utf-8") as fh:
        fh.write(version)
    stamp = os.path.getmtime(marker) + (1 if downloader._shared_loaded == os.path.getmtime(marker) else 0)
    os.utime(marker, (stamp, stamp))


def test_a_newer_shared_yt_dlp_is_put_in_front_and_an_older_one_is_not(monkeypatch):
    folder = downloader.shared_packages()
    monkeypatch.setattr(downloader, "_image_version", "2026.8.19")
    try:
        _fake_update(folder, "2020.1.1")  # older than the image's: the image's own copy keeps being used
        downloader.use_shared_packages()
        assert folder not in sys.path
        _fake_update(folder, "2099.1.1")  # an update made in another container
        downloader.use_shared_packages()
        assert sys.path[0] == folder
    finally:
        if folder in sys.path:
            sys.path.remove(folder)
        for name in [name for name in sys.modules if name.split(".")[0] == "yt_dlp"]:
            del sys.modules[name]  # the real yt-dlp is imported again by whatever needs it next
        shutil.rmtree(folder, ignore_errors=True)
        downloader._shared_loaded = None
