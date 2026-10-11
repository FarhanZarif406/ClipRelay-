"""Processing pipeline.

Detected → Downloading → Rendering → (Rewriting) → (Awaiting approval) → Ready → Uploading → Posted → Monitoring
→ Clean / Violated / Failed

The caption is rewritten alongside the download and the edit, because it needs only the metadata. Detection
(which videos enter the pipeline) lives in `app.services.detection`.

Every function takes a SQLAlchemy session and returns plain values; the task layer (`app.workers.tasks`)
decides what to enqueue next. This keeps the pipeline unit-testable.
"""

import logging
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.integrations import tiktok
from app.integrations.http import ApiError, AuthError, RateLimitError, backoff_delay
from app.models import (
    CaptionStatus,
    Job,
    JobStatus,
    TikTokAccount,
    TikTokStatus,
    Video,
    Violation,
    utcnow,
)
from app.services import activity, media, notify, prompts, rules, sources, tokens, workspace_settings
from app.services.activity import job_event
from app.services.storage import get_storage

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
PROCESS_LEASE = timedelta(minutes=45)  # a download plus a render may take a while
MAX_UPLOAD_ATTEMPTS = 3
MAX_STAGE_ATTEMPTS = 3
ACTIVE_ACCOUNT = (TikTokStatus.ACTIVE, TikTokStatus.EXPIRING)
PROCESSING_STATES = {"PROCESSING_UPLOAD", "PROCESSING_DOWNLOAD", "SEND_TO_USER_INBOX"}


# ---------------------------------------------------------------- helpers

def within_window(policy: dict, now: datetime | None = None) -> bool:
    now = (now or utcnow()).astimezone(ZoneInfo(policy.get("timezone") or "UTC"))
    if now.weekday() not in policy.get("active_days", list(range(7))):
        return False
    start = policy.get("active_window_start", "00:00")
    end = policy.get("active_window_end", "23:59")
    current = now.strftime("%H:%M")
    return start <= current <= end if start <= end else (current >= start or current <= end)


