"""Editing Rules: each member's default look and presets per workspace, a channel's preset, their library of
music, fonts and watermark, and test renders on a real video."""

import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentUser, Workspace
from app.db import session_scope
from app.integrations import youtube
from app.integrations.http import ApiError
from app.models import Channel, EditingLook, Job, JobStatus, LibraryFile, Mode, User, Video, utcnow
from app.security import decode_token
from app.services import activity, downloader, library, looks, media, pipeline, sources

router = APIRouter(tags=["editing"])

TEST_SECONDS = 20  # a test render shows at most this much of the clip, so it finishes quickly
TESTS_DIR = Path(__file__).resolve().parents[2] / "data" / "tests"
KEEP_TESTS = 60 * 60
_tests: dict[str, dict] = {}
_tests_lock = threading.Lock()


class LookIn(BaseModel):
    look: dict


class PresetIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    look: dict | None = None


class AssignIn(BaseModel):
    preset_id: int | None = None


class TestIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    look: dict


def _preset_view(db, row: EditingLook) -> dict:
    used = db.scalar(select(func.count(Channel.id)).where(Channel.preset_id == row.id)) or 0
    return {"id": row.id, "name": row.name, "look": looks.complete(row.look, row.mode), "channels": used, "updated_at": row.updated_at}


def _mine(db, preset_id: int, user: User, mode: str) -> EditingLook:
    row = db.get(EditingLook, preset_id)
    if not row or row.user_id != user.id or row.name is None or row.mode != mode:
        raise HTTPException(404, "No such preset.")
    return row


def _state(db, user: User, mode: str) -> dict:
    default = looks.default_row(db, user.id, mode)
    since = utcnow().timestamp() - 86400
    recent = [j for j in db.scalars(select(Job).join(Video, Job.video_id == Video.id).where(Video.user_id == user.id, Video.mode == mode, Job.status.notin_([JobStatus.FAILED, JobStatus.CANCELLED])).order_by(Job.id.desc()).limit(50)) if j.created_at.timestamp() >= since and j.video.rendered_file_path]
    return {
        "default": looks.complete(default.look, mode),
        "presets": [_preset_view(db, row) for row in looks.presets(db, user.id, mode)],
        "channels": [{"id": c.id, "display_name": c.display_name, "thumbnail_url": c.thumbnail_url, "preset_id": c.preset_id} for c in db.scalars(select(Channel).where(Channel.user_id == user.id, Channel.mode == mode).order_by(Channel.display_name))],
        "font_available": media.default_font() is not None,
        "rendered_last_day": len(recent),
    }


