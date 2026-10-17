"""Downloading a video from YouTube over the member's own internet (no cookies, no proxy: a home connection needs neither)."""

import os
from collections.abc import Callable

from cliprelay_helper.editcore import media
from cliprelay_helper.system import js_runtimes

# Tried in turn when YouTube refuses one way of asking (the same choices the server tries).
PLAYER_CLIENTS = ["", "web_safari", "mweb", "tv"]


class DownloadError(Exception):
    pass


class Stop(Exception):
    """The video was paused, stopped or moved on while it downloaded."""


def source_format(short_side: int) -> tuple[str, list[str]]:
    """At most `short_side` on the short side (720 Fast mode, 1080 Full HD); the same choice as the server's."""
    long_side = round(short_side * 16 / 9)
    cap = f"[width<={long_side}][height<={long_side}]"
    capped = [f"bv*[vcodec^=avc1][protocol=https]{cap}+ba[ext=m4a]", f"bv*[protocol=https]{cap}+ba", f"bv*{cap}+ba", f"b{cap}"]
    return "/".join(capped + ["wv*+ba", "w"]), [f"res:{short_side}"]


def readable(message: str) -> str:
    text = message.replace("ERROR: ", "").strip()
    low = text.lower()
    if "sign in to confirm" in low or "not a bot" in low:
        return "YouTube asked for a sign-in check on this computer's connection"
    if "private video" in low:
        return "The video is private"
    if "video unavailable" in low or "has been removed" in low:
        return "The video is unavailable (deleted or blocked)"
    if "members-only" in low or "join this channel" in low:
        return "The video is for channel members only"
    return text[:300]


def download(url: str, folder: str, *, short_side: int, clip: dict | None, on_progress: Callable[[float], None], on_status=None) -> str:
    import yt_dlp
    from yt_dlp.utils import download_range_func

    chosen_format, chosen_sort = source_format(short_side)
    state = {"best": 0.0, "stop": None}

    def hook(d: dict) -> None:
        if d.get("status") != "downloading":
            return
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        part = min(1.0, (d.get("downloaded_bytes") or 0) / total) if total else 0.0
        video = (d.get("info_dict") or {}).get("vcodec") not in (None, "none")
        state["best"] = max(state["best"], min(99.0, part * (92 if video else 99)))
        try:
            on_progress(state["best"])
        except Stop as exc:
            state["stop"] = exc
            raise

    options = {
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "socket_timeout": 30, "retries": 3,
        "format": chosen_format, "format_sort": chosen_sort, "merge_output_format": "mp4", "concurrent_fragment_downloads": 4,
        "outtmpl": os.path.join(folder, "source.%(ext)s"), "overwrites": True, "progress_hooks": [hook],
        "ffmpeg_location": media.ffmpeg_exe(), "js_runtimes": js_runtimes(on_status),
    }
    if clip:
        # A podcast clip: only its part of the video is fetched, cut exactly at the chosen times.
        options["download_ranges"] = download_range_func(None, [(float(clip["start"]), float(clip["end"]))])
        options["force_keyframes_at_cuts"] = True
    failures = []
    for client in PLAYER_CLIENTS:
        attempt = dict(options)
        if client:
            attempt["extractor_args"] = {"youtube": {"player_client": [client]}}
        try:
            with yt_dlp.YoutubeDL(attempt) as ydl:
                ydl.download([url])
        except Stop:
            raise
        except yt_dlp.utils.DownloadError as exc:
            if state["stop"]:
                raise state["stop"] from exc
            failures.append(readable(str(exc)))
            if "private" in failures[-1] or "unavailable" in failures[-1] or "members only" in failures[-1]:
                break  # no other way of asking will help
            continue
        files = [os.path.join(folder, name) for name in os.listdir(folder) if name.startswith("source.") and not name.endswith(".part")]
        if files and os.path.getsize(max(files, key=os.path.getsize)) > 0:
            return max(files, key=os.path.getsize)
        failures.append("The download finished but produced no file")
    raise DownloadError(failures[0] if failures else "The video could not be downloaded")