def start_of_day(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def cap_day_start(timezone_name: str, now: datetime | None = None) -> datetime:
    """Midnight of the current day in the cap-reset timezone — the moment the daily caps start counting."""
    local = (now or utcnow()).astimezone(ZoneInfo(timezone_name or "UTC"))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(ZoneInfo("UTC"))


def account_cap(account: TikTokAccount, rule_values: dict) -> int:
    return account.daily_cap or int(rule_values["uploads_per_tiktok_account_per_day"])


def account_load(db: Session, account_id: int, since: datetime, *, exclude_job_id: int | None = None) -> int:
    """Uploads counted against an account's daily cap: published since `since`, plus everything still on its way."""
    stmt = select(func.count(Job.id)).where(
        Job.tiktok_account_id == account_id,
        or_(Job.posted_at >= since, (Job.posted_at.is_(None)) & Job.status.in_(JobStatus.PENDING)),
    )
    if exclude_job_id:
        stmt = stmt.where(Job.id != exclude_job_id)
    return db.scalar(stmt) or 0


def posts_since(db: Session, account_id: int, since: datetime) -> int:
    return db.scalar(
        select(func.count(Job.id)).where(Job.tiktok_account_id == account_id, Job.posted_at >= since)
    ) or 0


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
    target = f" for @{job.tiktok_account.username}" if job.tiktok_account else ""
    activity.record(db, "Publisher", f"Job #{job.id} failed{target}: {error[:200]}", level="error", event="job_failed", job_id=job.id)
    notify.send(db, "failure", f"Job #{job.id} failed{target}: {error[:200]}", job_id=job.id)


# ---------------------------------------------------------------- 1. job creation

def pick_account(db: Session, video: Video) -> TikTokAccount | None:
    """The channel's default TikTok account, or the least-loaded connected account when it has none."""
    channel = video.channel
    if channel and channel.default_tiktok_account and channel.default_tiktok_account.status in ACTIVE_ACCOUNT:
        return channel.default_tiktok_account
    accounts = list(db.scalars(select(TikTokAccount).where(TikTokAccount.status.in_(ACTIVE_ACCOUNT)).order_by(TikTokAccount.id)))
    if not accounts:
        return None
    since = cap_day_start(rules.global_values(db)["cap_reset_timezone"])
    return min(accounts, key=lambda a: (account_load(db, a.id, since), a.id))


def create_job(db: Session, video: Video, account: TikTokAccount | None, *, prompt_template_id: int | None = None) -> Job:
    """Exactly one job per source video: one YouTube upload becomes one TikTok post."""
    existing = db.scalar(select(Job).where(Job.video_id == video.id))
    if existing:
        return existing
    job = Job(
        video_id=video.id,
        tiktok_account_id=account.id if account else None,
        prompt_template_id=prompt_template_id,
        approval_required=bool(rules.effective(db, video.channel_id)["approval_required"]),
        status=JobStatus.FETCHED,
        caption_status=CaptionStatus.PENDING,
        next_check_at=utcnow() + LEASE,
    )
    db.add(job)
    db.flush()
    source = f" from {video.channel.display_name}" if video.channel else ""
    job_event(db, job, JobStatus.FETCHED, f"New upload detected{source} · {video.duration_sec or 0:.0f}s")
    if account is None:
        job.error = "No active TikTok account connected"
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
    job.approval_required = bool(rules.effective(db, job.video.channel_id)["approval_required"])
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


def process_video(db: Session, job_id: int) -> str | None:
    """Download the original and apply the edits. A failure is retried from the stage that broke."""
    job = db.get(Job, job_id)
    if not job or job.status not in (JobStatus.FETCHED, JobStatus.DOWNLOADING, JobStatus.RENDERING):
        return job.status if job else None
    video = job.video
    storage = get_storage()
    job.next_check_at = utcnow() + PROCESS_LEASE

    if not video.source_file_path:
        if job.status != JobStatus.DOWNLOADING:
            job_event(db, job, JobStatus.DOWNLOADING, "Downloading from YouTube")
        db.commit()
        try:
            path = sources.get_adapter().download(video)
            info = media.probe(path)
        except (sources.SourceError, media.ProbeError) as exc:
            return _stage_failed(db, job, "Download", str(exc))
        video.width, video.height, video.size_bytes = info.width, info.height, os.path.getsize(path)
        video.duration_sec = video.duration_sec or round(info.duration, 2)
        video.source_file_path = storage.save(path, f"source/{video.id}.mp4")
        job.attempts = 0
        activity.record(db, "Download", f"Video #{video.id} downloaded · {video.size_bytes / 1_048_576:.1f} MB", event="downloaded", job_id=job.id)

    values = rules.effective(db, video.channel_id)
    speed, flip, keep_audio = float(values["speed"]), bool(values["horizontal_flip"]), bool(values["keep_audio"])
    summary = f"speed {speed:g}x · flip {'on' if flip else 'off'} · audio {'kept' if keep_audio else 'removed'}"
    if job.status != JobStatus.RENDERING:
        job_event(db, job, JobStatus.RENDERING, f"Rendering · {summary}")
    db.commit()
    try:
        with storage.local_copy(video.source_file_path) as source_path:
            rendered = media.render(source_path, speed=speed, flip=flip, keep_audio=keep_audio)
    except (media.RenderError, OSError) as exc:
        return _stage_failed(db, job, "Render", str(exc))
    video.rendered_file_path = storage.save(rendered, f"videos/{video.id}.mp4")
    activity.record(db, "Render", f"Video #{video.id} rendered · {summary}", event="rendered", job_id=job.id)
    return _advance(db, job)


def fallback_caption(video: Video, values: dict) -> dict:
    tags = prompts.parse_hashtags(values.get("fallback_hashtags", ""))
    return {"title": video.original_title, "caption": video.original_title, "tags": tags[: int(values["hashtag_count"])]}


def rewrite_job(db: Session, job_id: int) -> str | None:
    """Write the TikTok caption and hashtags. A model failure never fails the job: it falls back to the title."""
    job = db.get(Job, job_id)
    if not job or job.status not in JobStatus.PROCESSING:
        return job.status if job else None
    if job.caption_status != CaptionStatus.PENDING:
        return _advance(db, job)  # the caption was already written; make sure the job has moved on
    video = job.video
    values = rules.effective(db, video.channel_id)
    count = int(values["hashtag_count"])
    channel_name = video.channel.display_name if video.channel else ""
    custom_prompt = (values.get("caption_prompt") or "").strip()
    template = None if custom_prompt else prompts.resolve_template(db, job.prompt_template_id)
    try:
        if custom_prompt:
            result = prompts.rewrite_single(
                custom_prompt, title=video.original_title, description=video.original_caption,
                tags=video.original_tags or [], channel=channel_name, hashtag_count=count,
            )
            used = "the caption prompt from Settings"
        elif template:
            result = prompts.rewrite(
                title_prompt=template.title_prompt, caption_prompt=template.caption_prompt, hashtags_prompt=template.hashtags_prompt,
                title=video.original_title, caption=video.original_caption, tags=video.original_tags or [],
                niche=template.niche, channel=channel_name, hashtag_count=count, provider_id=template.llm_provider_id,
            )
            job.prompt_template_id = template.id
            used = f"prompt “{template.name}”"
        else:
            raise ApiError("No caption prompt is set and no prompt template is enabled")
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

def _defer(job: Job, delta: timedelta, reason: str) -> str:
    job.next_check_at = utcnow() + delta
    job.error = reason
    return "deferred"


def upload_job(db: Session, job_id: int, *, ignore_window: bool = False) -> str:
    """Upload one READY job. Returns 'posted' | 'deferred' | 'skipped' | 'failed'.

    In inbox mode the file lands in the account's TikTok inbox and a person finishes the post in the app;
    in direct mode the Content Posting API publishes it (TikTok forces it private until the app is audited).
    """
    job = db.get(Job, job_id)
    if not job or job.status != JobStatus.READY or job.tiktok_publish_id:
        return "skipped"
    policy = workspace_settings.get(db, "policy")
    account = job.tiktok_account
    now = utcnow()
    if account is None:
        return _defer(job, timedelta(hours=1), "No TikTok account assigned")
    if account.status not in (TikTokStatus.ACTIVE, TikTokStatus.EXPIRING):
        return _defer(job, timedelta(minutes=30), f"@{account.username} is {account.status} — reconnect it")
    if not ignore_window:
        if policy["automations_paused"]:
            return _defer(job, timedelta(minutes=5), "Automations paused")
        if not within_window(policy, now):
            return _defer(job, timedelta(minutes=10), "Outside the active publishing window")
    values = rules.effective(db, job.video.channel_id)
    cap = account_cap(account, values)
    if not job.video.forced and posts_since(db, account.id, cap_day_start(values["cap_reset_timezone"], now)) >= cap:
        return _defer(job, timedelta(hours=1), f"Daily cap of {cap} reached for @{account.username}")
    if not job.video.rendered_file_path:
        mark_failed(db, job.id, "The rendered file is no longer stored — it was deleted after the retention period")
        return "failed"
    if posts_since(db, account.id, now - timedelta(hours=1)) >= int(policy.get("hourly_cap", 4)):
        return _defer(job, timedelta(minutes=10), "Hourly cap reached")

    # Atomic claim: only one worker can move READY → UPLOADING, and only if nothing was ever published.
    claimed = db.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == JobStatus.READY, Job.tiktok_publish_id.is_(None))
        .values(status=JobStatus.UPLOADING, attempts=Job.attempts + 1)
        .execution_options(synchronize_session=False)
    ).rowcount
    if not claimed:
        return "skipped"
    db.refresh(job)
    job.error = None
    job_event(db, job, JobStatus.UPLOADING, f"Uploading to @{account.username}")
    db.commit()

    video = job.video
    mode = values["publish_mode"]
    privacy = None
    try:
        token = tokens.tiktok_token(db, account)
        creator = {}
        if mode == "direct":
            creator = tiktok.creator_info(token)
            options = creator.get("privacy_level_options") or ["SELF_ONLY"]
            privacy = job.privacy_level if job.privacy_level in options else account.default_privacy
            if privacy not in options:
                privacy = options[0]
            max_duration = creator.get("max_video_post_duration_sec")
            if max_duration and video.duration_sec and video.duration_sec > max_duration:
                mark_failed(db, job.id, f"Video is longer than @{account.username}'s {max_duration}s limit")
                return "failed"
        with get_storage().local_copy(video.rendered_file_path) as path:
            size = os.path.getsize(path)
            if mode == "direct":
                init = tiktok.init_direct_post(token, title=compose_post_text(job), privacy_level=privacy, video_size=size, creator=creator)
            else:
                init = tiktok.init_inbox_upload(token, video_size=size)
            job.tiktok_publish_id = init["publish_id"]
            job.privacy_level = privacy
            job.publish_mode = mode
            db.commit()  # persist publish_id before transferring bytes — the job can never be re-initialised
            tiktok.upload_file(init["upload_url"], path)
    except RateLimitError as exc:
        if job.tiktok_publish_id is None:
            job_event(db, job, JobStatus.READY, "TikTok rate limit hit — will retry")
            activity.record(db, "TikTok API", f"Rate limit for @{account.username}: {exc}", level="warning", event="rate_limited", job_id=job.id)
            return _defer(job, timedelta(minutes=15), str(exc))
        mark_failed(db, job.id, str(exc))
        return "failed"
    except AuthError as exc:
        mark_failed(db, job.id, str(exc))
        return "failed"
    except (ApiError, OSError) as exc:
        if job.tiktok_publish_id is None and job.attempts < MAX_UPLOAD_ATTEMPTS:
            job_event(db, job, JobStatus.READY, f"Upload attempt {job.attempts} failed — retrying")
            return _defer(job, timedelta(seconds=backoff_delay(job.attempts, base=60, cap=1800)), str(exc))
        mark_failed(db, job.id, str(exc))
        return "failed"

    now = utcnow()
    job.posted_at = now
    account.last_posted_at = now
    if mode == "inbox":
        job_event(db, job, JobStatus.POSTED, f"Sent to the TikTok inbox of @{account.username} — finish the post in the TikTok app")
    else:
        job_event(db, job, JobStatus.POSTED, f"Uploaded to @{account.username} ({privacy})")
    activity.record(
        db, "Publisher", f"Video #{video.id} {'sent to the inbox of' if mode == 'inbox' else 'published to'} @{account.username} · “{(job.rewritten_title or video.original_title)[:40]}”",
        event="published", job_id=job.id,
    )
    job.monitor_until = now + timedelta(hours=24)
    job.next_check_at = now + timedelta(minutes=2)
    job_event(db, job, JobStatus.MONITORING, "Monitoring for violations over the next 24 hours")
    return "posted"


