"""Publishing through Buffer.

Every member saves their own Buffer API keys, up to ten. The Buffer channels (the social accounts connected
in Buffer) every key reaches then appear in each workspace, each with its own switch, daily limit and times of
day. The accounts take turns: a finished clip goes to the account that has waited longest for one, as a post
scheduled for its next free time; Buffer fetches the video from a private link on this server and publishes
it. A key is never sent to the page: only its name and its last four characters.
"""

import logging
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.integrations import buffer as api
from app.integrations.buffer import BufferError
from app.models import BufferChannel, BufferKey, BufferLog, Job, JobStatus, Mode, Video, utcnow
from app.security import decrypt, encrypt
from app.services import activity, push, rules, slots
from app.services.activity import job_event

log = logging.getLogger(__name__)

KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{20,400}$")
DEFAULT_TIMES = ["09:00", "13:00", "18:00"]
DEFAULT_LIMIT = 3
MAX_ATTEMPTS = 3
MAX_KEYS = 10
# A post is asked about a few minutes after its time, then now and then until Buffer reports it.
CHECK_AFTER = timedelta(minutes=3)
CHECK_EVERY = timedelta(minutes=15)
GIVE_UP = timedelta(hours=24)
NO_ACCOUNT = "Waiting for a Buffer account — switch one on in Buffer Settings"
NO_TIMES = "Waiting for posting times — add times to an account in Buffer Settings"
NO_KEY = "Waiting for Buffer — add your Buffer API key in Buffer Settings"
NO_PUBLIC_URL = "The public base URL is not set, so Buffer cannot fetch the clip. An admin sets it on the Integrations page."


# ---------------------------------------------------------------- the member's keys and accounts

def keys(db: Session, user_id: int | None) -> list[BufferKey]:
    if not user_id:
        return []
    return list(db.scalars(select(BufferKey).where(BufferKey.user_id == user_id).order_by(BufferKey.position, BufferKey.id)))


def uses_buffer(db: Session, user_id: int | None) -> bool:
    """Whether the member has saved a Buffer API key. Clips are published through Buffer only."""
    return bool(user_id) and db.scalar(select(func.count(BufferKey.id)).where(BufferKey.user_id == user_id)) > 0


def channels(db: Session, user_id: int, mode: str) -> list[BufferChannel]:
    return list(db.scalars(select(BufferChannel).where(BufferChannel.user_id == user_id, BufferChannel.mode == mode).order_by(BufferChannel.enabled.desc(), func.lower(BufferChannel.name), BufferChannel.id)))  # the accounts in use first


def zone_of(db: Session, channel: BufferChannel) -> str:
    """An account's times are read on its own clock when it has one, else on the member's."""
    return channel.time_zone or member_zone(db, channel.user_id)


def member_zone(db: Session, user_id: int) -> str:
    return rules.global_values(db, user_id=user_id).get("cap_reset_timezone") or "UTC"


def taken(db: Session, channel: BufferChannel) -> list[datetime]:
    """The times already given out on the account, in either workspace: its scheduled posts and recent published ones."""
    same_account = select(BufferChannel.id).where(BufferChannel.user_id == channel.user_id, BufferChannel.buffer_id == channel.buffer_id)
    return list(db.scalars(
        select(Job.buffer_due_at).where(
            Job.buffer_channel_id.in_(same_account), Job.buffer_due_at.is_not(None), Job.buffer_due_at >= utcnow() - timedelta(days=2),
            Job.status.in_([JobStatus.SCHEDULED, JobStatus.POSTED]),
        )
    ))


def next_slot(db: Session, channel: BufferChannel, now: datetime | None = None) -> datetime | None:
    return slots.next_slot(channel.times or [], channel.daily_limit, channel.start_date, taken(db, channel), now or utcnow(), zone_of(db, channel))