@router.get("/editing")
def editing(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    state = _state(db, user, mode)
    db.commit()  # a first visit stores the member's default look
    return state


@router.put("/editing")
def save_default(body: LookIn, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    try:
        look = looks.validate(body.look, mode)
    except looks.LookError as exc:
        raise HTTPException(422, str(exc)) from exc
    looks.save(looks.default_row(db, user.id, mode), look)
    activity.record(db, "Settings", f"{user.email} saved the editing rules: {looks.summary(look)}", event="editing_saved", user_id=user.id)
    db.commit()
    return _state(db, user, mode)


@router.post("/editing/presets", status_code=201)
def create_preset(body: PresetIn, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    try:
        name = looks.check_name(db, user.id, mode, body.name)
        look = looks.validate(body.look, mode)
    except looks.LookError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = EditingLook(user_id=user.id, mode=mode, name=name, look=look)
    db.add(row)
    activity.record(db, "Settings", f"{user.email} saved the editing preset “{name}”", event="preset_saved", user_id=user.id)
    db.commit()
    return _preset_view(db, row)


@router.patch("/editing/presets/{preset_id}")
def update_preset(preset_id: int, body: PresetIn, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    row = _mine(db, preset_id, user, mode)
    try:
        if body.name is not None:
            row.name = looks.check_name(db, user.id, mode, body.name, preset_id=row.id)
        if body.look is not None:
            looks.save(row, looks.validate(body.look, mode))
    except looks.LookError as exc:
        raise HTTPException(422, str(exc)) from exc
    row.updated_at = utcnow()
    db.commit()
    return _preset_view(db, row)


@router.delete("/editing/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: int, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    row = _mine(db, preset_id, user, mode)
    # Channels that used it go back to the default rules.
    db.execute(update(Channel).where(Channel.preset_id == row.id).values(preset_id=None).execution_options(synchronize_session=False))
    activity.record(db, "Settings", f"{user.email} deleted the editing preset “{row.name}”", event="preset_deleted", user_id=user.id)
    db.delete(row)
    db.commit()


@router.put("/editing/channels/{channel_id}")
def assign_preset(channel_id: int, body: AssignIn, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    channel = db.get(Channel, channel_id)
    if not channel or channel.user_id != user.id or channel.mode != mode:
        raise HTTPException(404, "Channel not found")
    if body.preset_id is not None:
        _mine(db, body.preset_id, user, mode)
    channel.preset_id = body.preset_id
    db.commit()
    return _state(db, user, mode)


# ---------------------------------------------------------------- the member's library

def _kind(kind: str) -> str:
    if kind not in library.KINDS:
        raise HTTPException(404, "Unknown library")
    return kind


def _user_from_media_token(db, token: str | None) -> User | None:
    try:
        payload = decode_token(token or "")
        user = db.get(User, int(payload["sub"])) if payload.get("purpose") == "media" else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
    return user if user and user.is_active else None


@router.get("/library/{kind}")
def library_list(kind: str, db: DB, user: CurrentUser):
    return library.view(db, user.id, _kind(kind))


@router.post("/library/{kind}")
async def library_upload(kind: str, request: Request, db: DB, user: CurrentUser, name: str = "file"):
    """The file itself is the request body; its name comes in `name`."""
    data = await request.body()
    try:
        row = library.add(db, user.id, _kind(kind), name, data)
    except library.LibraryError as exc:
        raise HTTPException(422, str(exc)) from exc
    activity.record(db, "Settings", f"{user.email} added “{row.name}” to their {kind} library", event="library_added", user_id=user.id)
    db.commit()
    return library.view(db, user.id, kind)


@router.delete("/library/{kind}/{file_id}")
def library_remove(kind: str, file_id: int, db: DB, user: CurrentUser):
    row = db.get(LibraryFile, file_id)
    if not row or row.user_id != user.id or row.kind != _kind(kind):
        raise HTTPException(404, "No such file.")
    library.remove(db, row)
    db.commit()
    return library.view(db, user.id, kind)


@router.get("/library/{kind}/{file_id}/file", include_in_schema=False)
def library_file(kind: str, file_id: int, db: DB, token: str | None = None):
    """The file, for playing a track or showing the watermark in the page (token from /auth/media-token)."""
    user = _user_from_media_token(db, token)
    row = db.get(LibraryFile, file_id)
    if not user or not row or row.user_id != user.id or row.kind != _kind(kind) or not library.path_of(row).exists():
        raise HTTPException(404, "Not found")
    return FileResponse(library.path_of(row), media_type=library.media_type(row))


# ---------------------------------------------------------------- test render on a real video

def _forget_old_tests() -> None:
    with _tests_lock:
        for test_id, test in list(_tests.items()):
            if test["status"] != "running" and time.time() - test["started"] > KEEP_TESTS:
                shutil.rmtree(TESTS_DIR / test_id, ignore_errors=True)
                del _tests[test_id]


def _public(test: dict) -> dict:
    return {k: v for k, v in test.items() if k not in ("user_id", "started")}


def _run_test(test_id: str, url: str, look: dict) -> None:
    test = _tests[test_id]
    folder = TESTS_DIR / test_id
    folder.mkdir(parents=True, exist_ok=True)
    source = None
    try:
        video_id = downloader.video_id_from(url)
        meta = youtube.video_details(video_id)
        test["title"] = meta.title
        watch = youtube.watch_url(video_id)
        test["stage"] = "Downloading"
        adapter = sources.YtDlpAdapter()
        need = TEST_SECONDS * look["speed"]["speed"] + 1
        try:
            source = adapter._clip_from_pieces(watch, 0, min(need, meta.duration_seconds or need))  # only the part the test needs
        except sources.SourceError:
            source = adapter._download_whole(watch)
        with session_scope() as db:
            user_id = test["user_id"]
            font = library.font_file(db, user_id, look["hook"]["font"]) if look["hook"]["enabled"] else None
            mark = library.watermark(db, user_id) if look["watermark"]["enabled"] else None
            track = library.next_track(db, user_id) if look["music"]["enabled"] else None  # a test does not use up a track's turn
            mark_path = str(library.path_of(mark)) if mark else None
            track_path, track_name = (str(library.path_of(track)), track.name) if track else (None, None)
        hook = pipeline.hook_words(look, meta.title) if look["hook"]["enabled"] else None
        test["stage"] = "Rendering"
        started = time.monotonic()
        result = media.render(source, look, hook_text=hook, font_file=font, watermark_file=mark_path, music_file=track_path, max_seconds=TEST_SECONDS)
        preview = folder / "preview.mp4"
        shutil.move(result.path, preview)
        test.update(status="done", stage=None, seconds=result.seconds, bytes=os.path.getsize(preview), render_seconds=round(time.monotonic() - started, 1),
                    command=result.command, note=result.note, vertical=result.vertical_source, music=track_name, hook=hook)
    except (sources.SourceError, media.RenderError, media.ProbeError, ApiError, OSError, ValueError) as exc:
        test.update(status="failed", stage=None, message=str(exc)[:500])
    finally:
        if source and os.path.exists(source):
            try:
                os.remove(source)
            except OSError:
                pass


@router.post("/editing/test")
def start_test(body: TestIn, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    try:
        look = looks.validate(body.look, mode)
        downloader.video_id_from(body.url)
    except (looks.LookError, ValueError) as exc:
        raise HTTPException(422, str(exc) or "That is not a YouTube video link.") from exc
    _forget_old_tests()
    with _tests_lock:
        if any(t["status"] == "running" and t["user_id"] == user.id for t in _tests.values()):
            raise HTTPException(409, "A test render is already running. Wait for it to finish.")
        test_id = uuid.uuid4().hex
        _tests[test_id] = {"id": test_id, "status": "running", "stage": "Looking the video up", "title": None, "user_id": user.id, "started": time.time()}
    threading.Thread(target=_run_test, args=(test_id, body.url.strip(), look), name="cliprelay-test-render", daemon=True).start()
    return _public(_tests[test_id])


@router.get("/editing/test/{test_id}")
def test_status(test_id: str, user: CurrentUser):
    test = _tests.get(test_id)
    if not test or test["user_id"] != user.id:
        raise HTTPException(404, "No such test render.")
    return _public(test)


@router.get("/editing/test/{test_id}/preview.mp4", include_in_schema=False)
def test_preview(test_id: str, db: DB, token: str | None = None):
    user = _user_from_media_token(db, token)
    test = _tests.get(test_id)
    preview = TESTS_DIR / test_id / "preview.mp4"
    if not user or not test or test["user_id"] != user.id or not preview.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(preview, media_type="video/mp4")