# ---------------------------------------------------------------- 4. violation monitoring

def _violation(db: Session, job: Job, reason: str, raw: dict, token: str | None, removed_by_tiktok: bool) -> None:
    audit = workspace_settings.get(db, "audit")
    removal = "removed_by_tiktok" if removed_by_tiktok else "disabled"
    if audit.get("auto_remove") and not removed_by_tiktok:
        removal = "manual_required"
        if job.tiktok_post_id and token:
            try:
                tiktok.delete_video(token, job.tiktok_post_id)
                removal = "removed"
            except ApiError:
                removal = "manual_required"
    job.violation_reason = reason
    job.next_check_at = None
    job_event(db, job, JobStatus.VIOLATED, f"Violation detected: {reason}")
    db.add(Violation(job_id=job.id, tiktok_account_id=job.tiktok_account_id, reason=reason, raw=raw, removal_status=removal))
    handle = job.tiktok_account.username if job.tiktok_account else "?"
    activity.record(db, "Compliance", f"Video flagged on @{handle}: {reason}", level="error", event="violation", job_id=job.id, payload={"removal": removal})
    notify.send(db, "violation", f"Video flagged on @{handle}: {reason} (removal: {removal})", job_id=job.id)


def _advance_checkpoint(db: Session, job: Job) -> None:
    audit = workspace_settings.get(db, "audit")
    hours = sorted({float(h) for h in audit.get("check_hours", [1, 6, 12, 24])}) or [24.0]
    now = utcnow()
    posted = job.posted_at or now
    job.check_count += 1
    upcoming = [posted + timedelta(hours=h) for h in hours if posted + timedelta(hours=h) > now]
    if upcoming:
        job.next_check_at = upcoming[0]
    else:
        job.next_check_at = None
        job_event(db, job, JobStatus.CLEAN, f"Passed {hours[-1]:g}-hour compliance monitoring ({job.check_count} checks)")


