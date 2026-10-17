"""Where a video is edited: on the member's own PC first (the PC Helper), else in Google Cloud Run.

The PC Helper is a small program a member runs on their own Windows or Mac computer. Connected with a short code
from the website, it asks this server every few seconds for the member's next video, downloads it from YouTube over
the member's own internet, edits it with the same FFmpeg edit, and sends back only the finished video. The server
writes the caption and hands it to Buffer as usual. So the PC Helper takes the download and the edit off the server,
and YouTube sees a home connection instead of a server.

When the PC is off, asleep or has not answered for three minutes, its video moves on: to Cloud Run (see
`cloud_editor`), or, when that is not set up, it is shown as failed unless the owner lets this server edit it.
The member's "one video at a time" line holds throughout.

The helper's key is a secret: it is stored only as a hash. The owner's cookies and proxy never go to a PC.
"""

import hashlib
import os
import secrets
import tempfile
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import youtube
from app.models import EditorDevice, EditorPairing, Job, JobStatus, LibraryFile, Mode, User, Video, utcnow
from app.services import activity, library, looks, media, plans
from app.services.activity import job_event
from app.services.storage import get_storage

ONLINE_FOR = timedelta(minutes=3)  # a PC that has not answered for this long is taken as off
PAIR_FOR = timedelta(minutes=10)
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I to mix up
TOKEN_PREFIX = "crh_"
PLATFORMS = ("windows", "mac")
WORKING = (JobStatus.DOWNLOADING, JobStatus.RENDERING)
MAX_RESULT_BYTES = 1024 * 1024 * 1024
LATEST_VERSION = "1.1.1"  # the newest PC Helper; an older one is told an update is ready


class EditorError(ValueError):
    """Something the helper or the member asked for cannot be done. The message is written for people."""


class NotYours(EditorError):
    """The video moved on (to the cloud, paused, stopped): this PC must drop it."""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _code_key(code: str) -> str:
    return _hash("".join(ch for ch in (code or "").upper() if ch.isalnum()))


# ---------------------------------------------------------------- connecting a PC

def new_code(db: Session, user: User) -> dict:
    """A code the member types into the PC Helper. One at a time; it works for ten minutes."""
    now = utcnow()
    for row in db.scalars(select(EditorPairing).where((EditorPairing.user_id == user.id) | (EditorPairing.expires_at < now))):
        db.delete(row)
    raw = "".join(secrets.choice(CODE_LETTERS) for _ in range(6))
    db.add(EditorPairing(code_hash=_code_key(raw), user_id=user.id, expires_at=now + PAIR_FOR))
    db.commit()
    return {"code": f"{raw[:3]}-{raw[3:]}", "expires_at": now + PAIR_FOR}


def connect(db: Session, code: str, *, name: str, platform: str, version: str) -> tuple[EditorDevice, str]:
    """Exchange a code for the helper's own key. Returns (device, key); the key is shown to the helper once."""
    row = db.get(EditorPairing, _code_key(code))
    if not row or row.expires_at < utcnow():
        raise EditorError("That code is wrong or has expired. Make a new one on the website: PC Helper → Connect a PC.")
    user = db.get(User, row.user_id)
    db.delete(row)
    if not user or not user.is_active or (user.suspended and not user.is_owner):
        db.commit()
        raise EditorError("That account cannot connect a PC.")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    device = EditorDevice(
        user_id=user.id, name=(name or "My computer").strip()[:80] or "My computer",
        platform=platform if platform in PLATFORMS else "", version=(version or "")[:20],
        token_hash=_hash(token), last_seen_at=utcnow(),
    )
    db.add(device)
    db.commit()
    activity.record(db, "PC Helper", f"{device.name} was connected", event="helper_connected", user_id=user.id)
    db.commit()
    return device, token


