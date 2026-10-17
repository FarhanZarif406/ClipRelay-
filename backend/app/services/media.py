"""FFmpeg helpers: inspect a file, and render it with an editing look (shape, speed, quality, sound, music, hook text, watermark)."""

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections.abc import Callable
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


# ---------------------------------------------------------------- the look: sizes and placement

MARGIN = 40  # pixels between a watermark and the edge of a Full HD clip
CROP_X = {"left": 0.0, "centre": 0.5, "right": 1.0}
BOLD_FONTS = (
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def default_font() -> str | None:
    """The bold font hook text is drawn with: FONT_FILE when set, else the first system bold font found."""
    return next((f for f in (get_settings().font_file, *BOLD_FONTS) if f and os.path.isfile(f)), None)


def _tidy(value: float) -> float:
    return round(value * 1000) / 1000


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def aspect_parts(aspect: str) -> tuple[int, int]:
    try:
        w, h = (int(x) for x in aspect.split(":"))
    except (ValueError, AttributeError):
        return 9, 16
    return (w, h) if w > 0 and h > 0 else (9, 16)


def output_size(look: dict) -> tuple[int, int]:
    """The finished clip's size: the quality sets the shorter side (1080 or 720), the aspect ratio the other."""
    short = int(look["encoding"]["resolution"].split("x")[0])
    w, h = aspect_parts(look["frame"]["aspect"])
    return (short, _even(short * h / w)) if w <= h else (_even(short * w / h), short)


def source_fit(width: int, height: int, aspect: str) -> str:
    """sides: the source is wider and its sides are cropped. ends: a little narrower, top and bottom cropped.
    whole: the same shape or much narrower (a Short going into a square clip), kept whole with bars."""
    w, h = aspect_parts(aspect)
    ratio = width / height / (w / h)
    if ratio > 1.01:
        return "sides"
    return "ends" if 0.7 <= ratio < 0.99 else "whole"


def hook_scale(look: dict) -> float:
    """Hook sizes are given in pixels of a Full HD clip; at HD they shrink with the picture."""
    return int(look["encoding"]["resolution"].split("x")[0]) / 1080


def hook_font_size(look: dict) -> int:
    return max(8, round(look["hook"]["font_size"] * hook_scale(look)))


def hook_line_height(size: int) -> int:
    return round(size * 1.3)


def hook_box_size(look: dict) -> tuple[int, int, int]:
    """Width, height and corner radius in pixels of the box behind the hook text."""
    width, height = output_size(look)
    box = look["hook"]["box"]
    w, h = _even(width * box["width"] / 100), _even(height * box["height"] / 100)
    return w, h, round(min(w, h) / 2 * min(100, max(0, box["radius"])) / 100)


def wrap_hook_text(text: str, look: dict) -> list[str]:
    """Hook text in lines that fit: inside the box behind it when there is one, else most of the clip's width."""
    width, _ = output_size(look)
    hook, size = look["hook"], hook_font_size(look)
    room = width * hook["box"]["width"] / 100 - size if hook["box"]["enabled"] else width * 0.86
    per_line = max(6, int(room // (size * 0.56)))
    lines: list[str] = []
    line = ""
    for word in text.split():
        if line and len(f"{line} {word}") > per_line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        lines.append(line)
    return lines[:4]


def drawable(text: str) -> str:
    """Hook text without emoji and other symbols a text font has no shape for (they would show as empty boxes)."""
    kept = "".join(ch for ch in text if not (unicodedata.category(ch) in ("So", "Cs", "Co", "Cn") or ord(ch) > 0xFFFF or ch in "‍️"))
    return " ".join(kept.split())


def _filter_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _colour(hex_value: str) -> str:
    return f"0x{hex_value[1:].lower()}" if isinstance(hex_value, str) and len(hex_value) == 7 and hex_value.startswith("#") else "0xffffff"


def _picture_filters(look: dict, width: int, height: int) -> list[str]:
    """Fit the source to the clip's shape, then flip and speed up."""
    out_w, out_h = output_size(look)
    frame = look["frame"]
    w, h = aspect_parts(frame["aspect"])
    zoom = _tidy(frame["zoom"])
    fit = source_fit(width, height, frame["aspect"])
    if fit == "sides":
        filters = [f"crop=ih*{w}/{h}/{zoom}:ih/{zoom}:(iw-ow)*{CROP_X[frame['position']]}:(ih-oh)/2", f"scale={out_w}:{out_h}"]
    elif fit == "ends":
        filters = [f"crop=iw/{zoom}:iw*{h}/{w}/{zoom}:(iw-ow)/2:(ih-oh)/2", f"scale={out_w}:{out_h}"]
    else:
        filters = [f"scale={out_w}:{out_h}:force_original_aspect_ratio=decrease", f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2"]
    filters += adjust_filters(look["adjust"])
    if frame["flip"]:
        filters.append("hflip")
    speed = look["speed"]["speed"]
    if abs(speed - 1.0) > 1e-6:
        filters.append(f"setpts=PTS/{_tidy(speed)}")
    return filters


def adjust_filters(adjust: dict) -> list[str]:
    """Light, colour and detail, as FFmpeg filters. Settings left at 0 add nothing."""
    a = {key: adjust.get(key, 0) for key in ("brightness", "contrast", "highlights", "shadows", "saturation", "warmth", "tint", "hue", "sharpness", "vignette", "grain")}
    out = []
    eq = []
    if a["brightness"]:
        eq.append(f"brightness={_tidy(a['brightness'] / 100 * 0.3)}")
    if a["contrast"]:
        eq.append(f"contrast={_tidy(1 + a['contrast'] / 100 * 0.5)}")
    if a["saturation"]:
        eq.append(f"saturation={_tidy(1 + a['saturation'] / 100)}")
    if eq:
        out.append("eq=" + ":".join(eq))
    if a["shadows"] or a["highlights"]:
        # Shadows lift or deepen the dark quarter of the picture, highlights the bright quarter; black and white stay put.
        low = min(1.0, max(0.0, 0.25 + a["shadows"] / 100 * 0.15))
        high = min(1.0, max(0.0, 0.75 + a["highlights"] / 100 * 0.15))
        out.append(f"curves=all='0/0 0.25/{_tidy(low)} 0.75/{_tidy(high)} 1/1'")
    if a["warmth"] or a["tint"]:
        warm, tint = a["warmth"] / 100 * 0.3, a["tint"] / 100 * 0.3
        out.append(f"colorbalance=rm={_tidy(warm)}:gm={_tidy(-tint)}:bm={_tidy(-warm)}")
    if a["hue"]:
        out.append(f"hue=h={a['hue']}")
    if a["sharpness"]:
        out.append(f"unsharp=5:5:{_tidy(a['sharpness'] / 100 * 1.5)}:5:5:0")
    if a["vignette"]:
        out.append(f"vignette=angle={_tidy(a['vignette'] / 100 * 1.2)}")
    if a["grain"]:
        out.append(f"noise=alls={round(a['grain'] / 100 * 30)}:allf=t+u")
    return out


def _box_filter(look: dict) -> str:
    """The rounded box behind the hook text, as one still picture: clear outside the rounded corners."""
    box = look["hook"]["box"]
    w, h, radius = hook_box_size(look)
    alpha = round(255 * min(1, max(0, box["opacity"])))
    dx, dy = f"abs(X-{w / 2})-{w / 2 - radius}", f"abs(Y-{h / 2})-{h / 2 - radius}"
    a = f"if(gt({dx},0)*gt({dy},0),if(lte(hypot({dx},{dy}),{radius}),{alpha},0),{alpha})" if radius > 0 else str(alpha)
    return f"color=c={_colour(box['color'])}:s={w}x{h}:r=1:d=1,format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{a}'"


def _watermark_place(position: str) -> str:
    x = {"l": f"{MARGIN}", "c": "(W-w)/2", "r": f"W-w-{MARGIN}"}[position[1]]
    y = {"t": f"{MARGIN}", "m": "(H-h)/2", "b": f"H-h-{MARGIN}"}[position[0]]
    return f"{x}:{y}"


def _tempo(look: dict) -> list[str]:
    speed = look["speed"]["speed"]
    if abs(speed - 1.0) < 1e-6:
        steps = []
    elif look["speed"]["keep_pitch"]:
        steps = [atempo_chain(speed)]  # faster, voices at their normal pitch
    else:
        steps = ["aresample=44100", f"asetrate={round(44100 * speed)}", "aresample=44100"]  # like a record played faster
    if look["encoding"]["loudnorm"]:
        steps.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    return steps or ["anull"]


def render_command(src: str, dst: str, look: dict, *, width: int, height: int, duration: float, has_audio: bool,
                   hook_files: list[str] | None = None, font_file: str | None = None, watermark_file: str | None = None,
                   music_file: str | None = None, max_seconds: float | None = None) -> tuple[list[str], float]:
    """Build the FFmpeg command for a look. Returns (command, length of the finished clip in seconds)."""
    speed = look["speed"]["speed"]
    take = min(duration, max_seconds * speed) if max_seconds else duration
    seconds = _tidy(take / speed)
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1"]
    cmd += (["-t", f"{_tidy(take)}"] if max_seconds else []) + ["-i", src]
    sound = "[0:a]" if has_audio and look["encoding"]["keep_audio"] else None
    music = bool(look["music"]["enabled"] and music_file)
    next_input = 1
    silence = None
    if not sound and not music:
        # Silence rather than no sound at all, which some players and upload services refuse.
        silence = next_input
        next_input += 1
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    mark = None
    if look["watermark"]["enabled"] and watermark_file:
        mark = next_input
        next_input += 1
        cmd += ["-i", watermark_file]
    track = None
    if music:
        track = next_input
        next_input += 1
        cmd += ["-stream_loop", "-1", "-i", music_file]  # repeated, so a short track still covers a long clip

    out_w, out_h = output_size(look)
    hook = look["hook"]
    lines = hook_files or []
    show_hook = hook["enabled"] and bool(lines) and bool(font_file)
    shown = f"enable='lt(t,{_tidy(hook['duration'])})'"
    graph: list[str] = []
    state = {"last": "[0:v]", "step": 0}

    def stage(filters: str, source: str | None = None) -> None:
        label = f"[p{state['step']}]"
        state["step"] += 1
        graph.append(f"{source or state['last']}{filters}{label}")
        state["last"] = label

    stage(",".join(_picture_filters(look, width, height)))
    if show_hook and hook["box"]["enabled"]:
        w, h, _ = hook_box_size(look)
        graph.append(f"{_box_filter(look)}[hookbox]")
        x, y = round(out_w * hook["box"]["x"] / 100 - w / 2), round(out_h * hook["box"]["y"] / 100 - h / 2)
        stage(f"overlay={x}:{y}:{shown}", f"{state['last']}[hookbox]")
    if show_hook:
        # Each line is drawn by itself, so every line is centred on the text's position.
        size = hook_font_size(look)
        line_height = hook_line_height(size)
        top = _tidy(len(lines) * line_height / 2)
        border = max(0, round(hook["stroke_width"] * hook_scale(look)))
        stage(",".join(
            f"drawtext=fontfile='{_filter_path(font_file)}':textfile='{_filter_path(f)}':fontsize={size}"
            f":fontcolor={_colour(hook['color'])}:borderw={border}:bordercolor={_colour(hook['stroke_color'])}"
            f":x=w*{_tidy(hook['x'] / 100)}-text_w/2:y=h*{_tidy(hook['y'] / 100)}-{top}+{i * line_height}:{shown}"
            for i, f in enumerate(lines)
        ))
    if mark is not None:
        wm = look["watermark"]
        graph.append(f"[{mark}:v]format=rgba,colorchannelmixer=aa={_tidy(wm['opacity'])},scale={round(out_w * wm['size'] / 100)}:-1[mark]")
        stage(f"overlay={_watermark_place(wm['position'])}", f"{state['last']}[mark]")
    graph[-1] = graph[-1][: graph[-1].rindex("[")] + "[vout]"

    if track is not None:
        fade_out = max(0.0, _tidy(seconds - 1))
        bed = (f"[{track}:a]atrim=0:{seconds},asetpts=PTS-STARTPTS,aresample=44100,volume={_tidy(look['music']['volume'])},"
               f"afade=t=in:d=0.5,afade=t=out:st={fade_out}:d=1")
        if sound:
            graph.append(f"{sound}{','.join(_tempo(look))},aresample=44100[voice]")
            graph.append(f"{bed}[music]")
            graph.append("[voice][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
        else:
            graph.append(f"{bed}[aout]")
    elif sound:
        graph.append(f"{sound}{','.join(_tempo(look))}[aout]")

    audible = bool(sound) or track is not None
    enc = look["encoding"]
    cmd += ["-filter_complex", ";".join(graph), "-map", "[vout]"]
    cmd += ["-map", "[aout]"] if audible else ["-map", f"{silence}:a", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", enc["preset"], "-crf", str(enc["crf"]), "-pix_fmt", "yuv420p", "-r", str(enc["fps"])]
    cmd += ["-threads", str(max(1, get_settings().render_threads))]  # a few edits at once share the processor, and each needs less memory
    cmd += ["-c:a", "aac", "-b:a", f"{enc['audio_bitrate']}k" if audible else "64k"]
    if track is not None or max_seconds:
        cmd += ["-t", str(seconds)]  # the picture decides the length: looping music never makes a clip longer
    return cmd + ["-movflags", "+faststart", dst], seconds


def _ffmpeg_message(stderr: str) -> str:
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    text = lines[-1] if lines else "FFmpeg stopped without an error message"
    lowered = text.lower()
    if "no space left" in lowered:
        return "The disk is full"
    if "invalid data found" in lowered or "moov atom not found" in lowered:
        return "The downloaded file is damaged or incomplete"
    return text[:300]


Progress = Callable[[float], None]  # called with 0–100


@lru_cache
def _nice_exe() -> str | None:
    return shutil.which("nice") if os.name == "posix" else None


def _gentle(cmd: list[str]) -> list[str]:
    """On Linux, edits run at a lower priority: downloads, the website and new-video checks stay quick while they work."""
    nice = _nice_exe()
    return [nice, "-n", "10", *cmd] if nice else cmd


def _run(cmd: list[str], seconds: float, on_progress: Progress | None, timeout: float) -> tuple[int, str]:
    """Run FFmpeg and return (exit code, error text). With `on_progress`, reports how much of the output is written."""
    if on_progress is None or seconds <= 0:
        result = subprocess.run(_gentle(cmd), capture_output=True, text=True, errors="replace", timeout=timeout)
        return result.returncode, result.stderr
    proc = subprocess.Popen(_gentle(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:]), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace")
    errors: list[str] = []
    reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    try:
        for line in proc.stdout:
            if line.startswith(("out_time_us=", "out_time_ms=")):  # both are microseconds
                try:
                    written = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                on_progress(min(99.0, written / seconds * 100))  # may raise to stop the render
            if time.monotonic() > deadline:
                raise subprocess.TimeoutExpired(cmd, timeout)
    except BaseException:
        proc.kill()  # timed out, or stopped by the operator: FFmpeg must not keep running
        proc.wait()
        raise
    proc.wait()
    reader.join(5)
    return proc.returncode, "".join(errors)


@dataclass
class RenderResult:
    path: str
    command: str
    seconds: float
    note: str | None = None  # e.g. "hook_font_missing"
    vertical_source: bool = False


def render(src: str, look: dict, *, hook_text: str | None = None, font_file: str | None = None, watermark_file: str | None = None,
           music_file: str | None = None, max_seconds: float | None = None, on_progress: Progress | None = None) -> RenderResult:
    """Apply a look to `src` and return a new temporary MP4 (H.264 / AAC) with the command that made it."""
    try:
        info = probe(src)
    except ProbeError as exc:
        raise RenderError(str(exc)) from exc
    fd, dst = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    work = tempfile.mkdtemp(prefix="cliprelay-render-")
    note = None
    hook_files: list[str] = []
    font = None
    hook_text = drawable(hook_text or "")
    if look["hook"]["enabled"] and hook_text:
        font = font_file or default_font()
        if font:
            for i, line in enumerate(wrap_hook_text(hook_text, look)):  # one file per line: each is drawn and centred by itself
                path = os.path.join(work, f"hook-{i}.txt")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(line)
                hook_files.append(path)
        else:
            note = "hook_font_missing"
    cmd, seconds = render_command(
        src, dst, look, width=info.width or 1920, height=info.height or 1080, duration=info.duration, has_audio=info.has_audio,
        hook_files=hook_files, font_file=font, watermark_file=watermark_file, music_file=music_file if music_file and os.path.isfile(music_file) else None,
        max_seconds=max_seconds,
    )
    try:
        code, errors = _run(cmd, seconds, on_progress, 1800)
    except FileNotFoundError as exc:
        os.remove(dst)
        raise RenderError("FFmpeg was not found — install FFmpeg on the server") from exc
    except subprocess.TimeoutExpired as exc:
        os.remove(dst)
        raise RenderError("Rendering took longer than 30 minutes and was stopped") from exc
    except BaseException:  # stopped by the operator
        if os.path.exists(dst):
            os.remove(dst)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if code != 0 or os.path.getsize(dst) == 0:
        os.remove(dst)
        raise RenderError(_ffmpeg_message(errors))
    shown = " ".join(f'"{part}"' if " " in part else part for part in cmd)
    return RenderResult(dst, shown, seconds, note, bool(info.width and info.height and info.height > info.width))