def check_job(db: Session, job_id: int) -> str | None:
    job = db.get(Job, job_id)
    if not job or job.status != JobStatus.MONITORING or not job.tiktok_publish_id:
        return job.status if job else None
    account = job.tiktok_account
    if not account:
        return job.status
    token = tokens.tiktok_token(db, account)
    status = tiktok.fetch_status(token, job.tiktok_publish_id)
    state = status.get("status")

    if state == "FAILED":
        reason = status.get("fail_reason") or "unknown"
        if reason in tiktok.VIOLATION_REASONS or "violat" in reason or "spam" in reason or "moderat" in reason:
            _violation(db, job, f"TikTok rejected the post: {reason}", status, token, removed_by_tiktok=True)
        else:
            mark_failed(db, job.id, f"TikTok publish failed: {reason}")
        return job.status

    if state == "SEND_TO_USER_INBOX" and job.publish_mode == "inbox":
        if job.check_count == 0:
            job_event(db, job, JobStatus.MONITORING, "Delivered to the TikTok inbox — waiting for the post to be finished in the app")
        _advance_checkpoint(db, job)
        return job.status

    if state in PROCESSING_STATES:
        job.next_check_at = utcnow() + timedelta(minutes=5)
        return job.status

    post_ids = status.get("publicaly_available_post_id") or status.get("publicly_available_post_id") or []
    if post_ids and not job.tiktok_post_id:
        job.tiktok_post_id = str(post_ids[0])
        job_event(db, job, JobStatus.MONITORING, f"Published successfully · post {job.tiktok_post_id}")
    if job.tiktok_post_id:
        try:
            found = tiktok.query_videos(token, [job.tiktok_post_id])
        except AuthError as exc:
            if exc.code != "scope_not_authorized":
                raise
            found = None  # video.list scope not granted — can only rely on publish status
        if found is not None and not found:
            _violation(
                db, job, "Video is no longer available on TikTok (removed or restricted by moderation)",
                status, token, removed_by_tiktok=True,
            )
            return job.status
    _advance_checkpoint(db, job)
    return job.status


