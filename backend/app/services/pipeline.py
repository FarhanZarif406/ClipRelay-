"""Processing pipeline.

Fetched → Rewriting → (Awaiting approval) → Ready → Uploading → Posted → Monitoring → Clean / Violated / Failed

Every function takes a SQLAlchemy session and returns plain values; the Celery task layer
(`app.workers.tasks`) decides what to enqueue next. This keeps the pipeline unit-testable.
"""

import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations import instagram, llm, tiktok, transcription
from app.integrations.http import ApiError, AuthError, RateLimitError, backoff_delay
from app.models import (
    InstagramSource,
    Job,
    JobStatus,
    TikTokStatus,
    Video,
    VideoStatus,
    Violation,
    utcnow,
)
from app.services import activity, media, notify, prompts, tokens, workspace_settings
from app.services.activity import job_event
from app.services.storage import get_storage

LEASE = timedelta(minutes=10)
MAX_UPLOAD_ATTEMPTS = 3
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


def posts_since(db: Session, account_id: int, since: datetime) -> int:
    return db.scalar(
        select(func.count(Job.id)).where(Job.tiktok_account_id == account_id, Job.posted_at >= since)
    ) or 0


def compose_post_text(job: Job) -> str:
    caption = (job.rewritten_caption or job.video.original_caption or "").strip()
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


# ---------------------------------------------------------------- 1. fetch

def run_source(db: Session, source_id: int, *, manual: bool = False) -> list[int]:
    """Fetch the latest videos for one source. Returns ids of newly created jobs (to be rewritten)."""
    source = db.get(InstagramSource, source_id)
    if not source:
        return []
    policy = workspace_settings.get(db, "policy")
    now = utcnow()
    source.next_run_at = now + timedelta(minutes=source.refresh_interval_minutes)
    if not manual and (not source.is_active or policy["automations_paused"]):
        return []

    try:
        token = tokens.instagram_token(db, source)
        items = instagram.list_media(token, source.ig_user_id, limit=int(policy.get("max_videos_per_run", 25)))
    except ApiError as exc:
        source.last_checked_at = now
        source.last_run_status = "error"
        source.last_error = str(exc)
        activity.record(db, "Instagram", f"Fetch failed for @{source.username}: {exc}", level="error", event="fetch_failed")
        raise

    videos = [item for item in items if item.is_video and item.media_url]
    known = set(
        db.scalars(
            select(Video.ig_media_id).where(Video.source_id == source.id, Video.ig_media_id.in_([v.id for v in videos]))
        )
    ) if videos else set()
    new_items = [v for v in videos if v.id not in known]

    job_ids: list[int] = []
    accepted = rejected = 0
    for item in reversed(new_items):  # oldest first
        video = process_media(db, source, item, policy)
        if video.status == VideoStatus.ACCEPTED:
            accepted += 1
            job_ids += [job.id for job in create_jobs(db, video, source, policy)]
        else:
            rejected += 1

    source.last_checked_at = utcnow()
    source.last_run_status = "ok"
    source.last_error = None
    source.videos_found += accepted
    activity.record(
        db,
        "Instagram",
        f"{len(new_items)} new videos found from @{source.username}" + (f" · {rejected} rejected" if rejected else ""),
        event="source_checked",
        payload={"source_id": source.id, "new": len(new_items), "accepted": accepted, "rejected": rejected, "skipped": len(videos) - len(new_items)},
    )
    return job_ids


def _reject(db: Session, video: Video, reason: str, path: str | None = None) -> Video:
    video.status = VideoStatus.REJECTED
    video.rejection_reason = reason
    if path and os.path.exists(path):
        os.remove(path)
    activity.record(
        db, "Filter", f"Video rejected from @{video.source.username if video.source else ''}: {reason}",
        level="warning", event="video_rejected", payload={"video_id": video.id, "ig_media_id": video.ig_media_id},
    )
    return video


