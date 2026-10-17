"""Only a few videos are edited at once on the whole server; the others wait, downloaded, while downloads carry on."""

from datetime import timedelta

from app.models import JobStatus, Video, utcnow
from app.services import media, pipeline
from tests.test_pipeline import _make_job  # noqa: E402


def _members_video(db, user_id: int, name: str, **kw):
    job = _make_job(db, youtube_video_id=name, rendered=False, **kw)
    db.get(Video, job.video_id).user_id = user_id
    db.commit()
    return job


def test_three_edits_at_a_time_and_the_fourth_waits_downloaded(db, fake_media, monkeypatch):
    monkeypatch.setattr(pipeline, "max_renders", lambda: 3)
    editing = [_members_video(db, n, f"busy{n}", status=JobStatus.RENDERING) for n in (2, 3, 4)]  # three other members are editing
    job = _make_job(db, rendered=False)

    # It is downloaded at once, then waits for a place: nothing is edited, the file is kept, and it is asked again shortly.
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    assert fake_media == [] and job.video.source_file_path and job.progress is None
    assert job.next_check_at - utcnow() < timedelta(seconds=30)
    db.expire(job, ["events"])
    assert "waiting for a free editing place" in job.events[-1].message
    events = len(job.events)
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    db.expire(job, ["events"])
    assert len(job.events) == events  # said once, not on every check

    # One of the three finishes: the waiting video takes its place without downloading again.
    editing[0].status = JobStatus.REWRITING
    db.commit()
    assert pipeline.process_video(db, job.id) == JobStatus.AWAITING_APPROVAL
    assert len(fake_media) == 1 and job.video.rendered_file_path and job.video.source_file_path is None


def test_a_video_that_is_editing_keeps_its_place(db, fake_media, monkeypatch):
    monkeypatch.setattr(pipeline, "max_renders", lambda: 1)
    job = _make_job(db, rendered=False, status=JobStatus.RENDERING)
    job.video.source_file_path = "source/x.mp4"
    assert pipeline.claim_render(db, job, "Rendering") is True  # a retry after a worker stopped: never locked out by itself
    other = _members_video(db, 2, "other")
    assert pipeline.claim_render(db, other, "Rendering") is False and other.status == JobStatus.FETCHED


def test_a_failed_edit_gives_its_place_up_while_it_waits(db, fake_media, monkeypatch):
    monkeypatch.setattr(pipeline, "max_renders", lambda: 1)
    job = _make_job(db, rendered=False)

    def broken(src, look, **_):
        raise media.RenderError("The downloaded file is damaged or incomplete")

    monkeypatch.setattr(media, "render", broken)
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING and job.attempts == 1
    assert pipeline.renders_running(db) == 0  # another member's video may be edited meanwhile


def test_edits_are_gentle_with_the_server(monkeypatch):
    from app.services import looks

    cmd, _ = media.render_command("in.mp4", "out.mp4", looks.complete({}, "shorts"), width=1920, height=1080, duration=30, has_audio=True)
    assert cmd[cmd.index("-threads") + 1] == "1" and cmd[cmd.index("-filter_complex_threads") + 1] == "1"
    monkeypatch.setattr(media, "_nice_exe", lambda: "/usr/bin/nice")
    assert media._gentle(["ffmpeg", "-i", "x"]) == ["/usr/bin/nice", "-n", "10", "ffmpeg", "-i", "x"]  # lower priority on Linux
