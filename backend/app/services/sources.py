"""Source adapters: how the original file of a detected video is obtained.

The pipeline only knows the `SourceAdapter` interface, so the method can be swapped (VIDEO_SOURCE_ADAPTER)
without touching it — for example for an adapter that reads the client's original files from cloud storage.
"""

import glob
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from typing import Protocol

import httpx

from app.config import get_settings
from app.integrations import youtube
from app.models import Video
from app.services import downloader, media


log = logging.getLogger(__name__)


class SourceError(Exception):
    """A download failed. The message is written for the operator, not a stack trace."""


Progress = Callable[[float], None]  # called with 0–100


class SourceAdapter(Protocol):
    name: str

    def download(self, video: Video, on_progress: Progress | None = None) -> str:
        """Fetch the original file and return the path of a local temporary copy."""


def _readable(message: str) -> str:
    text = message.replace("ERROR: ", "").strip()
    lowered = text.lower()
    if "sign in to confirm" in lowered or "not a bot" in lowered:
        return "YouTube asked for a sign-in check and blocked the download from this server"
    if "private video" in lowered:
        return "The video is private"
    if "video unavailable" in lowered or "has been removed" in lowered:
        return "The video is unavailable (deleted or blocked)"
    if "members-only" in lowered or "join this channel" in lowered:
        return "The video is for channel members only"
    if "ffmpeg" in lowered and "not" in lowered:
        return "FFmpeg is missing, so the video and audio could not be joined"
    return text[:300]


# Podcast clips: the stream YouTube serves in small pieces (HLS). Only the pieces a clip needs are fetched.
SECTION_FORMAT = "bv*[protocol^=m3u8][vcodec^=avc1]+ba[protocol^=m3u8]/b[protocol^=m3u8]"
SEGMENT_ATTEMPTS = 6
_whole_locks: dict[str, threading.Lock] = {}
_whole_guard = threading.Lock()


def segments_for(playlist: str, start: float, end: float) -> tuple[str | None, list[tuple[float, str]]]:
    """From an HLS playlist, the pieces that cover start–end: (initialisation piece or None, [(starts at, address)])."""
    init, at, duration, out = None, 0.0, None, []
    for line in playlist.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MAP:"):
            found = re.search(r'URI="([^"]+)"', line)
            init = found.group(1) if found else None
        elif line.startswith("#EXTINF:"):
            duration = float(line[8:].split(",")[0])
        elif line and not line.startswith("#") and duration is not None:
            if at + duration > start and at < end:
                out.append((at, line))
            at += duration
            duration = None
    return init, out


def _fetch(client: httpx.Client, url: str) -> bytes:
    """One piece, retried: YouTube's servers drop a connection now and then."""
    error: Exception | None = None
    for attempt in range(SEGMENT_ATTEMPTS):
        try:
            response = client.get(url)
            if response.status_code < 400:
                return response.content
            error = SourceError(f"YouTube answered HTTP {response.status_code} for a piece of the video")
            if response.status_code in (403, 404, 410):
                break  # the address expired or is refused: trying again will not help
        except httpx.TransportError as exc:
            error = exc
        time.sleep(min(8, 1 + attempt))
    raise SourceError(f"A piece of the video could not be downloaded: {str(error)[:200]}")


