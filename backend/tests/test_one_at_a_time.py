"""A member's videos go through one at a time: the next is not downloaded until the one before is done."""

from datetime import timedelta

from app.models import Job, JobStatus, Video, utcnow
from app.services import pipeline
from tests.test_pipeline import _make_job  # noqa: E402


def _set(db, job: Job, status: str, **fields) -> None:
    job.status = status
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


def test_one_video_at_a_time_per_member(db, member_auth):
    first = _make_job(db, youtube_video_id="a1", rendered=False)
    second = _make_job(db, youtube_video_id="a2", rendered=False, caption="pending")
    theirs = _make_job(db, youtube_video_id="b1", rendered=False)
    member = db.get(Video, theirs.video_id)
    member.user_id = 2  # another member's video: their own line
    db.commit()

    assert pipeline.claim_lane(db, second) is False  # an older video of the same member goes first
    assert pipeline.claim_lane(db, first) is True and first.status == JobStatus.DOWNLOADING
    assert pipeline.claim_lane(db, theirs) is True  # the other member is not held up

    # While the first is downloading, edited, captioned or being handed to Buffer, the second waits.
    for busy in (JobStatus.DOWNLOADING, JobStatus.RENDERING, JobStatus.REWRITING, JobStatus.UPLOADING):
        _set(db, first, busy)
        assert pipeline.lane_free(db, second) is False and pipeline.claim_lane(db, second) is False, busy
    _set(db, first, JobStatus.READY, error=None)  # ready, about to go to Buffer: still holds the line
    assert pipeline.claim_lane(db, second) is False

    # Waiting means nothing runs for it: no download, no caption, and it is asked again shortly.
    assert pipeline.process_video(db, second.id) == JobStatus.FETCHED
    assert second.next_check_at - utcnow() < timedelta(seconds=30)
    assert pipeline.rewrite_job(db, second.id) == JobStatus.FETCHED and second.caption_status == "pending"

    # Ready but left waiting for a Buffer account does not hold the line; neither does the review queue.
    _set(db, first, JobStatus.READY, error="Waiting for a Buffer account")
    assert pipeline.lane_free(db, second) is True
    _set(db, first, JobStatus.AWAITING_APPROVAL, error=None)
    assert pipeline.claim_lane(db, second) is True and second.status == JobStatus.DOWNLOADING
