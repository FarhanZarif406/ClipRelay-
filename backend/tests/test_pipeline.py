import os
from datetime import timedelta

import httpx
import respx
from sqlalchemy import select

from tests.conftest import ME
from app.db import SessionLocal
from app.models import ActivityLog, CaptionStatus, Job, JobStatus, Video, VideoStatus, utcnow
from app.services import looks, media, pipeline, rules
from app.services.storage import get_storage
from tests.helpers import ANTHROPIC, claude


def _make_job(db, *, status=JobStatus.FETCHED, approval=False, youtube_video_id="v1", caption="done", rendered=True):
    key = f"videos/{youtube_video_id}.mp4"
    if rendered:
        path = os.path.join(get_storage().root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x00" * 4096)
    video = Video(
        user_id=1, youtube_video_id=youtube_video_id, original_title="Hidden beaches in Crete", original_caption="We found this hidden beach #crete",
        original_tags=["crete"], duration_sec=42, status=VideoStatus.ACCEPTED, rendered_file_path=key if rendered else None,
    )
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, status=status, approval_required=approval, caption_status=caption,
              rewritten_title="Crete's secret", rewritten_caption="40 minutes off the trail.", rewritten_tags=["crete"])
    db.add(job)
    db.commit()
    return job


@respx.mock
def test_rewrite_uses_template(db, template):
    job = _make_job(db, status=JobStatus.REWRITING, caption="pending")
    rules.set_values(db, {"approval_required": False, "hashtag_count": 2}, user=ME)
    respx.post(ANTHROPIC).mock(side_effect=[claude("Crete’s best-kept secret"), claude("40 minutes off the trail, worth it."), claude("#crete #hiddengems #greece")])
    assert pipeline.rewrite_job(db, job.id) == JobStatus.READY
    assert job.rewritten_title == "Crete’s best-kept secret" and job.caption_status == CaptionStatus.DONE
    assert job.rewritten_tags == ["crete", "hiddengems"]  # trimmed to hashtag_count


@respx.mock
def test_approval_switch_decides_review_or_publish(db, template):
    job = _make_job(db, status=JobStatus.REWRITING, caption="pending")
    respx.post(ANTHROPIC).mock(return_value=claude("text"))
    assert pipeline.rewrite_job(db, job.id) == JobStatus.AWAITING_APPROVAL  # approval is on by default
    assert pipeline.upload_job(db, job.id) == "skipped"
    pipeline.approve_job(db, job)
    assert job.status == JobStatus.READY


@respx.mock
def test_caption_falls_back_when_the_model_fails(db, template):
    job = _make_job(db, status=JobStatus.FETCHED, caption="pending", rendered=False)
    respx.post(ANTHROPIC).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    assert pipeline.rewrite_job(db, job.id) == JobStatus.FETCHED  # the job is not failed; the render is still running
    assert respx.calls.call_count == 5  # 1 call + 4 retries with exponential backoff
    assert job.caption_status == CaptionStatus.FALLBACK
    assert job.rewritten_caption == "Hidden beaches in Crete" and job.rewritten_tags[:2] == ["fyp", "foryou"]
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "caption_fallback"))


def test_process_downloads_renders_and_waits_for_the_caption(db, fake_media):
    job = _make_job(db, status=JobStatus.FETCHED, caption="pending", rendered=False)
    row = looks.default_row(db, 1, "shorts")
    looks.save(row, looks.validate({**row.look, "speed": {"speed": 1.2, "keep_pitch": True}, "frame": {**row.look["frame"], "flip": False}}))
    db.commit()
    assert pipeline.process_video(db, job.id) == JobStatus.REWRITING
    assert fake_media == [{"speed": 1.2, "flip": False, "keep_audio": True, "aspect": "9:16"}]  # read from the editing rules at job time
    video = job.video
    root = get_storage().root
    assert os.path.exists(os.path.join(root, video.source_file_path)) and os.path.exists(os.path.join(root, video.rendered_file_path))
    db.commit()
    db.refresh(job)
    assert [e.status for e in job.events] == [JobStatus.DOWNLOADING, JobStatus.RENDERING, JobStatus.REWRITING]


def test_process_goes_straight_to_review_when_the_caption_is_ready(db, fake_media):
    job = _make_job(db, status=JobStatus.FETCHED, rendered=False)
    assert pipeline.process_video(db, job.id) == JobStatus.AWAITING_APPROVAL
    rules.set_values(db, {"approval_required": False}, user=ME)
    other = _make_job(db, status=JobStatus.FETCHED, rendered=False, youtube_video_id="v2")
    assert pipeline.process_video(db, other.id) == JobStatus.READY