def device_for_token(db: Session, token: str) -> EditorDevice | None:
    if not token or not token.startswith(TOKEN_PREFIX):
        return None
    return db.scalar(select(EditorDevice).where(EditorDevice.token_hash == _hash(token)))


def is_online(device: EditorDevice | None, now=None) -> bool:
    return bool(device and not device.paused and device.last_seen_at and device.last_seen_at > (now or utcnow()) - ONLINE_FOR)


def online_device(db: Session, user_id: int | None) -> EditorDevice | None:
    """The member's PC that can edit now: connected, not paused, and heard from within three minutes."""
    if not user_id:
        return None
    since = utcnow() - ONLINE_FOR
    return db.scalar(
        select(EditorDevice)
        .where(EditorDevice.user_id == user_id, EditorDevice.paused.is_(False), EditorDevice.last_seen_at > since)
        .order_by(EditorDevice.last_seen_at.desc())
        .limit(1)
    )


def beat(db: Session, device: EditorDevice, *, version: str | None = None, paused: bool | None = None) -> dict:
    """The helper says it is there (every 30 seconds)."""
    device.last_seen_at = utcnow()
    if version:
        device.version = version[:20]
    if paused is not None and paused != device.paused:
        device.paused = paused
        if paused:
            release_device(db, device, "The PC Helper was paused")
    db.commit()
    return {"ok": True, "latest_version": LATEST_VERSION, **downloads()}


# The built PC Helper can be served by this server: put the files in this folder (next to the media folder,
# so /data/helper on Docker). A link in .env (HELPER_DOWNLOAD_*) wins over the folder.
HELPER_FILES = {"windows": "ClipRelay-Helper-windows.exe", "mac": "ClipRelay-Helper-mac.zip", "mac-intel": "ClipRelay-Helper-mac-intel.zip"}


def helper_folder() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(get_settings().storage_local_path)), "helper")


def helper_file(platform: str) -> str | None:
    name = HELPER_FILES.get(platform)
    path = os.path.join(helper_folder(), name) if name else None
    return path if path and os.path.isfile(path) else None


def downloads() -> dict:
    """Where the page's download buttons go: a link from .env, else this server (which says so when it has no file yet)."""
    s = get_settings()
    links = {"windows": s.helper_download_windows, "mac": s.helper_download_mac, "mac-intel": ""}
    ready = {}
    for platform in HELPER_FILES:
        ready[platform] = bool(links[platform] or helper_file(platform))
        links[platform] = links[platform] or f"/api/helper/download/{platform}"
    return {"download_windows": links["windows"], "download_mac": links["mac"], "download_mac_intel": links["mac-intel"],
            "ready_windows": ready["windows"], "ready_mac": ready["mac"], "ready_mac_intel": ready["mac-intel"]}


def device_view(device: EditorDevice, now=None) -> dict:
    return {
        "id": device.id, "name": device.name, "platform": device.platform, "version": device.version,
        "online": is_online(device, now), "paused": device.paused,
        "last_seen_at": device.last_seen_at, "created_at": device.created_at,
        "outdated": bool(device.version) and _version(device.version) < _version(LATEST_VERSION),
    }


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) if part.isdigit() else 0 for part in text.split(".")[:3])


def view(db: Session, user: User) -> dict:
    """The member's PC Helper page."""
    devices = db.scalars(select(EditorDevice).where(EditorDevice.user_id == user.id).order_by(EditorDevice.created_at)).all()
    from app.services import cloud_editor, push

    working = db.scalar(select(Job).join(Video, Job.video_id == Video.id).where(
        Video.user_id == user.id, Job.edit_place == "pc", Job.status.in_(WORKING)).limit(1))
    return {
        "devices": [device_view(d) for d in devices],
        "allowed": plans.allows(db, user.id, "pc_editing"),
        "cloud_allowed": plans.allows(db, user.id, "cloud_editing"),
        "cloud_ready": cloud_editor.ready(db),
        "server_address": push.base_url() or "",
        "latest_version": LATEST_VERSION,
        "working_on": {"job_id": working.id, "title": working.video.original_title or working.video.youtube_video_id} if working else None,
        **downloads(),
    }


