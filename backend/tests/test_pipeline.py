import os
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from app.integrations.http import ApiError
from app.models import ActivityLog, Job, JobStatus, Video, VideoStatus, Violation, utcnow
from app.services import pipeline, workspace_settings
from app.services.storage import get_storage
from tests.helpers import ANTHROPIC, CREATOR, GRAPH_MEDIA, TT, UPLOAD_URL, claude, ig_media, ig_video, tt_err, tt_ok


@respx.mock
def test_fetch_accepts_short_videos_and_rejects_long(db, source, template, fake_media):
    fake_media["https://cdn.instagram.test/long.mp4"] = 75.0
    respx.get(GRAPH_MEDIA).mock(
        return_value=ig_media(
            ig_video("short"),
            ig_video("long", url="https://cdn.instagram.test/long.mp4"),
            ig_video("photo", media_type="IMAGE"),
        )
    )
    job_ids = pipeline.run_source(db, source.id)
    db.commit()

    videos = {v.ig_media_id: v for v in db.scalars(select(Video))}
    assert set(videos) == {"short", "long"}  # images are ignored
    assert videos["short"].status == VideoStatus.ACCEPTED
    assert videos["short"].original_tags == ["crete", "travel"]
    assert videos["long"].status == VideoStatus.REJECTED
    assert "75.0s is not under 60s" in videos["long"].rejection_reason
    assert len(job_ids) == 1
    job = db.get(Job, job_ids[0])
    assert job.status == JobStatus.FETCHED and job.tiktok_account_id == source.tiktok_accounts[0].id
    assert os.path.exists(os.path.join(get_storage().root, videos["short"].storage_key))
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "video_rejected"))


@respx.mock
def test_exactly_60_seconds_is_rejected(db, source, fake_media):
    fake_media["https://cdn.instagram.test/edge.mp4"] = 60.0
    respx.get(GRAPH_MEDIA).mock(return_value=ig_media(ig_video("edge", url="https://cdn.instagram.test/edge.mp4")))
    assert pipeline.run_source(db, source.id) == []
    assert db.scalar(select(Video)).status == VideoStatus.REJECTED


@respx.mock
def test_second_run_skips_processed_videos(db, source, fake_media):
    route = respx.get(GRAPH_MEDIA).mock(return_value=ig_media(ig_video("a"), ig_video("b")))
    assert len(pipeline.run_source(db, source.id)) == 2
    db.commit()
    assert pipeline.run_source(db, source.id) == []
    assert route.call_count == 2
    assert len(db.scalars(select(Video)).all()) == 2


@respx.mock
def test_language_gate_rejects_other_languages(db, source, fake_media):
    workspace_settings.update(db, "policy", {"language_gate_enabled": True, "allowed_languages": ["hi", "ur"]})
    respx.get(GRAPH_MEDIA).mock(return_value=ig_media(ig_video("es", caption="Paseo por el mercado de Madrid")))
    respx.post(ANTHROPIC).mock(return_value=claude('{"language": "es", "confidence": 0.98}'))
    assert pipeline.run_source(db, source.id) == []
    video = db.scalar(select(Video))
    assert video.status == VideoStatus.REJECTED
    assert video.detected_language == "es" and video.rejection_reason == "Not Hindi or Urdu"


@respx.mock
def test_paused_source_does_not_fetch_unless_manual(db, source, fake_media):
    source.is_active = False
    db.commit()
    route = respx.get(GRAPH_MEDIA).mock(return_value=ig_media(ig_video("a")))
    assert pipeline.run_source(db, source.id) == []
    assert route.call_count == 0
    assert len(pipeline.run_source(db, source.id, manual=True)) == 1