def process_media(db: Session, source: InstagramSource, item: instagram.MediaItem, policy: dict) -> Video:
    """Download, probe (<60s), optional language gate, store. Rejections are logged with a reason."""
    video = Video(
        source_id=source.id,
        source=source,
        ig_media_id=item.id,
        permalink=item.permalink,
        media_url=item.media_url,
        thumbnail_url=item.thumbnail_url,
        posted_at=item.timestamp,
        original_title=item.title,
        original_caption=item.caption,
        original_tags=item.tags,
    )
    db.add(video)
    db.flush()

    limit = min(float(policy.get("max_duration_sec", 60)), get_settings().max_video_duration_sec)
    path = None
    try:
        path = media.download(item.media_url)
        probe = media.probe(path)
    except (ApiError, media.ProbeError) as exc:
        return _reject(db, video, f"Could not download/probe video: {exc}", path)

    video.duration_sec = round(probe.duration, 2)
    video.width, video.height = probe.width, probe.height
    video.size_bytes = os.path.getsize(path)
    if probe.duration >= limit:
        return _reject(db, video, f"Duration {probe.duration:.1f}s is not under {limit:.0f}s", path)

    if policy.get("language_gate_enabled"):
        allowed = [lang.lower() for lang in policy.get("allowed_languages", [])]
        try:
            language, confidence = detect_video_language(path, video)
        except (ApiError, media.ProbeError) as exc:
            return _reject(db, video, f"Language detection failed: {exc}", path)
        video.detected_language, video.language_confidence = language, confidence
        if allowed and language not in allowed:
            names = " or ".join(LANG_LABELS.get(code, code) for code in allowed)
            return _reject(db, video, f"Not {names}", path)

    video.storage_key = get_storage().save(path, f"videos/{source.username}/{item.id}.mp4")
    video.status = VideoStatus.ACCEPTED
    return video


LANG_LABELS = {"hi": "Hindi", "ur": "Urdu", "en": "English", "es": "Spanish", "pt": "Portuguese", "ja": "Japanese", "ar": "Arabic", "bn": "Bengali", "fr": "French", "de": "German"}


def detect_video_language(path: str, video: Video) -> tuple[str, float]:
    """Transcribe the audio when a transcription API is configured, otherwise classify the caption."""
    if transcription.enabled():
        audio = media.extract_audio(path)
        try:
            transcript, whisper_language = transcription.transcribe(audio)
        finally:
            os.remove(audio)
        video.transcript = transcript
        if not transcript.strip():
            return whisper_language or "und", 0.0
        if not get_settings().llm_api_key and whisper_language:
            return whisper_language, 0.9
        return llm.detect_language(transcript)
    text = f"{video.original_title}\n{video.original_caption}"
    if not text.strip():
        return "und", 0.0
    return llm.detect_language(text)


def create_jobs(db: Session, video: Video, source: InstagramSource, policy: dict) -> list[Job]:
    """One job per (video, TikTok account). UQ(video_id, tiktok_account_id) prevents double-posting."""
    accounts = [a for a in source.tiktok_accounts if a.status in (TikTokStatus.ACTIVE, TikTokStatus.EXPIRING)]
    if accounts and policy.get("unique_video_per_account", True):
        today = start_of_day()
        load = {
            account_id: count
            for account_id, count in db.execute(
                select(Job.tiktok_account_id, func.count(Job.id))
                .where(Job.tiktok_account_id.in_([a.id for a in accounts]), Job.created_at >= today)
                .group_by(Job.tiktok_account_id)
            )
        }
        accounts = [min(accounts, key=lambda a: (load.get(a.id, 0), a.id))]

    jobs = []
    for account in accounts or [None]:
        job = Job(
            video_id=video.id,
            tiktok_account_id=account.id if account else None,
            prompt_template_id=source.prompt_template_id,
            approval_required=source.approval_mode == "manual",
            status=JobStatus.FETCHED,
            next_check_at=utcnow() + LEASE,
        )
        db.add(job)
        db.flush()
        job_event(db, job, JobStatus.FETCHED, f"Fetched from @{source.username} · {video.duration_sec or 0:.0f}s")
        if account is None:
            job.error = f"No active TikTok account linked to @{source.username}"
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------- 2. rewrite