def remove(db: Session, device: EditorDevice) -> None:
    """Disconnect a PC: its key stops working and its video moves on."""
    release_device(db, device, f"{device.name} was disconnected")
    activity.record(db, "PC Helper", f"{device.name} was disconnected", event="helper_removed", user_id=device.user_id)
    db.delete(device)
    db.commit()


# ---------------------------------------------------------------- where a video is edited

def place_for(db: Session, video: Video) -> str | None:
    """"pc" (wait for the member's PC to take it), "cloud", "server", or None when nothing may edit it."""
    from app.services import cloud_editor

    if video.is_podcast_source:
        return "server"  # a whole podcast is read and split here; only its clips are edited
    if plans.allows(db, video.user_id, "pc_editing") and online_device(db, video.user_id):
        return "pc"
    if plans.allows(db, video.user_id, "cloud_editing") and cloud_editor.ready(db):
        return "cloud"
    if cloud_editor.fallback(db) == "server":
        return "server"
    return None


def nothing_can_edit(db: Session, video: Video) -> str:
    """Why a video could not be edited anywhere, for the member and the owner."""
    from app.services import cloud_editor

    if not plans.allows(db, video.user_id, "pc_editing") and not plans.allows(db, video.user_id, "cloud_editing"):
        return "Your plan includes neither PC Helper nor cloud editing. Ask the owner to upgrade it."
    if not cloud_editor.ready(db):
        return "No PC Helper is on for this account and cloud editing is not set up. Turn the PC Helper on, then press Retry."
    return "Your plan's cloud editing is off and no PC Helper is on. Turn the PC Helper on, then press Retry."


def release(db: Session, job: Job, why: str) -> None:
    """Take a video back from a PC: it waits again for whoever edits it next (the PC once it is back, or the cloud)."""
    job.edit_place = None
    job.editor_device_id = None
    job.edit_spec = None
    job.progress = None
    job.next_check_at = None
    if job.status in WORKING:
        job_event(db, job, JobStatus.FETCHED, f"{why} — the video moves on without it")


def release_device(db: Session, device: EditorDevice, why: str) -> None:
    for job in db.scalars(select(Job).where(Job.editor_device_id == device.id, Job.status.in_(WORKING))).unique():
        release(db, job, why)


def release_lost(db: Session) -> list[int]:
    """Videos whose PC stopped answering for three minutes (off, asleep, no internet) move on. Called by the tick."""
    moved = []
    now = utcnow()
    for job in db.scalars(select(Job).where(Job.edit_place == "pc", Job.status.in_(WORKING))).unique():
        device = db.get(EditorDevice, job.editor_device_id) if job.editor_device_id else None
        if is_online(device, now):
            continue
        name = device.name if device else "The PC"
        release(db, job, f"{name} stopped answering for {int(ONLINE_FOR.total_seconds() // 60)} minutes")
        moved.append(job.id)
    return moved


# ---------------------------------------------------------------- the helper's work

def _mine(job: Job | None, device: EditorDevice) -> bool:
    return bool(job and job.editor_device_id == device.id and job.edit_place == "pc" and job.video.user_id == device.user_id)