def sync_key(db: Session, saved: BufferKey) -> None:
    """Read the accounts one key reaches in Buffer and keep their switches, limits and times.

    An account two keys both reach stays with the key that found it first, so it is never listed twice.
    """
    key = decrypt(saved.api_key_enc) or ""
    try:
        organization = api.organization(key)
        found = api.channels(key, organization)
    except BufferError as exc:
        saved.error = str(exc)
        db.flush()
        raise
    seen = set()
    for item in found:
        service = str(item.get("service") or "").lower()
        name = item.get("displayName") or item.get("name") or item["id"]
        for mode in Mode.ALL:  # each workspace has its own switch and schedule for the same account
            row = db.scalar(select(BufferChannel).where(BufferChannel.user_id == saved.user_id, BufferChannel.mode == mode, BufferChannel.buffer_id == item["id"]))
            if row and row.key_id not in (None, saved.id):
                continue  # another of the member's keys already has it
            seen.add(item["id"])
            if row:
                row.key_id, row.name, row.service, row.avatar = saved.id, name, service, item.get("avatar")
            else:
                # TikTok accounts are switched on from the start; any other network is the member's choice.
                db.add(BufferChannel(user_id=saved.user_id, key_id=saved.id, mode=mode, buffer_id=item["id"], name=name, service=service, avatar=item.get("avatar"),
                                     enabled=service == "tiktok", daily_limit=DEFAULT_LIMIT, times=list(DEFAULT_TIMES)))
    # An account disconnected in Buffer is dropped here too.
    for row in db.scalars(select(BufferChannel).where(BufferChannel.key_id == saved.id)):
        if row.buffer_id not in seen:
            db.delete(row)
    saved.organization_id, saved.synced_at, saved.error = organization, utcnow(), None
    db.flush()


def sync(db: Session, user_id: int) -> None:
    """Read every key's accounts again. A key Buffer refuses keeps its reason; the others are still read."""
    saved = keys(db, user_id)
    if not saved:
        raise BufferError("No Buffer API key is saved.")
    problems = []
    for item in saved:
        try:
            sync_key(db, item)
        except BufferError as exc:
            problems.append(f"{item.label}: {exc}")
    if len(problems) == len(saved):
        raise BufferError(" · ".join(problems))


def _check_key(db: Session, user_id: int, key: str, ignore: int | None = None) -> None:
    if not KEY_RE.match(key):
        raise BufferError("That does not look like a Buffer API key. It should be one line with no spaces.")
    if any(decrypt(item.api_key_enc) == key for item in keys(db, user_id) if item.id != ignore):
        raise BufferError("This key is already saved.")


def _label(db: Session, user_id: int, label: str | None, ignore: int | None = None) -> str | None:
    label = (label or "").strip()
    if not label:
        return None
    if len(label) > 40:
        raise BufferError("Keep the key's name to 40 characters.")
    if any(item.label.lower() == label.lower() for item in keys(db, user_id) if item.id != ignore):
        raise BufferError(f"Another key is already called “{label}”.")
    return label


def add_key(db: Session, user_id: int, key: str, label: str | None = None) -> BufferKey:
    """Keep a new key only if Buffer accepts it."""
    saved = keys(db, user_id)
    if len(saved) >= MAX_KEYS:
        raise BufferError(f"Up to {MAX_KEYS} Buffer keys can be saved. Remove one first.")
    _check_key(db, user_id, key)
    taken_labels = {item.label.lower() for item in saved}
    number = next(n for n in range(1, MAX_KEYS + 2) if f"key {n}" not in taken_labels)
    item = BufferKey(user_id=user_id, label=_label(db, user_id, label) or f"Key {number}", position=max((s.position for s in saved), default=0) + 1,
                     api_key_enc=encrypt(key), saved_at=utcnow())
    db.add(item)
    db.flush()
    try:
        sync_key(db, item)
    except BufferError:
        db.delete(item)
        db.flush()
        raise
    return item


def update_key(db: Session, item: BufferKey, *, key: str | None = None, label: str | None = None) -> None:
    """Rename a key, or put a new one in its place; a key that worked before is put back if Buffer refuses the new one."""
    if label is not None:
        item.label = _label(db, item.user_id, label, ignore=item.id) or item.label
    if key:
        _check_key(db, item.user_id, key, ignore=item.id)
        previous = (item.api_key_enc, item.saved_at, item.error)
        item.api_key_enc, item.saved_at, item.error = encrypt(key), utcnow(), None
        db.flush()
        try:
            sync_key(db, item)
        except BufferError:
            item.api_key_enc, item.saved_at, item.error = previous
            db.flush()
            raise
    db.flush()


def remove_key(db: Session, item: BufferKey) -> None:
    user_id = item.user_id
    db.execute(delete(BufferChannel).where(BufferChannel.key_id == item.id).execution_options(synchronize_session=False))
    db.delete(item)
    db.flush()
    db.expire_all()
    # An account this key shared with another one now belongs to that other key.
    for other in keys(db, user_id):
        try:
            sync_key(db, other)
        except BufferError:
            pass