def rewrite_job(db: Session, job_id: int) -> str | None:
    job = db.get(Job, job_id)
    if not job or job.status not in (JobStatus.FETCHED, JobStatus.REWRITING):
        return job.status if job else None
    template = prompts.resolve_template(db, job.prompt_template_id)
    job_event(db, job, JobStatus.REWRITING, f"Rewriting with prompt “{template.name}”" if template else "Rewriting (no template — keeping original text)")
    video = job.video
    if template:
        result = prompts.rewrite(
            title_prompt=template.title_prompt,
            caption_prompt=template.caption_prompt,
            hashtags_prompt=template.hashtags_prompt,
            title=video.original_title,
            caption=video.original_caption,
            tags=video.original_tags or [],
            source=video.source.username if video.source else "",
            niche=template.niche,
        )
        job.prompt_template_id = template.id
        activity.record(db, "AI rewrite", f"Caption rewritten · prompt “{template.name}” applied", event="rewritten", job_id=job.id)
    else:
        result = {"title": video.original_title, "caption": video.original_caption, "tags": video.original_tags or []}
    job.rewritten_title, job.rewritten_caption, job.rewritten_tags = result["title"], result["caption"], result["tags"]
    job.next_check_at = None
    if job.approval_required:
        job_event(db, job, JobStatus.AWAITING_APPROVAL, "Waiting for manual approval")
    else:
        job_event(db, job, JobStatus.READY, "Ready to upload")
    return job.status


# ---------------------------------------------------------------- 3. upload

def _defer(job: Job, delta: timedelta, reason: str) -> str:
    job.next_check_at = utcnow() + delta
    job.error = reason
    return "deferred"


def upload_job(db: Session, job_id: int, *, ignore_window: bool = False) -> str:
    """Upload one READY job. Returns 'posted' | 'deferred' | 'skipped' | 'failed'."""
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
    if posts_since(db, account.id, start_of_day(now)) >= account.daily_cap:
        return _defer(job, timedelta(hours=1), f"Daily cap of {account.daily_cap} reached for @{account.username}")
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
    try:
        token = tokens.tiktok_token(db, account)
        creator = tiktok.creator_info(token)
        options = creator.get("privacy_level_options") or ["SELF_ONLY"]
        privacy = job.privacy_level if job.privacy_level in options else account.default_privacy
        if privacy not in options:
            privacy = options[0]
        max_duration = creator.get("max_video_post_duration_sec")
        if max_duration and video.duration_sec and video.duration_sec > max_duration:
            mark_failed(db, job.id, f"Video is longer than @{account.username}'s {max_duration}s limit")
            return "failed"
        with get_storage().local_copy(video.storage_key) as path:
            init = tiktok.init_direct_post(
                token, title=compose_post_text(job), privacy_level=privacy, video_size=os.path.getsize(path), creator=creator
            )
            job.tiktok_publish_id = init["publish_id"]
            job.privacy_level = privacy
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
    job_event(db, job, JobStatus.POSTED, f"Uploaded to @{account.username} ({privacy})")
    activity.record(
        db, "Publisher", f"Video published · “{(job.rewritten_title or video.original_title)[:40]}…” to @{account.username}",
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
    if not job.rewritten_caption and not job.rewritten_title:
        job_event(db, job, JobStatus.FETCHED, "Retry requested — rewriting again")
    else:
        job.next_check_at = None
        job_event(db, job, JobStatus.READY, "Retry requested")
    return job.status


def cancel_job(db: Session, job: Job) -> None:
    if job.status not in (JobStatus.FETCHED, JobStatus.REWRITING, JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.FAILED):
        raise ValueError(f"Job cannot be cancelled while {job.status}")
    job.next_check_at = None
    job_event(db, job, JobStatus.CANCELLED, "Cancelled by user")


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
    out: dict[str, list] = {"sources": [], "rewrites": [], "uploads": [], "checks": []}

    if not policy["automations_paused"] and within_window(policy, now):
        due = db.scalars(
            select(InstagramSource)
            .where(InstagramSource.is_active.is_(True))
            .where((InstagramSource.next_run_at.is_(None)) | (InstagramSource.next_run_at <= now))
            .limit(200)
        ).all()
        for source in due:
            source.next_run_at = now + timedelta(minutes=source.refresh_interval_minutes)
            out["sources"].append(source.id)

    def lease(status: str, limit: int) -> list[Job]:
        jobs = db.scalars(
            select(Job)
            .where(Job.status == status, (Job.next_check_at.is_(None)) | (Job.next_check_at <= now))
            .order_by(Job.id)
            .limit(limit)
        ).all()
        return list(jobs)

    for job in lease(JobStatus.FETCHED, 50):
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