def next_job(db: Session, device: EditorDevice) -> Job | None:
    """The member's next video for this PC, or None. A video it already has (the helper restarted) comes back first."""
    from app.services import pipeline, system

    device.last_seen_at = utcnow()
    if device.paused or not system.is_on(db) or not plans.allows(db, device.user_id, "pc_editing") or plans.blocked(db, device.user_id):
        db.commit()
        return None
    job = db.scalar(select(Job).where(Job.editor_device_id == device.id, Job.edit_place == "pc", Job.status.in_(WORKING)).order_by(Job.id).limit(1))
    if job:
        if not job.edit_spec:
            job.edit_spec = _spec(db, job)
        db.commit()
        return job
    now = utcnow()
    waiting = db.scalars(
        select(Job).join(Video, Job.video_id == Video.id)
        .where(Video.user_id == device.user_id, Job.status == JobStatus.FETCHED, ~((Video.mode == Mode.PODCASTS) & Video.parent_id.is_(None)))
        .order_by(Job.id).limit(1)
    ).unique().all()
    for job in waiting:
        if job.attempts and job.next_check_at and job.next_check_at > now:
            break  # it failed a moment ago and waits before trying again
        if not pipeline.claim_lane(db, job):  # the member's previous video is still on its way
            break
        job.edit_place, job.editor_device_id, job.progress = "pc", device.id, 0
        job.next_check_at = None
        job.edit_spec = _spec(db, job)
        job_event(db, job, JobStatus.DOWNLOADING, f"Downloading on {device.name} (PC Helper)")
        db.commit()
        return job
    db.commit()
    return None


def _asset(kind: str, path: str | None, row: LibraryFile | None = None) -> dict | None:
    if not path or not os.path.isfile(path):
        return None
    size = os.path.getsize(path)
    # The helper keeps files it has fetched; the same name means the same file, so it is fetched only once.
    cache = f"{kind}-{row.id}-{size}" if row else f"{kind}-default-{size}"
    return {"path": path, "cache": cache + os.path.splitext(path)[1].lower(), "library_id": row.id if row else None}


def _spec(db: Session, job: Job) -> dict:
    """What the PC is asked to make: the video to fetch, the look, the hook line and the member's files."""
    from app.services import acting, pipeline

    video = job.video
    with acting.acting_for(db, video.user_id):  # the member's own AI model writes the hook line
        look = pipeline._plan_look(db, video, looks.for_video(db, video))
        hook_text = pipeline.hook_words(look, video.original_title or "", ai=pipeline._allows(db, video, "ai_hook")) if look["hook"]["enabled"] else None
    font_path = library.font_file(db, video.user_id, look["hook"]["font"]) if look["hook"]["enabled"] else None
    font_row = db.get(LibraryFile, int(look["hook"]["font"].split(":", 1)[1])) if font_path else None
    mark = library.watermark(db, video.user_id) if look["watermark"]["enabled"] else None
    track = library.next_track(db, video.user_id) if look["music"]["enabled"] else None
    files = {
        "font": _asset("font", font_path or (media.default_font() if look["hook"]["enabled"] else None), font_row),
        "watermark": _asset("watermark", str(library.path_of(mark)) if mark else None, mark),
        "music": _asset("music", str(library.path_of(track)) if track else None, track),
    }
    source_id = video.parent.youtube_video_id if video.parent_id and video.parent else video.youtube_video_id
    return {
        "url": youtube.watch_url(source_id or ""),
        "clip": {"start": float(video.clip_start), "end": float(video.clip_end)} if video.parent_id and video.clip_start is not None else None,
        "short_side": 1080 if pipeline._allows(db, video, "full_editing") else 720,
        "look": look,
        "summary": looks.summary(look),
        "hook_text": hook_text,
        "files": {kind: value for kind, value in files.items() if value},
    }


def public_spec(job: Job) -> dict:
    """The spec as the helper sees it: links to fetch the files, never paths on the server."""
    spec = dict(job.edit_spec or {})
    files = {kind: {"cache": value["cache"], "url": f"/api/helper/jobs/{job.id}/files/{kind}"} for kind, value in (spec.get("files") or {}).items()}
    return {
        "job_id": job.id, "title": job.video.original_title or "", "url": spec.get("url"), "clip": spec.get("clip"),
        "link": _watch_link(job.video), "thumbnail": _thumbnail(job.video), "channel": job.video.channel.display_name if job.video.channel else "",
        "short_side": spec.get("short_side", 720), "look": spec.get("look"), "hook_text": spec.get("hook_text"),
        "summary": spec.get("summary", ""), "files": files,
    }