@respx.mock
def test_unique_video_per_account_spreads_load(db, source, fake_media, tiktok_account):
    from app.models import TikTokAccount
    from app.security import encrypt

    second = TikTokAccount(open_id="open-2", username="wildcuts", access_token_enc=encrypt("x"), refresh_token_enc=encrypt("y"))
    db.add(second)
    source.tiktok_accounts.append(second)
    db.commit()
    respx.get(GRAPH_MEDIA).mock(return_value=ig_media(ig_video("1"), ig_video("2")))
    ids = pipeline.run_source(db, source.id)
    accounts = sorted(db.get(Job, i).tiktok_account_id for i in ids)
    assert accounts == sorted([tiktok_account.id, second.id])  # each account got a different video


def _make_job(db, source, *, status=JobStatus.FETCHED, approval=False):
    path = os.path.join(get_storage().root, "videos", "slowtravel", "v1.mp4")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00" * 4096)
    video = Video(
        source_id=source.id, ig_media_id="v1", original_title="Hidden beaches in Crete", original_caption="We found this hidden beach #crete",
        original_tags=["crete"], duration_sec=42, status=VideoStatus.ACCEPTED, storage_key="videos/slowtravel/v1.mp4",
    )
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=source.tiktok_accounts[0].id, status=status, approval_required=approval,
              rewritten_title="Crete's secret", rewritten_caption="40 minutes off the trail.", rewritten_tags=["crete"])
    db.add(job)
    db.commit()
    return job


@respx.mock
def test_rewrite_uses_template(db, source, template):
    job = _make_job(db, source)
    respx.post(ANTHROPIC).mock(side_effect=[claude("Crete’s best-kept secret"), claude("40 minutes off the trail, worth it."), claude("#crete #hiddengems #greece")])
    assert pipeline.rewrite_job(db, job.id) == JobStatus.READY
    assert job.rewritten_title == "Crete’s best-kept secret"
    assert job.rewritten_tags == ["crete", "hiddengems", "greece"]
    assert [e.status for e in job.events] == [JobStatus.REWRITING, JobStatus.READY]


@respx.mock
def test_manual_approval_waits(db, source, template):
    job = _make_job(db, source, approval=True)
    respx.post(ANTHROPIC).mock(return_value=claude("text"))
    assert pipeline.rewrite_job(db, job.id) == JobStatus.AWAITING_APPROVAL
    assert pipeline.upload_job(db, job.id) == "skipped"
    pipeline.approve_job(db, job)
    assert job.status == JobStatus.READY


@respx.mock
def test_llm_failure_raises_for_retry(db, source, template):
    job = _make_job(db, source)
    respx.post(ANTHROPIC).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    with pytest.raises(ApiError):
        pipeline.rewrite_job(db, job.id)
    assert respx.calls.call_count == 5  # 1 call + 4 retries with exponential backoff


def _mock_tiktok_upload():
    respx.post(f"{TT}/post/publish/creator_info/query/").mock(return_value=tt_ok(CREATOR))
    init = respx.post(f"{TT}/post/publish/video/init/").mock(return_value=tt_ok({"publish_id": "pub-1", "upload_url": UPLOAD_URL}))
    put = respx.put(UPLOAD_URL).mock(return_value=httpx.Response(201))
    return init, put


@respx.mock
def test_upload_posts_once_and_starts_monitoring(db, source):
    job = _make_job(db, source, status=JobStatus.READY)
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
def test_daily_cap_defers(db, source, tiktok_account):
    tiktok_account.daily_cap = 1
    job = _make_job(db, source, status=JobStatus.READY)
    earlier = Video(source_id=source.id, ig_media_id="v0", status=VideoStatus.ACCEPTED)
    db.add(earlier)
    db.flush()
    db.add(Job(video_id=earlier.id, tiktok_account_id=tiktok_account.id, status=JobStatus.CLEAN, posted_at=utcnow()))
    db.commit()
    assert pipeline.upload_job(db, job.id) == "deferred"
    assert "Daily cap" in job.error and job.status == JobStatus.READY


