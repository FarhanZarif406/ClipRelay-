"""The admin's main switch: off stops everything for every member; on carries on where it stopped."""

from sqlalchemy import func, select

from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import Channel, Job, JobStatus, Video, utcnow
from app.services import detection, pipeline
from tests.test_pipeline import _make_job  # noqa: E402


def test_the_main_switch(client, auth, member_auth, db, channel, monkeypatch):
    running = _make_job(db, status=JobStatus.READY, youtube_video_id="run1")
    held = _make_job(db, status=JobStatus.READY, youtube_video_id="held1")
    pipeline.pause_job(db, held)  # paused by hand before: the switch leaves it alone
    db.commit()
    assert client.get("/api/system", headers=member_auth).json()["on"] is True

    # Only the admin may switch it.
    assert client.put("/api/system", headers=member_auth, json={"on": False}).status_code == 403
    off = client.put("/api/system", headers=auth, json={"on": False}).json()
    assert off["on"] is False and off["changed_by"]
    db.expire_all()
    assert db.get(Job, running.id).status == JobStatus.PAUSED and "switched the system off" in db.get(Job, running.id).events[-1].message

    # Members see that it is off, not who did it.
    seen = client.get("/api/system", headers=member_auth).json()
    assert seen["on"] is False and seen["changed_by"] is None
    assert client.get("/api/dashboard/nav", headers=member_auth).json()["system_on"] is False

    # Nothing moves: no channel is checked, no upload is even recorded, the tick hands out no work.
    assert detection.due_channels(db) == []
    monkeypatch.setattr(youtube, "video_details", lambda vid: VideoMeta(vid, title="New", duration_seconds=30, published_at=utcnow()))
    assert detection.discover(db, channel, "whileoff") is None
    assert db.scalar(select(func.count(Video.id)).where(Video.youtube_video_id == "whileoff")) == 0
    assert pipeline.scheduler_tick(db) == {"process": [], "rewrites": [], "uploads": [], "buffer_checks": []}

    # On again: the switched-off video carries on; the one paused by hand stays paused; channels are watched from now.
    before = utcnow()
    assert client.put("/api/system", headers=auth, json={"on": True}).json()["on"] is True
    db.expire_all()
    assert db.get(Job, running.id).status != JobStatus.PAUSED
    assert db.get(Job, held.id).status == JobStatus.PAUSED
    assert db.get(Channel, channel.id).monitoring_since >= before.replace(microsecond=0)