def file_path(db: Session, device: EditorDevice, job_id: int, kind: str) -> str:
    job = db.get(Job, job_id)
    if not _mine(job, device):
        raise NotYours("This video is no longer this PC's to edit")
    value = ((job.edit_spec or {}).get("files") or {}).get(kind)
    if not value or not os.path.isfile(value["path"]):
        raise EditorError("That file is not part of this video's edit")
    return value["path"]


def progress(db: Session, device: EditorDevice, job_id: int, stage: str, percent: float | None) -> dict:
    """The helper reports how far it is. {"stop": True} tells it to drop the video (paused, stopped or moved on)."""
    job = db.get(Job, job_id)
    device.last_seen_at = utcnow()
    if not _mine(job, device) or job.status not in WORKING:
        db.commit()
        return {"stop": True}
    if stage == "editing" and job.status != JobStatus.RENDERING:
        job_event(db, job, JobStatus.RENDERING, f"Editing on {device.name} (PC Helper) · {(job.edit_spec or {}).get('summary', '')}".rstrip(" ·"))
    if percent is not None:
        job.progress = max(0, min(99, int(percent)))
    db.commit()
    return {"stop": False}


def finish(db: Session, device: EditorDevice, job_id: int, upload) -> str:
    """The finished video from the PC: kept for Buffer, then the caption and the upload carry on as usual."""
    from app.services import pipeline

    job = db.get(Job, job_id)
    if not _mine(job, device) or job.status not in WORKING:
        raise NotYours("This video is no longer this PC's to edit: it was paused, stopped or moved on")
    fd, path = tempfile.mkstemp(suffix=".mp4")
    written = 0
    with os.fdopen(fd, "wb") as out:
        while chunk := upload.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_RESULT_BYTES:
                out.close()
                os.remove(path)
                raise EditorError("The edited video is larger than 1 GB")
            out.write(chunk)
    try:
        info = media.probe(path)
    except media.ProbeError as exc:
        os.remove(path)
        raise EditorError(f"The edited video could not be read: {exc}") from exc
    video = job.video
    video.rendered_file_path = get_storage().save(path, f"videos/{video.id}.mp4")
    job.edited_at = utcnow()
    if not video.duration_sec:
        video.duration_sec = round(info.duration, 2)
    music = ((job.edit_spec or {}).get("files") or {}).get("music") or {}
    if music.get("library_id"):
        row = db.get(LibraryFile, music["library_id"])
        if row:
            library.mark_used(row)  # the member's next video gets the next track
    summary = (job.edit_spec or {}).get("summary", "")
    job.edit_spec = None
    job.progress = None
    job.attempts = 0
    job.error = None
    device.last_seen_at = utcnow()
    activity.record(db, "Render", f"Video #{video.id} edited on {device.name} (PC Helper) · {summary}".rstrip(" ·"), event="rendered", job_id=job.id)
    status = pipeline._advance(db, job)
    db.commit()
    return status


def failed(db: Session, device: EditorDevice, job_id: int, stage: str, message: str) -> None:
    """The PC could not download or edit it: tried again after a while (on the PC if it is on, else in the cloud)."""
    from app.services import pipeline

    job = db.get(Job, job_id)
    if not _mine(job, device) or job.status not in WORKING:
        return
    job.edit_place = None
    job.editor_device_id = None
    job.edit_spec = None
    job.progress = None
    job.status = JobStatus.FETCHED
    label = "Download" if stage == "download" else "Render"
    pipeline._stage_failed(db, job, f"{label} on {device.name}", (message or "no reason given")[:300])
    db.commit()


# ---------------------------------------------------------------- the helper's window: plan, monthly figures, recent videos

MONTHS_SHOWN = 3