@respx.mock
def test_rate_limit_defers_without_failing(db, source):
    job = _make_job(db, source, status=JobStatus.READY)
    respx.post(f"{TT}/post/publish/creator_info/query/").mock(return_value=tt_ok(CREATOR))
    respx.post(f"{TT}/post/publish/video/init/").mock(return_value=tt_err("rate_limit_exceeded", 429))
    assert pipeline.upload_job(db, job.id) == "deferred"
    assert job.status == JobStatus.READY and job.tiktok_publish_id is None and job.next_check_at > utcnow()


def _monitoring_job(db, source, posted_hours_ago=0.1):
    job = _make_job(db, source, status=JobStatus.MONITORING)
    job.tiktok_publish_id = "pub-1"
    job.posted_at = utcnow() - timedelta(hours=posted_hours_ago)
    db.commit()
    return job


@respx.mock
def test_violation_when_video_disappears(db, source):
    job = _monitoring_job(db, source)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300]}))
    respx.post(f"{TT}/video/query/").mock(return_value=tt_ok({"videos": []}))
    assert pipeline.check_job(db, job.id) == JobStatus.VIOLATED
    violation = db.scalar(select(Violation))
    assert violation.removal_status == "removed_by_tiktok" and "no longer available" in violation.reason
    assert job.tiktok_post_id == "7300"


@respx.mock
def test_violation_on_moderation_failure(db, source):
    job = _monitoring_job(db, source)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "FAILED", "fail_reason": "spam_risk_text"}))
    assert pipeline.check_job(db, job.id) == JobStatus.VIOLATED
    assert "spam_risk_text" in job.violation_reason


@respx.mock
def test_checkpoints_then_clean(db, source):
    job = _monitoring_job(db, source, posted_hours_ago=2)
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7300]}))
    respx.post(f"{TT}/video/query/").mock(return_value=tt_ok({"videos": [{"id": "7300"}]}))
    assert pipeline.check_job(db, job.id) == JobStatus.MONITORING
    assert job.next_check_at == job.posted_at + timedelta(hours=6)

    job.posted_at = utcnow() - timedelta(hours=25)
    db.commit()
    assert pipeline.check_job(db, job.id) == JobStatus.CLEAN


@respx.mock
def test_retry_never_reposts_published_video(db, source):
    job = _make_job(db, source, status=JobStatus.FAILED)
    job.tiktok_publish_id = "pub-1"
    db.commit()
    respx.post(f"{TT}/post/publish/status/fetch/").mock(return_value=tt_ok({"status": "PUBLISH_COMPLETE"}))
    init = respx.post(f"{TT}/post/publish/video/init/")
    assert pipeline.retry_job(db, job) == JobStatus.MONITORING
    assert job.tiktok_publish_id == "pub-1" and init.call_count == 0


def test_scheduler_tick_uses_db_intervals(db, source):
    source.next_run_at = utcnow() - timedelta(seconds=1)
    db.commit()
    due = pipeline.scheduler_tick(db)
    assert due["sources"] == [source.id]
    assert source.next_run_at > utcnow() + timedelta(minutes=29)
    assert pipeline.scheduler_tick(db)["sources"] == []  # not due again until the interval passes

    workspace_settings.update(db, "policy", {"automations_paused": True})
    source.next_run_at = utcnow() - timedelta(seconds=1)
    assert pipeline.scheduler_tick(db)["sources"] == []


def test_active_window():
    policy = {"timezone": "UTC", "active_days": [0, 1, 2, 3, 4, 5, 6], "active_window_start": "09:00", "active_window_end": "22:00"}
    base = utcnow().replace(hour=12, minute=0)
    assert pipeline.within_window(policy, base)
    assert not pipeline.within_window(policy, base.replace(hour=23))
    overnight = {**policy, "active_window_start": "22:00", "active_window_end": "06:00"}
    assert pipeline.within_window(overnight, base.replace(hour=23))