def update_channel(db: Session, channel: BufferChannel, changes: dict) -> None:
    if changes.get("enabled") is not None:
        channel.enabled = bool(changes["enabled"])
    if changes.get("daily_limit") is not None:
        limit = changes["daily_limit"]
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise BufferError("The daily limit must be a whole number from 1 to 50.")
        channel.daily_limit = limit
    if changes.get("times") is not None:
        times = slots.clean_times(changes["times"])
        if len(times) != len(changes["times"]) or len(times) > slots.MAX_TIMES:
            raise BufferError("Give up to 24 different times of day, each as HH:MM.")
        channel.times = times
    if changes.get("time_zone") is not None:
        try:
            ZoneInfo(changes["time_zone"])
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise BufferError("Choose a valid timezone such as Asia/Karachi.") from exc
        channel.time_zone = changes["time_zone"]
    if "start_date" in changes:  # None clears it: clips go out from the next free time
        if changes["start_date"] is not None and not slots.is_day(changes["start_date"]):
            raise BufferError("Give the start date as a day, such as 2026-10-20.")
        channel.start_date = changes["start_date"]
    db.flush()


# ---------------------------------------------------------------- views

def channel_ref(channel: BufferChannel | None) -> dict | None:
    return {"id": channel.id, "name": channel.name, "service": channel.service} if channel else None


def initials(name: str) -> str:
    parts = [p for p in "".join(ch if ch.isalnum() else " " for ch in name).split() if p]
    return (parts[0][0] + parts[1][0]).upper() if len(parts) >= 2 else (parts[0][:2].upper() if parts else "?")


def account_ref(channel: BufferChannel) -> dict:
    """A publishing account as the Dashboard and the Daily Report list it."""
    return {**channel_ref(channel), "initials": initials(channel.name), "enabled": channel.enabled}


def _log_count(db: Session, channel: BufferChannel, state: str) -> int:
    return db.scalar(select(func.count(BufferLog.id)).where(BufferLog.buffer_channel_id == channel.id, BufferLog.state == state)) or 0


def channel_view(db: Session, channel: BufferChannel, now: datetime | None = None) -> dict:
    now = now or utcnow()
    zone = zone_of(db, channel)
    given = taken(db, channel)
    slot = slots.next_slot(channel.times or [], channel.daily_limit, channel.start_date, given, now, zone)
    return {
        "id": channel.id, "name": channel.name, "service": channel.service, "avatar": channel.avatar, "enabled": channel.enabled,
        "key_id": channel.key_id, "key_label": channel.key.label if channel.key else "", "last_picked_at": channel.last_picked_at,
        "daily_limit": channel.daily_limit, "times": slots.clean_times(channel.times or []), "time_zone": zone, "own_time_zone": bool(channel.time_zone),
        "start_date": channel.start_date, "used_today": slots.taken_today(given, now, zone),
        "uploaded": _log_count(db, channel, "published"), "waiting": _log_count(db, channel, "scheduled"), "next_slot": slot,
    }


def status(db: Session, user_id: int, mode: str) -> dict:
    """What the Buffer Settings page shows."""
    saved = keys(db, user_id)
    rows = channels(db, user_id, mode)
    up_next = choose_from(db, [c for c in rows if c.enabled])
    return {
        "connected": bool(saved), "max_keys": MAX_KEYS,
        "keys": [{
            "id": item.id, "label": item.label, "last4": (decrypt(item.api_key_enc) or "")[-4:], "saved_at": item.saved_at, "synced_at": item.synced_at,
            "error": item.error, "accounts": sum(1 for c in rows if c.key_id == item.id), "receiving": sum(1 for c in rows if c.key_id == item.id and c.enabled),
        } for item in saved],
        "public_url": push.is_public(push.base_url()),  # Buffer fetches clips from this server, so it needs a public address
        "time_zone": member_zone(db, user_id),
        "up_next": up_next.id if up_next else None,  # the account whose turn it is
        "channels": [channel_view(db, c) for c in rows],
    }


