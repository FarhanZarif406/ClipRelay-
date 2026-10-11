import os
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from app.models import ActivityLog, CaptionStatus, Job, JobStatus, Video, VideoStatus, Violation, utcnow
from app.services import media, pipeline, rules
from app.services.storage import get_storage
from tests.helpers import ANTHROPIC, CREATOR, TT, UPLOAD_URL, claude, tt_err, tt_ok


def _make_job(db, tiktok_account, *, status=JobStatus.FETCHED, approval=False, youtube_video_id="v1", caption="done", rendered=True):
    key = f"videos/{youtube_video_id}.mp4"
    if rendered:
        path = os.path.join(get_storage().root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x00" * 4096)
    video = Video(
        youtube_video_id=youtube_video_id, original_title="Hidden beaches in Crete", original_caption="We found this hidden beach #crete",
        original_tags=["crete"], duration_sec=42, status=VideoStatus.ACCEPTED, rendered_file_path=key if rendered else None,
    )
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=tiktok_account.id, status=status, approval_required=approval, caption_status=caption,
              rewritten_title="Crete's secret", rewritten_caption="40 minutes off the trail.", rewritten_tags=["crete"])
    db.add(job)
    db.commit()
    return job


@respx.mock
def test_rewrite_uses_template(db, tiktok_account, template):
    job = _make_job(db, tiktok_account, status=JobStatus.REWRITING, caption="pending")
    rules.set_values(db, {"approval_required": False, "hashtag_count": 2})
    respx.post(ANTHROPIC).mock(side_effect=[claude("Crete’s best-kept secret"), claude("40 minutes off the trail, worth it."), claude("#crete #hiddengems #greece")])
    assert pipeline.rewrite_job(db, job.id) == JobStatus.READY
    assert job.rewritten_title == "Crete’s best-kept secret" and job.caption_status == CaptionStatus.DONE
    assert job.rewritten_tags == ["crete", "hiddengems"]  # trimmed to hashtag_count


@respx.mock
def test_approval_switch_decides_review_or_publish(db, tiktok_account, template):
    job = _make_job(db, tiktok_account, status=JobStatus.REWRITING, caption="pending")
    respx.post(ANTHROPIC).mock(return_value=claude("text"))
    assert pipeline.rewrite_job(db, job.id) == JobStatus.AWAITING_APPROVAL  # approval is on by default
    assert pipeline.upload_job(db, job.id) == "skipped"
    pipeline.approve_job(db, job)
    assert job.status == JobStatus.READY


@respx.mock
def test_caption_falls_back_when_the_model_fails(db, tiktok_account, template):
    job = _make_job(db, tiktok_account, status=JobStatus.FETCHED, caption="pending", rendered=False)
    respx.post(ANTHROPIC).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    assert pipeline.rewrite_job(db, job.id) == JobStatus.FETCHED  # the job is not failed; the render is still running
    assert respx.calls.call_count == 5  # 1 call + 4 retries with exponential backoff
    assert job.caption_status == CaptionStatus.FALLBACK
    assert job.rewritten_caption == "Hidden beaches in Crete" and job.rewritten_tags[:2] == ["fyp", "foryou"]
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "caption_fallback"))


def test_process_downloads_renders_and_waits_for_the_caption(db, tiktok_account, fake_media):
    job = _make_job(db, tiktok_account, status=JobStatus.FETCHED, caption="pending", rendered=False)
    rules.set_values(db, {"speed": 1.2, "horizontal_flip": False})
    assert pipeline.process_video(db, job.id) == JobStatus.REWRITING
    assert fake_media == [{"speed": 1.2, "flip": False, "keep_audio": True}]  # read from settings at job time
    video = job.video
    root = get_storage().root
    assert os.path.exists(os.path.join(root, video.source_file_path)) and os.path.exists(os.path.join(root, video.rendered_file_path))
    db.commit()
    db.refresh(job)
    assert [e.status for e in job.events] == [JobStatus.DOWNLOADING, JobStatus.RENDERING, JobStatus.REWRITING]


def test_process_goes_straight_to_review_when_the_caption_is_ready(db, tiktok_account, fake_media):
    job = _make_job(db, tiktok_account, status=JobStatus.FETCHED, rendered=False)
    assert pipeline.process_video(db, job.id) == JobStatus.AWAITING_APPROVAL
    rules.set_values(db, {"approval_required": False})
    other = _make_job(db, tiktok_account, status=JobStatus.FETCHED, rendered=False, youtube_video_id="v2")
    assert pipeline.process_video(db, other.id) == JobStatus.READY


def test_download_is_retried_three_times_then_fails(db, tiktok_account, fake_media):
    job = _make_job(db, tiktok_account, status=JobStatus.FETCHED, rendered=False)
    fake_media.append({"fail_download": 3})
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    assert job.attempts == 1 and job.next_check_at > utcnow() and "The video is private" in job.error
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    assert pipeline.process_video(db, job.id) == JobStatus.FAILED
    assert "Download failed after 3 attempts: The video is private" in job.error