def _cut(inputs: list[tuple[str, float]], length: float, has_audio_input: bool) -> str:
    """Cut the clip out of the downloaded pieces, exactly at the chosen times. Runs on local files only."""
    fd, out = tempfile.mkstemp(suffix=".mp4", prefix="cliprelay-clip-")
    os.close(fd)
    cmd = [media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for path, offset in inputs:
        cmd += ["-ss", f"{max(0.0, offset):.3f}", "-i", path]
    cmd += ["-t", f"{length:.3f}", "-map", "0:v:0", "-map", "1:a:0?" if has_audio_input else "0:a:0?"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        os.remove(out)
        raise SourceError(f"The clip could not be cut: {exc}") from exc
    if result.returncode != 0 or os.path.getsize(out) == 0:
        os.remove(out)
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        raise SourceError(f"The clip could not be cut: {lines[-1][:200] if lines else 'FFmpeg gave no reason'}")
    return out


class YtDlpAdapter:
    name = "yt_dlp"

    def _yt_dlp(self):
        downloader.use_shared_packages()  # a yt-dlp updated from the app, in any container, is used from here on
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover
            raise SourceError("yt-dlp is not installed on the server") from exc
        return yt_dlp

    def download(self, video: Video, on_progress: Progress | None = None) -> str:
        if video.clip_start is not None and video.clip_end is not None and video.parent is not None:
            return self.download_clip(video, on_progress)
        return self._download_whole(video.permalink or youtube.watch_url(video.youtube_video_id or ""), on_progress)

    def _download_whole(self, url: str, on_progress: Progress | None = None) -> str:
        """Download a whole video: Full HD first, and when YouTube refuses, by every other way of asking in turn."""
        yt_dlp = self._yt_dlp()
        folder = tempfile.mkdtemp(prefix="cliprelay-src-")
        state = {"video_seen": False, "audio_first": False, "best": 0.0}

        def hook(d: dict) -> None:
            # The picture and the sound arrive as two files, in either order; the picture is nearly all of the bytes.
            if d.get("status") != "downloading" or not on_progress:
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            part = min(1.0, (d.get("downloaded_bytes") or 0) / total) if total else 0.0
            if (d.get("info_dict") or {}).get("vcodec") not in (None, "none"):
                state["video_seen"] = True
                value = 5 + part * 88 if state["audio_first"] else part * 92
            elif state["video_seen"]:
                value = 92 + part * 7
            else:
                state["audio_first"] = True
                value = part * 5
            state["best"] = max(state["best"], min(99.0, value))  # never runs backwards
            on_progress(state["best"])

        options = {
            "progress_hooks": [hook],
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "socket_timeout": 30, "retries": 3,
            "format": downloader.SOURCE_FORMAT, "format_sort": downloader.FORMAT_SORT, "concurrent_fragment_downloads": 4, "overwrites": True,
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(folder, "source.%(ext)s"),
            "ffmpeg_location": media.ffmpeg_exe(),
        }
        def fetch(access: dict) -> None:
            state.update(video_seen=False, audio_first=False)  # a fresh attempt starts its files again
            with yt_dlp.YoutubeDL({**options, **access}) as ydl:
                ydl.download([url])

        try:
            downloader.try_each(fetch)
        except downloader.DownloaderError as exc:
            raise SourceError(_readable(str(exc))) from exc
        files = [os.path.join(folder, name) for name in os.listdir(folder) if not name.endswith(".part")]
        if not files or os.path.getsize(files[0]) == 0:
            raise SourceError("The download finished but produced no file")
        return max(files, key=os.path.getsize)

    # ---- podcast clips: a long video is never downloaded whole when only a minute of it is needed

    def download_clip(self, video: Video, on_progress: Progress | None = None) -> str:
        """Return a file holding exactly the clip's section of its podcast."""
        start, end = float(video.clip_start), float(video.clip_end)
        url = youtube.watch_url(video.parent.youtube_video_id or "")
        try:
            return self._clip_from_pieces(url, start, end, on_progress)
        except SourceError as exc:
            log.warning("section download failed for %s (%s); downloading the whole video instead", url, exc)
        return self._clip_from_whole(url, video.parent.youtube_video_id or "", start, end, on_progress)

    def _clip_from_pieces(self, url: str, start: float, end: float, on_progress: Progress | None = None) -> str:
        yt_dlp = self._yt_dlp()
        def look_up(access: dict) -> dict:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 30, "format": SECTION_FORMAT, "format_sort": downloader.FORMAT_SORT, **access}) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = downloader.try_each(look_up)
        except downloader.DownloaderError as exc:
            raise SourceError(_readable(str(exc))) from exc
        formats = info.get("requested_formats") or [info]
        folder = tempfile.mkdtemp(prefix="cliprelay-pieces-")
        inputs: list[tuple[str, float]] = []
        try:
            with httpx.Client(timeout=45, headers=info.get("http_headers") or {}, follow_redirects=True, proxy=downloader.proxy() or None) as client:
                plans = []
                for fmt in formats:
                    playlist_url = fmt.get("url") or ""
                    init, pieces = segments_for(_fetch(client, playlist_url).decode("utf-8", "replace"), start, end)
                    if not pieces:
                        raise SourceError("The video's stream has no pieces for that part of the video")
                    plans.append((playlist_url, init, pieces))
                total, done = sum(len(pieces) for _url, _init, pieces in plans), 0
                for index, (playlist_url, init, pieces) in enumerate(plans):
                    path = os.path.join(folder, f"{index}.ts")
                    with open(path, "wb") as fh:
                        if init:
                            fh.write(_fetch(client, str(httpx.URL(playlist_url).join(init))))
                        for _at, piece in pieces:
                            fh.write(_fetch(client, str(httpx.URL(playlist_url).join(piece))))
                            done += 1
                            if on_progress:
                                on_progress(done / total * 95)  # the last few percent are the exact cut
                    inputs.append((path, start - pieces[0][0]))
            return _cut(inputs, end - start, has_audio_input=len(inputs) > 1)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _clip_from_whole(self, url: str, video_id: str, start: float, end: float, on_progress: Progress | None = None) -> str:
        """Fallback: download the podcast once (kept for a few hours for its other clips) and cut the clip from it."""
        cached = os.path.join(tempfile.gettempdir(), f"cliprelay-podcast-{video_id}.mp4")
        with _whole_guard:
            lock = _whole_locks.setdefault(video_id, threading.Lock())
            for old in glob.glob(os.path.join(tempfile.gettempdir(), "cliprelay-podcast-*.mp4")):
                if time.time() - os.path.getmtime(old) > 6 * 3600 and old != cached:
                    os.remove(old)
        with lock:
            if not os.path.exists(cached):
                shutil.move(self._download_whole(url, on_progress), cached)
        return _cut([(cached, start)], end - start, has_audio_input=False)


ADAPTERS: dict[str, type] = {YtDlpAdapter.name: YtDlpAdapter}


def get_adapter() -> SourceAdapter:
    name = get_settings().video_source_adapter
    if name not in ADAPTERS:
        raise SourceError(f"Unknown VIDEO_SOURCE_ADAPTER {name!r}")
    return ADAPTERS[name]()