def channel_status(db: Session, channel: BufferChannel, now: datetime | None = None) -> dict:
    """How one account is doing: uploaded and failed — today, 7 days, 30 days, in all — what is waiting, and its latest clips."""
    now = now or utcnow()
    zone = zone_of(db, channel)
    lines = list(db.scalars(select(BufferLog).where(BufferLog.buffer_channel_id == channel.id).order_by(func.coalesce(BufferLog.done_at, BufferLog.created_at).desc(), BufferLog.id.desc())))
    today = slots.day_of(now, zone)
    periods = {
        "today": lambda at: slots.day_of(at, zone) == today, "week": lambda at: now - at < timedelta(days=7),
        "month": lambda at: now - at < timedelta(days=30), "lifetime": lambda at: True,
    }
    count = lambda state: {name: sum(1 for line in lines if line.state == state and line.done_at and test(line.done_at)) for name, test in periods.items()}  # noqa: E731
    return {
        "id": channel.id, "name": channel.name, "time_zone": zone, "uploaded": count("published"), "failed": count("failed"),
        "waiting": sum(1 for line in lines if line.state == "scheduled"),  # handed to Buffer, waiting for its time there
        "sending": db.scalar(select(func.count(Job.id)).where(Job.buffer_channel_id == channel.id, Job.status == JobStatus.UPLOADING)) or 0,
        "recent": [{"id": line.id, "title": line.title, "state": line.state, "due_at": line.due_at, "done_at": line.done_at, "error": line.error} for line in lines[:40]],
    }


# ---------------------------------------------------------------- handing a clip over

def _record(db: Session, job: Job, channel: BufferChannel, state: str, *, post_id: str | None, due_at: datetime | None = None, done_at: datetime | None = None, error: str | None = None) -> None:
    """One line per post: handing a clip over starts it, and Buffer's answer later finishes it."""
    line = db.scalar(select(BufferLog).where(BufferLog.job_id == job.id, BufferLog.post_id == post_id).order_by(BufferLog.id.desc())) if post_id else None
    if line:
        line.state, line.done_at, line.error = state, done_at, error
        line.due_at = due_at or line.due_at
    else:
        title = (job.rewritten_title or job.video.original_title or "")[:300]
        db.add(BufferLog(user_id=channel.user_id, buffer_channel_id=channel.id, job_id=job.id, title=title, post_id=post_id, state=state, due_at=due_at, done_at=done_at, error=error))


def choose_from(db: Session, enabled: list[BufferChannel]) -> BufferChannel | None:
    """Whose turn it is: of the accounts that can take a clip, the one that has waited longest for one.

    An account that never had a clip goes first; ties go in the order the page lists them (key, then name).
    Every switched-on account, across all the member's keys, so gets clips in turn and none is left out.
    """
    now = utcnow()
    ready = [c for c in enabled if next_slot(db, c, now) is not None]
    order = {c.id: index for index, c in enumerate(sorted(ready, key=lambda c: ((c.key.position if c.key else 0), c.key_id or 0, c.name.lower(), c.id)))}
    return min(ready, key=lambda c: (c.last_picked_at is not None, c.last_picked_at or now, order[c.id]), default=None)


def choose(db: Session, job: Job) -> tuple[BufferChannel | None, str | None]:
    """The account a clip goes to: the one chosen for it, or the one whose turn it is."""
    video = job.video
    enabled = [c for c in channels(db, video.user_id, video.mode) if c.enabled and c.key_id]
    if not enabled:
        return None, NO_ACCOUNT
    if job.buffer_channel_id:
        named = next((c for c in enabled if c.id == job.buffer_channel_id), None)
        if named:
            return (named, None) if next_slot(db, named) else (None, NO_TIMES)
    best = choose_from(db, enabled)
    return (best, None) if best else (None, NO_TIMES)


def _defer(job: Job, delta: timedelta, reason: str) -> str:
    job.next_check_at = utcnow() + delta
    job.error = reason
    return "deferred"