def test_download_is_retried_three_times_then_fails(db, fake_media):
    job = _make_job(db, status=JobStatus.FETCHED, rendered=False)
    fake_media.append({"fail_download": 3})
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    assert job.attempts == 1 and job.next_check_at > utcnow() and "The video is private" in job.error
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    assert pipeline.process_video(db, job.id) == JobStatus.FAILED
    assert "Download failed after 3 attempts: The video is private" in job.error


def test_render_failure_resumes_from_the_render(db, fake_media, monkeypatch):
    job = _make_job(db, status=JobStatus.FETCHED, rendered=False)

    def broken(src, look, **_):
        raise media.RenderError("The downloaded file is damaged or incomplete")

    working = media.render
    monkeypatch.setattr(media, "render", broken)
    assert pipeline.process_video(db, job.id) == JobStatus.RENDERING
    source = job.video.source_file_path
    assert source and job.attempts == 1
    monkeypatch.setattr(media, "render", working)
    assert pipeline.process_video(db, job.id) == JobStatus.AWAITING_APPROVAL
    assert job.video.source_file_path == source  # not downloaded again


def test_reject_keeps_the_reason(db):
    job = _make_job(db, status=JobStatus.AWAITING_APPROVAL)
    pipeline.reject_job(db, job, "Wrong channel")
    assert job.status == JobStatus.CANCELLED and job.reject_reason == "Wrong channel"


def test_files_are_deleted_after_the_retention_period(db):
    job = _make_job(db, status=JobStatus.CLEAN)
    job.posted_at = utcnow() - timedelta(days=6)
    db.commit()
    path = os.path.join(get_storage().root, job.video.rendered_file_path)
    assert pipeline.cleanup_files(db) == 0 and os.path.exists(path)
    job.posted_at = utcnow() - timedelta(days=8)
    db.commit()
    assert pipeline.cleanup_files(db) == 1
    assert not os.path.exists(path) and job.video.rendered_file_path is None and job.video.files_deleted_at
    assert db.get(Video, job.video_id) is not None  # the row is kept forever


def test_scheduler_tick_leases_due_jobs(db):
    job = _make_job(db, caption="pending", rendered=False)
    due = pipeline.scheduler_tick(db)
    assert due == {"process": [job.id], "rewrites": [job.id], "uploads": [], "buffer_checks": []}  # side by side
    assert pipeline.scheduler_tick(db)["process"] == []  # leased, not handed out again straight away

    ready = _make_job(db, status=JobStatus.READY, youtube_video_id="v2")
    job.status, job.next_check_at = JobStatus.CLEAN, None
    db.commit()
    assert [job_id for job_id, _delay in pipeline.scheduler_tick(db)["uploads"]] == [ready.id]


def test_stop_halts_a_running_download(db, monkeypatch):
    from app.services import sources

    job = _make_job(db, status=JobStatus.FETCHED, rendered=False)
    reached = {"end": False}

    class Adapter:
        name = "slow"

        def download(self, video, on_progress=None):
            on_progress(10)
            other = SessionLocal()  # the operator presses Stop while the download is running
            pipeline.cancel_job(other, other.get(Job, job.id))
            other.commit()
            other.close()
            monkeypatch.setattr(pipeline.time, "monotonic", lambda: 1e9)  # the next progress report is due
            on_progress(20)
            reached["end"] = True
            return "never"

    monkeypatch.setattr(sources, "get_adapter", lambda: Adapter())
    assert pipeline.process_video(db, job.id) == JobStatus.CANCELLED
    db.commit()
    db.refresh(job)
    assert reached["end"] is False  # the download was cut short, not left to finish
    assert job.status == JobStatus.CANCELLED and job.progress is None and job.attempts == 0 and job.video.source_file_path is None
    assert [e.message for e in job.events][-1] == "Download stopped by the operator"
    assert pipeline.scheduler_tick(db)["process"] == []  # and it is not picked up again


def test_stop_halts_a_running_render(db, fake_media, monkeypatch):
    job = _make_job(db, status=JobStatus.FETCHED, rendered=False)

    def render(src, look, *, on_progress=None, **_):
        other = SessionLocal()
        pipeline.cancel_job(other, other.get(Job, job.id))
        other.commit()
        other.close()
        on_progress(50)
        raise AssertionError("the render should have been stopped")

    monkeypatch.setattr(media, "render", render)
    assert pipeline.process_video(db, job.id) == JobStatus.CANCELLED
    db.commit()
    db.refresh(job)
    assert job.video.rendered_file_path is None and [e.message for e in job.events][-1] == "Editing stopped by the operator"
    # A stopped video can be started again from where it was.
    assert pipeline.retry_job(db, job) == JobStatus.FETCHED
