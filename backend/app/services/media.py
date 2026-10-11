"""FFmpeg helpers: inspect a file and apply the two edits (speed-up and horizontal flip)."""

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache

from app.config import get_settings


@dataclass
class ProbeResult:
    duration: float
    width: int | None
    height: int | None
    has_audio: bool = True


class ProbeError(Exception):
    pass


class RenderError(Exception):
    """An edit failed. The message is written for the operator, not a stack trace."""


@lru_cache
def ffmpeg_exe() -> str:
    """The configured FFmpeg binary, or the copy bundled with `imageio-ffmpeg` when none is on the PATH."""
    configured = get_settings().ffmpeg_path
    found = shutil.which(configured)
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # not installed, or no binary for this platform
        return configured


DURATION_RE = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
VIDEO_RE = re.compile(r"Stream #\S+ Video: .*?\b(\d{2,5})x(\d{2,5})\b")


def probe(path: str) -> ProbeResult:
    """Read duration, size and whether there is sound, from FFmpeg's description of the file."""
    try:
        out = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True, errors="replace", timeout=60).stderr
    except FileNotFoundError as exc:
        raise ProbeError("FFmpeg was not found — install FFmpeg on the server") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("FFmpeg took too long to read the file") from exc
    video = VIDEO_RE.search(out)
    duration = DURATION_RE.search(out)
    if not video:
        raise ProbeError("The file has no video stream")
    if not duration:
        raise ProbeError("Could not read the video's duration")
    hours, minutes, seconds = duration.groups()
    total = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return ProbeResult(total, int(video.group(1)), int(video.group(2)), bool(re.search(r"Stream #\S+ Audio:", out)))


def atempo_chain(speed: float) -> str:
    """`atempo` accepts 0.5–2.0 per filter, so larger changes are chained."""
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    parts.append(f"atempo={remaining:.4f}")
    return ",".join(parts)


def render_command(src: str, dst: str, *, speed: float, flip: bool, keep_audio: bool, has_audio: bool) -> list[str]:
    """Build the FFmpeg command. Streams that need no change are copied, not re-encoded."""
    faster = abs(speed - 1.0) > 1e-6
    filters = (["hflip"] if flip else []) + ([f"setpts=PTS/{speed:.4f}"] if faster else [])
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-map", "0:v:0"]
    if filters:
        # Same resolution and frame rate as the source; CRF 20 leaves headroom for TikTok's own re-encode.
        cmd += ["-vf", ",".join(filters), "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
    else:
        cmd += ["-c:v", "copy"]
    if keep_audio and has_audio:
        cmd += ["-map", "0:a:0"]
        cmd += ["-af", atempo_chain(speed), "-c:a", "aac", "-b:a", "192k"] if faster else ["-c:a", "copy"]
    else:
        cmd += ["-an"]
    return cmd + ["-movflags", "+faststart", dst]


def _ffmpeg_message(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    text = lines[-1] if lines else "FFmpeg stopped without an error message"
    lowered = text.lower()
    if "no space left" in lowered:
        return "The disk is full"
    if "invalid data found" in lowered or "moov atom not found" in lowered:
        return "The downloaded file is damaged or incomplete"
    return text[:300]


def render(src: str, *, speed: float, flip: bool, keep_audio: bool) -> str:
    """Apply the edits to `src` and return the path of a new temporary MP4 (H.264 / AAC)."""
    try:
        info = probe(src)
    except ProbeError as exc:
        raise RenderError(str(exc)) from exc
    fd, dst = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    cmd = render_command(src, dst, speed=speed, flip=flip, keep_audio=keep_audio, has_audio=info.has_audio)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=1800)
    except FileNotFoundError as exc:
        os.remove(dst)
        raise RenderError("FFmpeg was not found — install FFmpeg on the server") from exc
    except subprocess.TimeoutExpired as exc:
        os.remove(dst)
        raise RenderError("Rendering took longer than 30 minutes and was stopped") from exc
    if result.returncode != 0 or os.path.getsize(dst) == 0:
        os.remove(dst)
        raise RenderError(_ffmpeg_message(result.stderr))
    return dst