def publish(db: Session, job: Job) -> str:
    """Hand one READY job to Buffer. Returns 'scheduled' | 'deferred' | 'skipped' | 'failed'."""
    from app.services import pipeline  # the pipeline calls this module

    if job.status != JobStatus.READY or job.buffer_post_id:
        return "skipped"
    video = job.video
    if not uses_buffer(db, video.user_id):
        return _defer(job, timedelta(minutes=10), NO_KEY)
    channel, reason = choose(db, job)
    if channel is None:
        return _defer(job, timedelta(minutes=2), reason)  # nothing is lost: it is sent once an account can take it
    if not video.rendered_file_path:
        pipeline.mark_failed(db, job.id, "The rendered file is no longer stored — it was deleted after the retention period")
        return "failed"
    base = push.base_url()
    if not push.is_public(base):
        return _defer(job, timedelta(minutes=10), NO_PUBLIC_URL)
    slot = next_slot(db, channel)
    if slot is None:
        return _defer(job, timedelta(minutes=2), NO_TIMES)

    # Atomic claim: only one worker can move READY → UPLOADING, and only if nothing was ever handed over.
    claimed = db.execute(
        update(Job).where(Job.id == job.id, Job.status == JobStatus.READY, Job.buffer_post_id.is_(None))
        .values(status=JobStatus.UPLOADING, attempts=Job.attempts + 1).execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        return "skipped"
    db.refresh(job)
    job.error = None
    job.buffer_channel_id = channel.id
    channel.last_picked_at = utcnow()  # its turn is used, even if Buffer refuses: the next clip tries the next account
    job.share_token = job.share_token or secrets.token_hex(24)
    job_event(db, job, JobStatus.UPLOADING, f"Handing over to Buffer for {channel.name}")
    db.commit()
    try:
        post = api.create_post(decrypt(channel.key.api_key_enc) or "", channel_id=channel.buffer_id, body=pipeline.compose_post_text(job), due_at=slot,
                               video_url=f"{base}/api/public/clip/{job.share_token}/clip.mp4")
    except BufferError as exc:
        _record(db, job, channel, "failed", post_id=None, done_at=utcnow(), error=str(exc))  # a clip Buffer never took is still part of the account's history
        if job.attempts < MAX_ATTEMPTS:
            job_event(db, job, JobStatus.READY, f"Buffer attempt {job.attempts} failed — retrying")
            return _defer(job, timedelta(minutes=5 * job.attempts), str(exc))
        pipeline.mark_failed(db, job.id, str(exc))
        return "failed"
    due = _parse(post.get("dueAt")) or slot
    job.buffer_post_id, job.buffer_due_at = str(post["id"]), due
    job.publish_mode = "buffer"
    job.next_check_at = due + CHECK_AFTER
    when = due.astimezone(ZoneInfo(zone_of(db, channel))).strftime("%a %d %b, %I:%M %p")
    job_event(db, job, JobStatus.SCHEDULED, f"Scheduled in Buffer on {channel.name} for {when}")
    _record(db, job, channel, "scheduled", post_id=job.buffer_post_id, due_at=due)
    activity.record(db, "Publisher", f"Video #{video.id} handed to Buffer for {channel.name} · goes out {when}", event="buffer_scheduled", job_id=job.id, user_id=video.user_id)
    return "scheduled"


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=utcnow().tzinfo)


def check(db: Session, job_id: int) -> str | None:
    """Ask Buffer what became of a post whose time has passed: published, or failed with Buffer's reason."""
    from app.services import pipeline

    job = db.get(Job, job_id)
    if not job or job.status != JobStatus.SCHEDULED or not job.buffer_post_id:
        return job.status if job else None
    now = utcnow()
    channel = job.buffer_channel
    saved = channel.key if channel else None

    def fail(message: str) -> str:
        if channel:
            _record(db, job, channel, "failed", post_id=job.buffer_post_id, done_at=now, error=message)
        pipeline.mark_failed(db, job.id, message)
        return job.status

    if not saved:
        return fail("The Buffer API key was removed before this post was published.")
    try:
        post = api.post(decrypt(saved.api_key_enc) or "", job.buffer_post_id)
    except BufferError as exc:
        log.info("could not ask Buffer about job %s: %s", job.id, exc)
        job.next_check_at = now + CHECK_EVERY  # asked about again later
        return job.status
    state = str(post.get("status") or "").lower()
    if state == "sent":
        sent = _parse(post.get("sentAt")) or now
        job.posted_at, job.next_check_at, job.error = sent, None, None
        job.buffer_link = post.get("externalLink") or None
        name = channel.name if channel else "the account"
        job_event(db, job, JobStatus.POSTED, f"Published by Buffer on {name}")
        if channel:
            _record(db, job, channel, "published", post_id=job.buffer_post_id, done_at=sent)
        activity.record(db, "Publisher", f"Video #{job.video_id} published by Buffer on {name} · “{(job.rewritten_title or job.video.original_title or '')[:40]}”", event="published", job_id=job.id, user_id=job.video.user_id)
    elif state in ("error", "failed"):
        return fail(f"Buffer could not publish it: {(post.get('error') or {}).get('message') or 'no reason given'}")
    elif job.buffer_due_at and now - job.buffer_due_at > GIVE_UP:
        return fail("Buffer has not published this post a day after its time. Check it in Buffer.")
    else:
        job.next_check_at = now + CHECK_EVERY
    job.buffer_checked_at = now
    return job.status


def shared_clip(db: Session, token: str) -> Video | None:
    """The video behind a private link, while Buffer may still need it."""
    job = db.scalar(select(Job).where(Job.share_token == token))
    return job.video if job and job.status in (JobStatus.UPLOADING, JobStatus.SCHEDULED) and job.video.rendered_file_path else None
