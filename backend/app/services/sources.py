"""Source adapters: how the original file of a detected video is obtained.

The pipeline only knows the `SourceAdapter` interface, so the method can be swapped (VIDEO_SOURCE_ADAPTER)
without touching it — for example for an adapter that reads the client's original files from cloud storage.
"""

import os
import tempfile
from typing import Protocol

from app.config import get_settings
from app.integrations import youtube
from app.models import Video
from app.services import media


class SourceError(Exception):
    """A download failed. The message is written for the operator, not a stack trace."""


class SourceAdapter(Protocol):
    name: str

    def download(self, video: Video) -> str:
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


class YtDlpAdapter:
    name = "yt_dlp"

    def download(self, video: Video) -> str:
        try:
            import yt_dlp
        except ImportError as exc:  # pragma: no cover
            raise SourceError("yt-dlp is not installed on the server") from exc
        folder = tempfile.mkdtemp(prefix="cliprelay-src-")
        options = {
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "socket_timeout": 30, "retries": 3,
            "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(folder, "source.%(ext)s"),
            "ffmpeg_location": media.ffmpeg_exe(),
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([video.permalink or youtube.watch_url(video.youtube_video_id or "")])
        except yt_dlp.utils.DownloadError as exc:
            raise SourceError(_readable(str(exc))) from exc
        files = [os.path.join(folder, name) for name in os.listdir(folder) if not name.endswith(".part")]
        if not files or os.path.getsize(files[0]) == 0:
            raise SourceError("The download finished but produced no file")
        return max(files, key=os.path.getsize)


ADAPTERS: dict[str, type] = {YtDlpAdapter.name: YtDlpAdapter}


def get_adapter() -> SourceAdapter:
    name = get_settings().video_source_adapter
    if name not in ADAPTERS:
        raise SourceError(f"Unknown VIDEO_SOURCE_ADAPTER {name!r}")
    return ADAPTERS[name]()