# ---------------------------------------------------------------- 5. manual actions

def retry_job(db: Session, job: Job) -> str:
    """Retry without ever posting the same video twice: an existing publish_id is resolved first."""
    if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
        raise ValueError(f"Only failed or cancelled jobs can be retried (job is {job.status})")
    job.error = None
    job.attempts = 0
    if job.tiktok_publish_id and job.tiktok_account:
        token = tokens.tiktok_token(db, job.tiktok_account)
        state = tiktok.fetch_status(token, job.tiktok_publish_id).get("status")
        if state == "PUBLISH_COMPLETE" or state in PROCESSING_STATES:
            job.posted_at = job.posted_at or utcnow()
            job.monitor_until = job.posted_at + timedelta(hours=24)
            job.next_check_at = utcnow()
            job_event(db, job, JobStatus.MONITORING, "Already on TikTok — resumed monitoring instead of re-posting")
            return job.status
        job.tiktok_publish_id = None
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


def cancel_job(db: Session, job: Job) -> None:
    if job.status not in JobStatus.PROCESSING | {JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.FAILED}:
        raise ValueError(f"Job cannot be cancelled while {job.status}")
    job.next_check_at = None
    job_event(db, job, JobStatus.CANCELLED, "Cancelled by user")


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
    """Called by Celery beat every few seconds. Schedules live in the DB, so UI edits apply without restarts."""
    policy = workspace_settings.get(db, "policy")
    now = utcnow()
    out: dict[str, list] = {"process": [], "rewrites": [], "uploads": [], "checks": []}

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

    if not policy["automations_paused"]:
        low = int(policy.get("random_delay_min_minutes", 0))
        high = max(low, int(policy.get("random_delay_max_minutes", 0)))
        for job in lease(JobStatus.READY, 50):
            if job.tiktok_account_id is None:
                job.next_check_at = now + timedelta(hours=1)
                continue
            delay = random.randint(low * 60, high * 60) if high else 0
            job.next_check_at = now + timedelta(seconds=delay) + LEASE
            out["uploads"].append((job.id, delay))

    for job in lease(JobStatus.MONITORING, 200):
        job.next_check_at = now + LEASE
        out["checks"].append(job.id)
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
        .where(or_(Job.posted_at.is_not(None), Job.status.in_([JobStatus.FAILED, JobStatus.CANCELLED])))
    ).unique().all()
    retention: dict[int | None, int] = {}
    for video, job in rows:
        if video.channel_id not in retention:
            retention[video.channel_id] = int(rules.effective(db, video.channel_id)["file_retention_days"])
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