def _month_starts(now, count: int) -> list:
    """The first moment of this month and of the months before it, newest first (UTC)."""
    starts, year, month = [], now.year, now.month
    for _ in range(count):
        starts.append(now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return starts


def _count(db: Session, *conditions) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count(Job.id)).join(Video, Job.video_id == Video.id).where(*conditions)) or 0


def overview(db: Session, device: EditorDevice) -> dict:
    """What the helper's window shows besides its own work: the member's plan and when it ends, and per month (this
    one and the two before) how many videos this account's PCs edited, how many were edited in all, and published."""
    user = device.user
    now = utcnow()
    plan = plans.effective(db, user)
    ends = plan["expires_at"]
    blocked = plans.blocked(db, user.id)
    starts = _month_starts(now, MONTHS_SHOWN)
    months = []
    for i in range(MONTHS_SHOWN):
        start, end = starts[i], (starts[i - 1] if i else now)  # this month so far, then each month before it
        mine = Video.user_id == user.id
        months.append({
            "month": start.strftime("%Y-%m"),
            "edited_on_pc": _count(db, mine, Job.edit_place == "pc", Job.edited_at >= start, Job.edited_at < end),
            "edited_in_cloud": _count(db, mine, Job.edit_place == "cloud", Job.edited_at >= start, Job.edited_at < end),
            "edited": _count(db, mine, Job.edited_at >= start, Job.edited_at < end),
            "published": _count(db, mine, Job.posted_at >= start, Job.posted_at < end),
        })
    recent = db.scalars(
        select(Job).join(Video, Job.video_id == Video.id)
        .where(Video.user_id == user.id, Job.edit_place == "pc", Job.edited_at.is_not(None))
        .order_by(Job.edited_at.desc()).limit(6)
    ).unique().all()
    return {
        "account": user.email, "name": user.name,
        "plan": {
            "name": plan["plan"], "owner": plan["owner"], "trial": int(plan["limits"].get("trial_days") or 0) > 0,
            "ends_at": ends, "days_left": max(0, (ends - now).days) if ends else None, "blocked": blocked,
            "videos_per_day": plan["limits"].get("videos_per_day", 0),
        },
        "months": months,
        "recent": [{
            "title": job.video.original_title or job.video.youtube_video_id, "status": job.status,
            "url": _watch_link(job.video), "thumbnail": _thumbnail(job.video), "edited_at": job.edited_at, "posted_at": job.posted_at,
        } for job in recent],
    }


def _youtube_id(video: Video) -> str:
    source = video.parent if video.parent_id and video.parent else video
    return (source.youtube_video_id or "").split("#", 1)[0]


def _watch_link(video: Video) -> str | None:
    vid = _youtube_id(video)
    return video.permalink or (youtube.watch_url(vid) if vid else None)


def _thumbnail(video: Video) -> str | None:
    vid = _youtube_id(video)
    return video.thumbnail_url or (f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg" if vid else None)


def not_ready_page(platform: str) -> str:
    """A friendly page for a download button whose file the owner has not put on the server yet."""
    which = {"windows": "Windows", "mac": "Mac (Apple chip)", "mac-intel": "Mac (Intel)"}.get(platform, "this computer")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClipRelay Helper</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0d12;color:#e6e8ee;
font:15px/1.6 Inter,system-ui,sans-serif}}div{{max-width:460px;padding:28px;border:1px solid #232938;border-radius:16px;background:#11141b;margin:16px}}
b{{display:block;font-size:19px;margin-bottom:8px}}p{{color:#8a91a5;margin:6px 0}}</style></head><body><div>
<b>The PC Helper for {which} is on its way</b><p>Your manager has not added this download to ClipRelay yet. Please ask them, then press the button again.</p>
<p>PC Helper abhi tayyar nahi hua. Manager se kahein ke ise ClipRelay mein lagayein, phir dobara button dabayein.</p></div></body></html>"""
