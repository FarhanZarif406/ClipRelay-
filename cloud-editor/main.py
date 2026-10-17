"""ClipRelay's cloud editor, run on Google Cloud Run.

ClipRelay sends one video's edit: links to the original and the member's files (font, watermark, music), the look
and the hook line. This fetches them, runs the very same FFmpeg edit the server would (app/services/media.py,
copied from the backend when the image is built), reports how far it is, and sends the finished video back.
Nothing is kept: every edit works in a folder of its own that is removed afterwards.

Cloud Run itself checks who calls: only ClipRelay's service account may (no public access).
"""

import os
import shutil
import subprocess
import tempfile
import time

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services import media

VERSION = "1.0.0"
PROGRESS_EVERY = 3.0
app = FastAPI(title="ClipRelay cloud editor", docs_url=None, redoc_url=None)


class Stopped(Exception):
    """ClipRelay says the video was paused or cancelled meanwhile."""


class FileLink(BaseModel):
    url: str
    ext: str = ""


class RenderIn(BaseModel):
    job: int
    look: dict
    hook_text: str | None = None
    files: dict[str, FileLink]
    progress_url: str
    result_url: str


def _ffmpeg_version() -> str:
    try:
        out = subprocess.run([media.ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=20).stdout
        return out.splitlines()[0][:80] if out else "FFmpeg"
    except (OSError, subprocess.TimeoutExpired):
        return "FFmpeg missing"


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "ffmpeg": _ffmpeg_version()}


def _fetch(client: httpx.Client, url: str, path: str) -> None:
    with client.stream("GET", url) as response:
        if response.status_code != 200:
            raise httpx.HTTPError(f"ClipRelay answered HTTP {response.status_code} for a file of this video")
        with open(path, "wb") as fh:
            for chunk in response.iter_bytes(1024 * 1024):
                fh.write(chunk)


@app.post("/render")
def render(body: RenderIn):
    work = tempfile.mkdtemp(prefix="edit-")
    try:
        with httpx.Client(timeout=httpx.Timeout(120, read=300), follow_redirects=True) as client:
            paths = {}
            for name, link in body.files.items():
                ext = link.ext if link.ext.startswith(".") and len(link.ext) <= 6 else ""
                paths[name] = os.path.join(work, f"{name}{ext}")
                _fetch(client, link.url, paths[name])
            if "source" not in paths:
                return JSONResponse({"error": "No video was sent to edit"}, status_code=400)
            state = {"at": 0.0}

            def on_progress(percent: float) -> None:
                if time.monotonic() - state["at"] < PROGRESS_EVERY:
                    return
                state["at"] = time.monotonic()
                try:
                    answer = client.post(body.progress_url, json={"percent": round(percent, 1)}, timeout=20).json()
                except (httpx.HTTPError, ValueError):
                    return  # a missed report never stops the edit
                if answer.get("stop"):
                    raise Stopped()

            result = media.render(
                paths["source"], body.look, hook_text=body.hook_text, font_file=paths.get("font"),
                watermark_file=paths.get("watermark"), music_file=paths.get("music"), on_progress=on_progress,
            )
            try:
                with open(result.path, "rb") as fh:
                    sent = client.put(body.result_url, content=fh, headers={"Content-Type": "video/mp4"}, timeout=httpx.Timeout(60, write=900))
            finally:
                os.remove(result.path)
            if sent.status_code != 200:
                return JSONResponse({"error": f"ClipRelay did not take the edited video (HTTP {sent.status_code})"}, status_code=502)
        return {"ok": True, "seconds": result.seconds, "note": result.note, "vertical_source": result.vertical_source}
    except Stopped:
        return JSONResponse({"error": "Stopped: the video was paused or cancelled in ClipRelay"}, status_code=409)
    except media.RenderError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    except httpx.HTTPError as exc:
        return JSONResponse({"error": f"Could not reach ClipRelay: {exc}"[:300]}, status_code=502)
    finally:
        shutil.rmtree(work, ignore_errors=True)