def test_render_failure_resumes_from_the_render(db, tiktok_account, fake_media, monkeypatch):
    job = _make_job(db, tiktok_account, status=JobStatus.FETCHED, rendered=False)

    def broken(src, **_):
        raise media.RenderError("The downloaded file is damaged or incomplete")

    working = media.render
    monkeypatch.setattr(media, "render", broken)
    assert pipeline.process_video(db, job.id) == JobStatus.RENDERING
    source = job.video.source_file_path
    assert source and job.attempts == 1
    monkeypatch.setattr(media, "render", working)
    assert pipeline.process_video(db, job.id) == JobStatus.AWAITING_APPROVAL
    assert job.video.source_file_path == source  # not downloaded again


def test_reject_keeps_the_reason(db, tiktok_account):
    job = _make_job(db, tiktok_account, status=JobStatus.AWAITING_APPROVAL)
    pipeline.reject_job(db, job, "Wrong channel")
    assert job.status == JobStatus.CANCELLED and job.reject_reason == "Wrong channel"


@respx.mock
def test_inbox_mode_is_the_default(db, tiktok_account):
    job = _make_job(db, tiktok_account, status=JobStatus.READY)
    init = respx.post(f"{TT}/post/publish/inbox/video/init/").mock(return_value=tt_ok({"publish_id": "pub-9", "upload_url": UPLOAD_URL}))
    direct = respx.post(f"{TT}/post/publish/video/init/")
    respx.put(UPLOAD_URL).mock(return_value=httpx.Response(201))
    assert pipeline.upload_job(db, job.id) == "posted"
    assert init.call_count == 1 and direct.call_count == 0 and job.publish_mode == "inbox"
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "SEND_TO_USER_INBOX"}))
    assert pipeline.check_job(db, job.id) == JobStatus.MONITORING
    db.commit()
    db.refresh(job)
    assert job.check_count == 1 and any("Delivered to the TikTok inbox" in e.message for e in job.events)


def test_files_are_deleted_after_the_retention_period(db, tiktok_account):
    job = _make_job(db, tiktok_account, status=JobStatus.CLEAN)
    job.posted_at = utcnow() - timedelta(days=6)
    db.commit()
    path = os.path.join(get_storage().root, job.video.rendered_file_path)
    assert pipeline.cleanup_files(db) == 0 and os.path.exists(path)
    job.posted_at = utcnow() - timedelta(days=8)
    db.commit()
    assert pipeline.cleanup_files(db) == 1
    assert not os.path.exists(path) and job.video.rendered_file_path is None and job.video.files_deleted_at
    assert db.get(Video, job.video_id) is not None  # the row is kept forever


def _mock_tiktok_upload():
    respx.post(f"{TT}/post/publish/creator_info/query/").mock(return_value=tt_ok(CREATOR))
    init = respx.post(f"{TT}/post/publish/video/init/").mock(return_value=tt_ok({"publish_id": "pub-1", "upload_url": UPLOAD_URL}))
    put = respx.put(UPLOAD_URL).mock(return_value=httpx.Response(201))
    return init, put


@respx.mock
def test_upload_posts_once_and_starts_monitoring(db, tiktok_account):
    rules.set_values(db, {"publish_mode": "direct"})
    job = _make_job(db, tiktok_account, status=JobStatus.READY)
    init, put = _mock_tiktok_upload()
    assert pipeline.upload_job(db, job.id) == "posted"
    db.refresh(job)
    assert job.status == JobStatus.MONITORING and job.tiktok_publish_id == "pub-1"
    assert job.posted_at and job.monitor_until - job.posted_at == timedelta(hours=24)
    body = init.calls[0].request.content.decode()
    assert '"privacy_level":"PUBLIC_TO_EVERYONE"' in body.replace(" ", "") and "#crete" in body
    assert put.calls[0].request.headers["Content-Range"] == "bytes 0-4095/4096"

    # Never post the same video twice — even if the job is forced back to READY.
    job.status = JobStatus.READY
    db.commit()
    assert pipeline.upload_job(db, job.id) == "skipped"
    assert init.call_count == 1


@respx.mock
def test_daily_cap_defers(db, tiktok_account):
    tiktok_account.daily_cap = 1
    job = _make_job(db, tiktok_account, status=JobStatus.READY)
    earlier = Video(youtube_video_id="v0", status=VideoStatus.ACCEPTED)
    db.add(earlier)
    db.flush()
    db.add(Job(video_id=earlier.id, tiktok_account_id=tiktok_account.id, status=JobStatus.CLEAN, posted_at=utcnow()))
    db.commit()
    assert pipeline.upload_job(db, job.id) == "deferred"
    assert "Daily cap" in job.error and job.status == JobStatus.READY
    job.video.forced = True  # "Process anyway" publishes past the cap
    db.commit()
    respx.post(f"{TT}/post/publish/inbox/video/init/").mock(return_value=tt_err("rate_limit_exceeded", 429))
    pipeline.upload_job(db, job.id)
    assert "Daily cap" not in job.error  # it got past the cap, as far as TikTok


