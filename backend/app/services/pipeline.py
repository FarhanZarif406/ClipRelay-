"""Processing pipeline.

Detected → Downloading → Rendering → (Rewriting) → (Awaiting approval) → Ready → Uploading → Posted → Monitoring
→ Scheduled at Buffer → Posted / Failed

The caption is rewritten alongside the download and the edit, because it needs only the metadata. Detection
(which videos enter the pipeline) lives in `app.services.detection`.

Every function takes a SQLAlchemy session and returns plain values; the task layer (`app.workers.tasks`)
decides what to enqueue next. This keeps the pipeline unit-testable.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.integrations.http import ApiError
from app.models import (
    CaptionStatus,
    Job,
    JobStatus,
    Video,
    utcnow,
)
from app.db import session_scope
from app.integrations import llm
from app.services import activity, buffer, library, looks, media, notify, prompts, rules, sources
from app.services.activity import job_event
from app.services.storage import get_storage

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
PROCESS_LEASE = timedelta(minutes=45)  # a download plus a render may take a while
MAX_STAGE_ATTEMPTS = 3


# ---------------------------------------------------------------- helpers

def cap_day_start(timezone_name: str, now: datetime | None = None) -> datetime:
    """Midnight of the current day in the cap-reset timezone — the moment the daily caps start counting."""
    local = (now or utcnow()).astimezone(ZoneInfo(timezone_name or "UTC"))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


def compose_post_text(job: Job) -> str:
    caption = (job.rewritten_caption or job.video.original_title or "").strip()
    title = (job.rewritten_title or "").strip()
    parts = [title] if title and title.lower() not in caption.lower() else []
    parts.append(caption)
    tags = " ".join(f"#{t.lstrip('#')}" for t in (job.rewritten_tags or []))
    if tags:
        parts.append(tags)
    return "\n\n".join(p for p in parts if p)[:2200]


def mark_failed(db: Session, job_id: int, error: str) -> None:
    job = db.get(Job, job_id)
    if not job or job.status in JobStatus.TERMINAL:
        return
    job.error = error[:2000]
    job.next_check_at = None
    job_event(db, job, JobStatus.FAILED, f"Failed: {error[:300]}")
    target = f" for {job.buffer_channel.name}" if job.buffer_channel else ""
    activity.record(db, "Publisher", f"Job #{job.id} failed{target}: {error[:200]}", level="error", event="job_failed", job_id=job.id)
    notify.send(db, "failure", f"Job #{job.id} failed{target}: {error[:200]}", job_id=job.id)


# ---------------------------------------------------------------- 1. job creation

def create_job(db: Session, video: Video, *, prompt_template_id: int | None = None) -> Job:
    """Exactly one job per source video: one YouTube upload becomes one post."""
    existing = db.scalar(select(Job).where(Job.video_id == video.id))
    if existing:
        return existing
    job = Job(
        video_id=video.id,
        prompt_template_id=prompt_template_id,
        approval_required=bool(rules.for_video(db, video)["approval_required"]),
        status=JobStatus.FETCHED,
        caption_status=CaptionStatus.PENDING,
        next_check_at=utcnow() + LEASE,
    )
    db.add(job)
    db.flush()
    source = f" from {video.channel.display_name}" if video.channel else ""
    if video.parent_id:
        job_event(db, job, JobStatus.FETCHED, f"Clip {video.clip_start or 0:.0f}s–{video.clip_end or 0:.0f}s of “{(video.parent.original_title if video.parent else '')[:60]}”")
    else:
        job_event(db, job, JobStatus.FETCHED, f"New upload detected{source} · {video.duration_sec or 0:.0f}s")
    return job


def create_podcast_job(db: Session, video: Video) -> Job:
    """The job that analyses a whole podcast. It is never posted and has no caption: its clips are."""
    job = create_job(db, video)
    job.caption_status = CaptionStatus.DONE
    job.approval_required = False
    return job


# ---------------------------------------------------------------- 2. download, edit and caption

def _advance(db: Session, job: Job) -> str:
    """Called when the render or the caption finishes: move on once both are done.

    The two run side by side in separate workers, so this side's work is saved first and the other side's
    progress is read fresh from the database before deciding.
    """
    db.commit()
    db.refresh(job)
    db.refresh(job.video)
    if not job.video.rendered_file_path or job.status not in JobStatus.PROCESSING:
        return job.status
    if job.caption_status == CaptionStatus.PENDING:
        job.next_check_at = utcnow() + timedelta(minutes=2)
        if job.status != JobStatus.REWRITING:
            job_event(db, job, JobStatus.REWRITING, "Rendered — waiting for the caption")
        return job.status
    job.next_check_at = None
    job.attempts = 0
    job.error = None
    # Read at this moment, not at detection, so switching approval on or off applies to the next job to finish.
    job.approval_required = bool(rules.for_video(db, job.video)["approval_required"])
    if job.approval_required:
        job_event(db, job, JobStatus.AWAITING_APPROVAL, "Waiting in the review queue")
    else:
        job_event(db, job, JobStatus.READY, "Ready to upload")
    return job.status


def _stage_failed(db: Session, job: Job, stage: str, error: str) -> str:
    """Retry a stage three times with exponential backoff, then mark the job failed."""
    job.attempts += 1
    if job.attempts >= MAX_STAGE_ATTEMPTS:
        mark_failed(db, job.id, f"{stage} failed after {job.attempts} attempts: {error}")
        return job.status
    delay = 60 * 2 ** (job.attempts - 1)
    job.next_check_at = utcnow() + timedelta(seconds=delay)
    job.error = f"{stage} failed: {error}"
    job_event(db, job, job.status, f"{stage} attempt {job.attempts} failed ({error}) — retrying in {delay // 60} min")
    activity.record(db, stage, f"Video #{job.video_id}: attempt {job.attempts} failed — {error}", level="warning", event="stage_retry", job_id=job.id)
    return job.status


class JobStopped(Exception):
    """The operator stopped the job while it was downloading or rendering. Not a failure: nothing is retried."""


STOPPED = (JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.PAUSED)  # a running download or render halts on any of these


def progress_writer(job_id: int):
    """A callback that stores how far a download or render has got (0–100), for the Live Status page.

    It writes through a short session of its own, at most every few seconds, so the long-running stage
    never holds the database. The same visit checks whether the operator pressed Stop: if so it raises
    `JobStopped`, which is how a download or a render that is already running is actually brought to a halt.
    """
    state = {"value": -1, "at": 0.0}

    def write(percent: float) -> None:
        value = max(0, min(100, int(percent)))
        now = time.monotonic()
        if value < 100 and now - state["at"] < 2.5:
            return
        state["at"] = now
        status = None
        try:
            with session_scope() as other:
                status = other.scalar(select(Job.status).where(Job.id == job_id))
                if status not in STOPPED and value != state["value"]:
                    other.execute(update(Job).where(Job.id == job_id).values(progress=value).execution_options(synchronize_session=False))
        except Exception as exc:  # progress is a nicety: never let it break a download
            log.debug("could not store progress for job %s: %s", job_id, exc)
        state["value"] = value
        if status in STOPPED:
            raise JobStopped(f"job {job_id} was stopped")

    return write


def _stopped(db: Session, job: Job) -> bool:
    """Read the job afresh: did the operator stop it while this stage was running?"""
    db.rollback()
    db.refresh(job)
    return job.status in STOPPED


def _set_progress(db: Session, job: Job, value: int | None) -> None:
    db.execute(update(Job).where(Job.id == job.id).values(progress=value).execution_options(synchronize_session=False))
    job.progress = value


def process_video(db: Session, job_id: int) -> str | None:
    """Download the original and apply the edits. A failure is retried from the stage that broke."""
    job = db.get(Job, job_id)
    if not job or job.status not in (JobStatus.FETCHED, JobStatus.DOWNLOADING, JobStatus.RENDERING):
        return job.status if job else None
    video = job.video
    if video.is_podcast_source:
        from app.services import podcasts

        return podcasts.split(db, job)
    storage = get_storage()
    job.next_check_at = utcnow() + PROCESS_LEASE

    if not video.source_file_path:
        if job.status != JobStatus.DOWNLOADING:
            job_event(db, job, JobStatus.DOWNLOADING, "Downloading the clip's section from YouTube" if video.parent_id else "Downloading from YouTube")
        _set_progress(db, job, 0)
        db.commit()
        try:
            path = sources.get_adapter().download(video, progress_writer(job.id))
            info = media.probe(path)
        except JobStopped:
            db.rollback()
            db.refresh(job)
            return job.status
        except (sources.SourceError, media.ProbeError) as exc:
            return _stage_failed(db, job, "Download", str(exc))
        if _stopped(db, job):  # stopped during the last moments of the download: keep nothing, start nothing
            os.remove(path)
            return job.status
        video.width, video.height, video.size_bytes = info.width, info.height, os.path.getsize(path)
        video.duration_sec = round(info.duration, 2) if video.parent_id else (video.duration_sec or round(info.duration, 2))
        video.source_file_path = storage.save(path, f"source/{video.id}.mp4")
        job.attempts = 0
        activity.record(db, "Download", f"Video #{video.id} downloaded · {video.size_bytes / 1_048_576:.1f} MB", event="downloaded", job_id=job.id)

    look = looks.for_video(db, video)  # the channel's preset, or the member's default editing rules
    summary = looks.summary(look)
    font = library.font_file(db, video.user_id, look["hook"]["font"]) if look["hook"]["enabled"] else None
    mark = library.watermark(db, video.user_id) if look["watermark"]["enabled"] else None
    track = library.next_track(db, video.user_id) if look["music"]["enabled"] else None
    hook_text = hook_words(look, video.original_title or "") if look["hook"]["enabled"] else None
    if job.status != JobStatus.RENDERING:
        job_event(db, job, JobStatus.RENDERING, f"Rendering · {summary}")
    _set_progress(db, job, 0)
    db.commit()
    try:
        with storage.local_copy(video.source_file_path) as source_path:
            rendered = media.render(
                source_path, look, hook_text=hook_text, font_file=font, watermark_file=str(library.path_of(mark)) if mark else None,
                music_file=str(library.path_of(track)) if track else None, on_progress=progress_writer(job.id),
            )
    except JobStopped:
        db.rollback()
        db.refresh(job)
        return job.status
    except (media.RenderError, OSError) as exc:
        return _stage_failed(db, job, "Render", str(exc))
    if _stopped(db, job):
        os.remove(rendered.path)
        return job.status
    video.rendered_file_path = storage.save(rendered.path, f"videos/{video.id}.mp4")
    if track:
        library.mark_used(track)  # the member's next clip gets the next track
    if rendered.note == "hook_font_missing":
        activity.record(db, "Render", f"Video #{video.id}: the hook text was left out — no bold font was found on the server (set FONT_FILE)", level="warning", event="hook_font_missing", job_id=job.id)
    _set_progress(db, job, None)
    activity.record(db, "Render", f"Video #{video.id} rendered · {summary}", event="rendered", job_id=job.id)
    return _advance(db, job)


HOOK_PROMPT = (
    "Write one short line of 4 to 9 words to show on screen at the start of a short video, to make a viewer stop scrolling. "
    "It must fit what the title promises, in the same language, with no hashtags, emojis or quotes. Answer with the line only.\n\nTitle: {title}"
)


def hook_words(look: dict, title: str) -> str:
    """The words of the hook text: a line written by the AI model from the title, or the title itself."""
    if look["hook"]["source"] == "ai" and title:
        try:
            line = " ".join(llm.complete(HOOK_PROMPT.format(title=title), max_tokens=40).split()).strip("\"'“”‘’ ")
            if line:
                return line[:90]
        except (ApiError, RuntimeError, ValueError) as exc:
            log.info("hook text: the AI model gave no line (%s); the title is used", exc)
    return title


def fallback_caption(video: Video, values: dict) -> dict:
    tags = prompts.parse_hashtags(values.get("fallback_hashtags", ""))
    return {"title": video.original_title, "caption": video.original_title, "tags": tags[: int(values["hashtag_count"])]}


def rewrite_job(db: Session, job_id: int) -> str | None:
    """Write the caption and hashtags. A model failure never fails the job: it falls back to the title."""
    job = db.get(Job, job_id)
    if not job or job.status not in JobStatus.PROCESSING:
        return job.status if job else None
    if job.caption_status != CaptionStatus.PENDING:
        return _advance(db, job)  # the caption was already written; make sure the job has moved on
    video = job.video
    values = rules.for_video(db, video)
    count = int(values["hashtag_count"])
    channel_name = video.channel.display_name if video.channel else ""
    template = prompts.resolve_template(db, job.prompt_template_id)
    try:
        if template:
            result = prompts.rewrite(
                title_prompt=template.title_prompt, caption_prompt=template.caption_prompt, hashtags_prompt=template.hashtags_prompt,
                title=video.original_title, caption=video.original_caption, tags=video.original_tags or [],
                niche=template.niche, channel=channel_name, hashtag_count=count, provider_id=template.llm_provider_id,
            )
            job.prompt_template_id = template.id
            used = f"prompt “{template.name}”"
        else:
            raise ApiError("No prompt template is enabled in Prompt Studio")
        result["tags"] = result["tags"][:count]
        job.caption_status = CaptionStatus.DONE
        activity.record(db, "AI rewrite", f"Video #{video.id}: caption rewritten with {used}", event="rewritten", job_id=job.id)
    except (ApiError, RuntimeError, ValueError) as exc:
        result = fallback_caption(video, values)
        job.caption_status = CaptionStatus.FALLBACK
        activity.record(
            db, "AI rewrite", f"Video #{video.id}: caption model failed, using the original title — {str(exc)[:200]}",
            level="warning", event="caption_fallback", job_id=job.id,
        )
    job.rewritten_title, job.rewritten_caption, job.rewritten_tags = result["title"], result["caption"], result["tags"]
    note = "Caption written" if job.caption_status == CaptionStatus.DONE else "Caption model failed — using the original title (edit it before publishing)"
    db.commit()
    db.refresh(job)  # the download and render moved the job on in the meantime
    job_event(db, job, job.status, note)
    return _advance(db, job)


# ---------------------------------------------------------------- 3. upload

def upload_job(db: Session, job_id: int) -> str:
    """Hand one READY job to Buffer, which publishes it. Returns 'scheduled' | 'deferred' | 'skipped' | 'failed'."""
    job = db.get(Job, job_id)
    if not job or job.status != JobStatus.READY:
        return "skipped"
    return buffer.publish(db, job)


# ---------------------------------------------------------------- 5. manual actions

def retry_job(db: Session, job: Job) -> str:
    """Start a failed or cancelled job again, from the stage it had reached."""
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise ValueError(f"Only failed or cancelled jobs can be retried (job is {job.status})")
    job.error = None
    job.attempts = 0
    job.buffer_post_id = job.buffer_due_at = job.buffer_checked_at = None  # a failed Buffer post is handed over afresh
    job.next_check_at = None
    if not job.video.rendered_file_path:
        if job.video.files_deleted_at:
            raise ValueError("The files of this video were deleted after the retention period")
        job_event(db, job, JobStatus.FETCHED, "Retry requested — processing again")
    elif job.caption_status == CaptionStatus.PENDING:
        job_event(db, job, JobStatus.REWRITING, "Retry requested — writing the caption again")
    else:
        job_event(db, job, JobStatus.READY, "Retry requested")
    return job.status


STAGE_NAMES = {
    JobStatus.FETCHED: "waiting to download", JobStatus.DOWNLOADING: "downloading", JobStatus.RENDERING: "editing",
    JobStatus.REWRITING: "writing the caption", JobStatus.READY: "waiting to upload",
}


def pause_job(db: Session, job: Job, *, reason: str | None = None) -> None:
    """Hold a video where it is. A download or an edit that is running stops within a few seconds (see `progress_writer`);
    what was already finished, such as the downloaded file, is kept for Resume."""
    if job.status not in JobStatus.PAUSABLE:
        raise ValueError(f"A video can be paused only while it is downloading, editing, getting its caption or waiting to upload (it is {job.status})")
    if job.video.is_podcast_source:
        raise ValueError("A podcast that is being split into clips cannot be paused; its clips can")
    job.paused_status = job.status
    job.next_check_at = None
    job.progress = None
    job_event(db, job, JobStatus.PAUSED, f"{reason or 'Paused by the operator'} while {STAGE_NAMES[job.status]}")


def resume_job(db: Session, job: Job, *, reason: str | None = None) -> str:
    """Carry on from the stage the video had reached. Returns the status it resumes in."""
    if job.status != JobStatus.PAUSED:
        raise ValueError("Only a paused video can be resumed")
    video = job.video
    if not video.rendered_file_path:
        if video.files_deleted_at:
            raise ValueError("The files of this video were deleted after the retention period")
        # Downloaded already: only the edit is left. A download or an edit that was cut short starts again.
        status, left = (JobStatus.RENDERING, "editing") if video.source_file_path else (JobStatus.FETCHED, "downloading")
    elif job.caption_status == CaptionStatus.PENDING:
        status, left = JobStatus.REWRITING, "writing the caption"
    elif job.paused_status == JobStatus.READY or not job.approval_required:
        status, left = JobStatus.READY, "uploading"
    else:
        status, left = JobStatus.AWAITING_APPROVAL, "waiting for approval"
    job.paused_status = None
    job.next_check_at = None
    job.attempts = 0
    job_event(db, job, status, f"{reason or 'Resumed by the operator'} — carries on {left}")
    return status


def cancel_job(db: Session, job: Job) -> None:
    if job.status not in JobStatus.PROCESSING | {JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.FAILED, JobStatus.PAUSED}:
        raise ValueError(f"Job cannot be cancelled while {job.status}")
    was = job.status
    job.paused_status = None
    job.next_check_at = None
    job.progress = None
    # A download or render that is running notices this within a few seconds and stops (see `progress_writer`).
    note = {JobStatus.DOWNLOADING: "Download stopped by the operator", JobStatus.RENDERING: "Editing stopped by the operator"}.get(was, "Cancelled by the operator")
    job_event(db, job, JobStatus.CANCELLED, note)


def reject_job(db: Session, job: Job, reason: str) -> None:
    """Review queue: the operator decides this video is not published."""
    if job.status != JobStatus.AWAITING_APPROVAL:
        raise ValueError("Job is not awaiting approval")
    job.next_check_at = None
    job.reject_reason = reason.strip()[:1000]
    job_event(db, job, JobStatus.CANCELLED, f"Rejected: {job.reject_reason}")


def approve_job(db: Session, job: Job) -> None:
    if job.status != JobStatus.AWAITING_APPROVAL:
        raise ValueError("Job is not awaiting approval")
    job.next_check_at = None
    job_event(db, job, JobStatus.READY, "Approved — ready to upload")


# ---------------------------------------------------------------- 6. scheduler

def scheduler_tick(db: Session) -> dict:
    """Called by the scheduler every few seconds. The pipeline runs around the clock: there is no schedule rule."""
    now = utcnow()
    out: dict[str, list] = {"process": [], "rewrites": [], "uploads": [], "buffer_checks": []}
    from app.services import system  # the main switch; it imports this module

    if not system.is_on(db):
        return out  # switched off by the admin: nothing moves until it is on again

    def lease(status: str, limit: int) -> list[Job]:
        jobs = db.scalars(
            select(Job)
            .where(Job.status == status, (Job.next_check_at.is_(None)) | (Job.next_check_at <= now))
            .order_by(Job.id)
            .limit(limit)
        ).all()
        return list(jobs)

    # Download and render: new jobs, plus jobs whose retry delay (or a crashed worker's lease) has run out.
    for status in (JobStatus.FETCHED, JobStatus.DOWNLOADING, JobStatus.RENDERING):
        for job in lease(status, 20):
            job.next_check_at = now + PROCESS_LEASE
            out["process"].append(job.id)
            if job.caption_status == CaptionStatus.PENDING:
                out["rewrites"].append(job.id)
    for job in lease(JobStatus.REWRITING, 50):
        job.next_check_at = now + LEASE
        out["rewrites"].append(job.id)

    for job in lease(JobStatus.READY, 50):
        job.next_check_at = now + LEASE
        out["uploads"].append((job.id, 0))
    # Posts handed to Buffer whose time has passed: ask what became of them.
    for job in lease(JobStatus.SCHEDULED, 50):
        job.next_check_at = now + LEASE
        out["buffer_checks"].append(job.id)
    db.flush()
    return out


# ---------------------------------------------------------------- 7. file retention

def cleanup_files(db: Session, now: datetime | None = None) -> int:
    """Delete downloaded and rendered files once they are no longer needed. The rows are kept forever.

    Published videos lose their files `file_retention_days` after publishing; videos whose job was
    rejected, cancelled or failed lose them the same number of days after the job stopped.
    """
    now = now or utcnow()
    storage = get_storage()
    deleted = 0
    rows = db.execute(
        select(Video, Job)
        .join(Job, Job.video_id == Video.id)
        .where(or_(Video.source_file_path.is_not(None), Video.rendered_file_path.is_not(None)))
        .where(or_(Job.posted_at.is_not(None), Job.status.in_([JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.CLIPPED])))
    ).unique().all()
    retention: dict[int | None, int] = {}
    for video, job in rows:
        if video.channel_id not in retention:
            retention[video.channel_id] = int(rules.for_video(db, video)["file_retention_days"])
        finished = job.posted_at or job.updated_at
        if job.status == JobStatus.UPLOADING or finished > now - timedelta(days=retention[video.channel_id]):
            continue
        for key in (video.source_file_path, video.rendered_file_path):
            if key:
                storage.delete(key)
        video.source_file_path = video.rendered_file_path = None
        video.files_deleted_at = now
        deleted += 1
    if deleted:
        activity.record(db, "Storage", f"Deleted the files of {deleted} video(s) past the retention period", event="files_deleted")
    db.flush()
    return deleted
