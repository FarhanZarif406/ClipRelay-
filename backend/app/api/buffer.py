"""Buffer Settings: the member's own Buffer keys and accounts, and the link Buffer fetches clips from."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser, Workspace
from app.integrations.buffer import BufferError
from app.models import BufferChannel, BufferKey, Mode, User
from app.services import activity, buffer
from app.services.storage import get_storage

router = APIRouter(tags=["buffer"])


class KeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=60)


class KeyChange(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    label: str | None = Field(default=None, max_length=60)


class ChannelIn(BaseModel):
    enabled: bool | None = None
    daily_limit: int | None = None
    times: list[str] | None = None
    time_zone: str | None = Field(default=None, max_length=60)
    start_date: str | None = Field(default=None, max_length=10)


def _mine(db, channel_id: int, user: User) -> BufferChannel:
    channel = db.get(BufferChannel, channel_id)
    if not channel or channel.user_id != user.id:
        raise HTTPException(404, "No such Buffer account.")
    return channel


@router.get("/buffer")
def status(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    return buffer.status(db, user.id, mode)


def _my_key(db, key_id: int, user: User) -> BufferKey:
    item = db.get(BufferKey, key_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "No such Buffer key.")
    return item


@router.post("/buffer/keys")
def add_key(body: KeyIn, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    """The key is checked with Buffer first, and refused if Buffer does not accept it."""
    try:
        item = buffer.add_key(db, user.id, body.api_key.strip(), body.label)
    except BufferError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    activity.record(db, "Settings", f"{user.email} added a Buffer API key ({item.label})", event="buffer_key_saved", user_id=user.id)
    db.commit()
    return buffer.status(db, user.id, mode)


@router.patch("/buffer/keys/{key_id}")
def update_key(key_id: int, body: KeyChange, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    """Rename a key, or replace it with a new one (checked with Buffer first)."""
    item = _my_key(db, key_id, user)
    try:
        buffer.update_key(db, item, key=(body.api_key or "").strip() or None, label=body.label)
    except BufferError as exc:
        db.commit()  # the key that worked before was put back, with Buffer's reason
        raise HTTPException(400, str(exc)) from exc
    if body.api_key:
        activity.record(db, "Settings", f"{user.email} replaced a Buffer API key ({item.label})", event="buffer_key_saved", user_id=user.id)
    db.commit()
    return buffer.status(db, user.id, mode)


@router.delete("/buffer/keys/{key_id}")
def remove_key(key_id: int, db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    item = _my_key(db, key_id, user)
    label = item.label
    buffer.remove_key(db, item)
    activity.record(db, "Settings", f"{user.email} removed a Buffer API key ({label})", event="buffer_key_removed", user_id=user.id)
    db.commit()
    return buffer.status(db, user.id, mode)


@router.post("/buffer/refresh")
def refresh(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    """Read every key's accounts from Buffer again, e.g. after connecting another one there."""
    try:
        buffer.sync(db, user.id)
    except BufferError as exc:
        db.commit()  # the reason is kept and shown on the page
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    return buffer.status(db, user.id, mode)


@router.patch("/buffer/channels/{channel_id}")
def update_channel(channel_id: int, body: ChannelIn, db: DB, user: CurrentUser):
    channel = _mine(db, channel_id, user)
    try:
        buffer.update_channel(db, channel, body.model_dump(exclude_unset=True))
    except BufferError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return buffer.status(db, user.id, channel.mode)


@router.get("/buffer/channels/{channel_id}/status")
def channel_status(channel_id: int, db: DB, user: CurrentUser):
    return buffer.channel_status(db, _mine(db, channel_id, user))


# ---------------------------------------------------------------- the private link (no login: called by Buffer)

@router.api_route("/public/clip/{token}/clip.mp4", methods=["GET", "HEAD"], include_in_schema=False)
def public_clip(token: str, db: DB):
    """Buffer fetches an approved clip from here. The long random token is the only way in, and it works
    only while the clip is on its way to being published."""
    video = buffer.shared_clip(db, token) if len(token) == 48 else None
    if not video:
        raise HTTPException(404, "Not found")
    storage = get_storage()
    path = storage.local_path(video.rendered_file_path)
    if path:
        return FileResponse(path, media_type="video/mp4")
    url = storage.url(video.rendered_file_path)
    if not url:
        raise HTTPException(404, "Not found")
    return RedirectResponse(url)