@respx.mock
def test_rate_limit_defers_without_failing(db, tiktok_account):
    rules.set_values(db, {"publish_mode": "direct"})
    job = _make_job(db, tiktok_account, status=JobStatus.READY)
    respx.post(f"{TT}/post/publish/creator_info/query/").mock(return_value=tt_ok(CREATOR))
    respx.post(f"{TT}/post/publish/video/init/").mock(return_value=tt_err("rate_limit_exceeded", 429))
    assert pipeline.upload_job(db, job.id) == "deferred"
    assert job.status == JobStatus.READY and job.tiktok_publish_id is None and job.next_check_at > utcnow()


def _monitoring_job(db, tiktok_account, posted_hours_ago=0.1):
    job = _make_job(db, tiktok_account, status=JobStatus.MONITORING)
    job.tiktok_publish_id = "pub-1"
    job.posted_at = utcnow() - timedelta(hours=posted_hours_ago)
    db.commit()
    return job


@respx.mock
def test_violation_when_video_disappears(db, tiktok_account):
    job = _monitoring_job(db, tiktok_account)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300]}))
    respx.post(f"{TT}/video/query/").mock(return_value=tt_ok({"videos": []}))
    assert pipeline.check_job(db, job.id) == JobStatus.VIOLATED
    violation = db.scalar(select(Violation))
    assert violation.removal_status == "removed_by_tiktok" and "no longer available" in violation.reason
    assert job.tiktok_post_id == "7300"


@respx.mock
def test_violation_on_moderation_failure(db, tiktok_account):
    job = _monitoring_job(db, tiktok_account)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "FAILED", "fail_reason": "spam_risk_text"}))
    assert pipeline.check_job(db, job.id) == JobStatus.VIOLATED
    assert "spam_risk_text" in job.violation_reason


@respx.mock
def test_checkpoints_then_clean(db, tiktok_account):
    job = _monitoring_job(db, tiktok_account, posted_hours_ago=2)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300]}))
    respx.post(f"{TT}/video/query/").mock(return_value=tt_ok({"videos": [{"id": "7300"}]}))
    assert pipeline.check_job(db, job.id) == JobStatus.MONITORING
    assert job.next_check_at == job.posted_at + timedelta(hours=6)

    job.posted_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert pipeline.check_job(db, job.id) == JobStatus.CLEAN


@respx.mock
def test_retry_never_reposts_published_video(db, tiktok_account):
    job = _make_job(db, tiktok_account, status=JobStatus.FAILED)
    job.tiktok_publish_id = "pub-1"
    db.commit()
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE"}))
    init = respx.post(f"{TT}/post/publish/video/init/")
    assert pipeline.retry_job(db, job) == JobStatus.MONITORING
    assert job.tiktok_publish_id == "pub-1" and init.call_count == 0


def test_scheduler_tick_leases_due_jobs(db, tiktok_account):
    job = _make_job(db, tiktok_account, caption="pending", rendered=False)
    due = pipeline.scheduler_tick(db)
    assert due == {"process": [job.id], "rewrites": [job.id], "uploads": [], "checks": []}  # side by side
    assert pipeline.scheduler_tick(db)["process"] == []  # leased, not handed out again straight away

    ready = _make_job(db, tiktok_account, status=JobStatus.READY, youtube_video_id="v2")
    job.status, job.next_check_at = JobStatus.CLEAN, None
    db.commit()
    assert [job_id for job_id, _delay in pipeline.scheduler_tick(db)["uploads"]] == [ready.id]


def test_jobs_wait_for_an_account_and_go_out_when_one_connects(db, tiktok_account):
    job = _make_job(db, tiktok_account, status=JobStatus.READY)
    job.tiktok_account_id = None
    tiktok_account.status = "revoked"
    db.commit()
    assert pipeline.upload_job(db, job.id) == "deferred"
    assert job.status == JobStatus.READY and job.error == pipeline.WAITING_FOR_ACCOUNT  # waits; it is not failed
    job.next_check_at = None
    assert pipeline.scheduler_tick(db)["uploads"] == []

    tiktok_account.status = "active"  # an account is connected
    job.next_check_at = None
    db.commit()
    assert pipeline.scheduler_tick(db)["uploads"] == [(job.id, 0)]
    assert job.tiktok_account_id == tiktok_account.id and job.error is None

