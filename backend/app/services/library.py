"""Each member's own files for editing: background music, fonts for hook text, and one watermark image.

Files live under <STORAGE_LOCAL_PATH>/library/<member>/<kind>/ and are recognised by their first bytes, not only their name.
"""

import os
import struct
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import LibraryFile, utcnow

# Next to the stored videos, so the files survive a redeploy (the media folder is a volume on the server).
ROOT = Path(get_settings().storage_local_path).resolve() / "library"


def _is_mp3(b: bytes) -> bool:
    return b[:3] == b"ID3" or (len(b) > 1 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0)


KINDS = {
    "music": {
        "max_files": 200, "max_bytes": 15_000_000, "noun": "track",
        "types": {"mp3": _is_mp3, "m4a": lambda b: b[4:8] == b"ftyp", "wav": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE", "ogg": lambda b: b[:4] == b"OggS"},
        "wrong": "Upload an MP3, M4A, WAV or OGG file.",
        "media": {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav", "ogg": "audio/ogg"},
    },
    "fonts": {
        "max_files": 30, "max_bytes": 5_000_000, "noun": "font",
        "types": {"ttf": lambda b: b[:4] in (b"\x00\x01\x00\x00", b"true"), "otf": lambda b: b[:4] == b"OTTO"},
        "wrong": "Upload a TTF or OTF font file.",
        "media": {"ttf": "font/ttf", "otf": "font/otf"},
    },
    "watermark": {
        "max_files": 1, "max_bytes": 2_000_000, "noun": "image",
        "types": {"png": lambda b: b[:8] == b"\x89PNG\r\n\x1a\n"},
        "wrong": "Upload a PNG image.",
        "media": {"png": "image/png"},
    },
}


class LibraryError(ValueError):
    pass


def path_of(row: LibraryFile) -> Path:
    return ROOT / str(row.user_id) / row.kind / f"{row.id}.{row.ext}"


def media_type(row: LibraryFile) -> str:
    return KINDS[row.kind]["media"].get(row.ext, "application/octet-stream")


def rows(db: Session, user_id: int, kind: str) -> list[LibraryFile]:
    return list(db.scalars(select(LibraryFile).where(LibraryFile.user_id == user_id, LibraryFile.kind == kind).order_by(LibraryFile.id)))


def _tidy(name: str) -> str:
    base = os.path.basename(str(name).replace("\\", "/"))
    base = base.rsplit(".", 1)[0] if "." in base else base
    return " ".join(base.split())[:80] or "Untitled"


def _png_size(data: bytes) -> tuple[int, int] | None:
    try:
        return struct.unpack(">II", data[16:24])
    except struct.error:
        return None


def next_track(db: Session, user_id: int) -> LibraryFile | None:
    """The track a member's next clip gets: tracks take turns, in the order they were added."""
    tracks = sorted(rows(db, user_id, "music"), key=lambda r: (r.last_used_at is not None, r.last_used_at or datetime.min, r.id))
    return next((t for t in tracks if path_of(t).exists()), None)


def mark_used(row: LibraryFile) -> None:
    row.last_used_at = utcnow()
    row.uses = (row.uses or 0) + 1


def view(db: Session, user_id: int, kind: str) -> dict:
    items = rows(db, user_id, kind)
    upcoming = next_track(db, user_id) if kind == "music" else None
    spec = KINDS[kind]
    return {
        "items": [{"id": r.id, "name": r.name, "type": r.ext, "bytes": r.size, "width": r.width, "height": r.height, "uploaded_at": r.created_at} for r in items],
        "limit": spec["max_files"], "max_bytes": spec["max_bytes"], "next_id": upcoming.id if upcoming else None,
    }


def add(db: Session, user_id: int, kind: str, name: str, data: bytes) -> LibraryFile:
    spec = KINDS[kind]
    if not data:
        raise LibraryError("The file is empty.")
    if len(data) > spec["max_bytes"]:
        raise LibraryError(f"That file is too large. The limit is {spec['max_bytes'] // 1_000_000} MB.")
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if kind == "watermark":
        ext = "png"
    check = spec["types"].get(ext)
    if not check or len(data) < 12 or not check(data):
        raise LibraryError(spec["wrong"])
    existing = rows(db, user_id, kind)
    if kind == "watermark":
        for old in existing:  # one watermark per member: a new one replaces the old
            remove(db, old)
    elif len(existing) >= spec["max_files"]:
        raise LibraryError(f"Your library holds {spec['max_files']} {spec['noun']}s at most. Delete one first.")
    size = _png_size(data) if kind == "watermark" else None
    row = LibraryFile(user_id=user_id, kind=kind, name=_tidy(name), ext=ext, size=len(data), width=size[0] if size else None, height=size[1] if size else None)
    db.add(row)
    db.flush()
    target = path_of(row)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return row


def remove(db: Session, row: LibraryFile) -> None:
    try:
        path_of(row).unlink()
    except FileNotFoundError:
        pass
    db.delete(row)
    db.flush()


def font_file(db: Session, user_id: int | None, font: str) -> str | None:
    """A member's own font for `custom:<id>`; None for the default font or one that is gone."""
    if not user_id or not font.startswith("custom:"):
        return None
    row = db.get(LibraryFile, int(font.split(":", 1)[1]))
    return str(path_of(row)) if row and row.user_id == user_id and row.kind == "fonts" and path_of(row).exists() else None


def watermark(db: Session, user_id: int | None) -> LibraryFile | None:
    found = rows(db, user_id, "watermark") if user_id else []
    return next((r for r in found if path_of(r).exists()), None)
