"""Video download + ffprobe/ffmpeg helpers."""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.integrations.http import ApiError, backoff_delay


@dataclass
class ProbeResult:
    duration: float
    width: int | None
    height: int | None


class ProbeError(Exception):
    pass


def download(url: str, *, retries: int = 3) -> str:
    """Stream a remote video into a temp file and return its path."""
    import time

    for attempt in range(retries + 1):
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
                if response.status_code >= 400:
                    raise ApiError(f"Download failed with HTTP {response.status_code}", status=response.status_code)
                with open(path, "wb") as fh:
                    for chunk in response.iter_bytes(1024 * 256):
                        fh.write(chunk)
            return path
        except (httpx.TransportError, ApiError):
            os.remove(path)
            if attempt >= retries:
                raise
            time.sleep(backoff_delay(attempt))
    raise ApiError("unreachable")  # pragma: no cover


def probe(path: str) -> ProbeResult:
    cmd = [
        get_settings().ffprobe_path, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True).stdout
    except FileNotFoundError as exc:
        raise ProbeError("ffprobe binary not found — install FFmpeg") from exc
    except subprocess.CalledProcessError as exc:
        raise ProbeError(f"ffprobe failed: {exc.stderr.strip()[:200]}") from exc
    data = json.loads(out or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise ProbeError("no video stream found")
    duration = data.get("format", {}).get("duration") or video.get("duration")
    if duration is None:
        raise ProbeError("could not determine duration")
    return ProbeResult(float(duration), video.get("width"), video.get("height"))


def extract_audio(path: str) -> str:
    fd, out = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    cmd = [get_settings().ffmpeg_path, "-y", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", out]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        os.remove(out)
        raise ProbeError(f"ffmpeg audio extraction failed: {exc}") from exc
    return out
