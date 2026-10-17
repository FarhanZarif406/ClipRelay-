from app.db import SessionLocal
from app.models import Job, JobStatus
from app.services import dispatch, media, pipeline, sources
from tests.test_pipeline import _make_job


def test_pause_and_resume_from_the_api(client, auth, db):
    job = _make_job(db, status=JobStatus.READY)
    paused = client.post(f"/api/jobs/{job.id}/pause", headers=auth).json()
    assert paused["status"] == "paused" and paused["events"][-1]["message"] == "Paused by the operator while waiting to upload"
    assert client.post(f"/api/jobs/{job.id}/pause", headers=auth).status_code == 409  # already paused
    assert pipeline.scheduler_tick(db)["uploads"] == []  # nothing goes out while it is paused
    db.commit()
    stages = {s["key"]: s for s in client.get("/api/pipeline/status", headers=auth).json()["stages"]}
    assert stages["paused"]["total"] == 1 and stages["paused"]["items"][0]["paused_while"] == "ready"
    assert client.get("/api/jobs?status=waiting", headers=auth).json()["total"] == 1

    resumed = client.post(f"/api/jobs/{job.id}/resume", headers=auth).json()
    assert resumed["status"] == "ready" and "carries on uploading" in resumed["events"][-1]["message"]
    assert dispatch.sent[-1] == ("upload_job", (job.id,))
    assert client.post(f"/api/jobs/{job.id}/resume", headers=auth).status_code == 409  # not paused any more

    # A paused video can still be stopped; it then goes to Cancelled.
    client.post(f"/api/jobs/{job.id}/pause", headers=auth)
    assert client.post(f"/api/jobs/{job.id}/cancel", headers=auth).json()["status"] == "cancelled"
    # Only work in progress can be paused.
    assert client.post(f"/api/jobs/{job.id}/pause", headers=auth).status_code == 409


def test_pausing_a_running_download_and_resuming_it(db, fake_media, monkeypatch):
    job = _make_job(db, status=JobStatus.FETCHED, caption="pending", rendered=False)
    adapter = sources.get_adapter()

    def slow_download(video, on_progress=None, short_side=1080):
        other = SessionLocal()
        pipeline.pause_job(other, other.get(Job, job.id))
        other.commit()
        other.close()
        on_progress(40)  # the next progress report notices the pause and stops the download
        raise AssertionError("the download should have been stopped")

    monkeypatch.setattr(adapter, "download", slow_download)
    monkeypatch.setattr(sources, "get_adapter", lambda: adapter)
    assert pipeline.process_video(db, job.id) == JobStatus.PAUSED
    db.commit()
    db.refresh(job)
    assert job.paused_status == JobStatus.DOWNLOADING and job.video.source_file_path is None and fake_media == []

    # Resume: nothing was downloaded yet, so the download starts again, then the edit follows.
    monkeypatch.undo()
    monkeypatch.setattr(media, "probe", lambda path: media.ProbeResult(30.0, 1080, 1920, True))
    assert pipeline.resume_job(db, job) == JobStatus.FETCHED and job.paused_status is None
    db.commit()
    assert pipeline.scheduler_tick(db)["process"] == [job.id]


def test_resume_keeps_what_was_finished(db):
    job = _make_job(db, status=JobStatus.RENDERING, caption="done", rendered=False)
    job.video.source_file_path = "source/x.mp4"  # downloaded already, paused while editing
    pipeline.pause_job(db, job)
    assert pipeline.resume_job(db, job) == JobStatus.DOWNLOADING  # only the edit is done again, once an editing place is free

    edited = _make_job(db, status=JobStatus.REWRITING, caption="pending", youtube_video_id="v2")
    pipeline.pause_job(db, edited)
    assert pipeline.resume_job(db, edited) == JobStatus.REWRITING  # edited already: only the caption is left

    review = _make_job(db, status=JobStatus.REWRITING, caption="done", approval=True, youtube_video_id="v3")
    pipeline.pause_job(db, review)
    assert pipeline.resume_job(db, review) == JobStatus.AWAITING_APPROVAL  # approval is still asked for
