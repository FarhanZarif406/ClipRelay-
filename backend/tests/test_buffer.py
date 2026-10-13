import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from sqlalchemy import select

from app.integrations import buffer as buffer_api
from app.models import BufferChannel, BufferLog, JobStatus, Mode, utcnow
from app.services import buffer, pipeline, push, slots
from tests.test_pipeline import _make_job  # noqa: E402

KEY = "buf_test_key_0123456789abcdefghij"
UTC = timezone.utc


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class FakeBuffer:
    """Stands in for Buffer's GraphQL API: answers by the name of the operation."""

    def __init__(self):
        self.channels = [{"id": "ch-tiktok", "name": "simran", "displayName": "simran_sing0", "service": "tiktok", "avatar": None},
                         {"id": "ch-insta", "name": "insta", "displayName": None, "service": "instagram", "avatar": None}]
        self.posts: list[str] = []
        self.post_state = {"status": "scheduled"}
        self.refuse: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers["authorization"] != f"Bearer {KEY}":
            return httpx.Response(401, json={"errors": [{"message": "unauthorized"}]})
        query = json.loads(request.content)["query"]
        if query.startswith("query Organizations"):
            return httpx.Response(200, json={"data": {"account": {"organizations": [{"id": "org-1", "name": "Mine"}]}}})
        if query.startswith("query Channels"):
            return httpx.Response(200, json={"data": {"channels": self.channels}})
        if query.startswith("mutation CreatePost"):
            self.posts.append(query)
            if self.refuse:
                return httpx.Response(200, json={"data": {"createPost": {"message": self.refuse}}})
            due = query.split('dueAt: "')[1].split('"')[0]
            return httpx.Response(200, json={"data": {"createPost": {"post": {"id": f"post-{len(self.posts)}", "status": "scheduled", "dueAt": due}}}})
        if query.startswith("query Post"):
            return httpx.Response(200, json={"data": {"post": {"id": "post-1", **self.post_state}}})
        return httpx.Response(400, json={"errors": [{"message": "unknown operation"}]})


@pytest.fixture
def fake():
    with respx.mock(assert_all_called=False) as mock:
        handler = FakeBuffer()
        mock.post(buffer_api.API).mock(side_effect=handler)
        yield handler


def test_next_slot():
    now = at("2026-10-14T05:00:00")  # 10:00 in Karachi
    zone = "Asia/Karachi"
    assert slots.next_slot(["09:00", "18:00"], 7, None, [], now, zone) == at("2026-10-14T13:00:00")  # today 18:00
    assert slots.next_slot(["09:00", "18:00"], 7, None, [at("2026-10-14T13:00:00")], now, zone) == at("2026-10-15T04:00:00")  # taken → tomorrow 09:00
    assert slots.next_slot(["09:00", "18:00"], 1, None, [at("2026-10-14T04:00:00")], now, zone) == at("2026-10-15T04:00:00")  # today is full
    assert slots.next_slot(["18:00"], 7, None, [], at("2026-10-14T12:55:00"), zone) == at("2026-10-15T13:00:00")  # too close to now
    assert slots.next_slot(["09:00"], 7, "2026-10-20", [], now, zone) == at("2026-10-20T04:00:00")  # not before the start date
    assert slots.next_slot([], 7, None, [], now, zone) is None and slots.next_slot(["09:00"], 0, None, [], now, zone) is None
    assert slots.clean_times(["18:00", "09:00", "9:00", "25:00", "09:00", 5]) == ["09:00", "18:00"]
    assert slots.is_day("2026-02-28") and not slots.is_day("2026-02-30") and not slots.is_day("20-10-2026")


def test_buffer_key_and_accounts(client, auth, member_auth, db, fake):
    assert client.get("/api/buffer", headers=auth).json()["connected"] is False
    assert client.put("/api/buffer/key", headers=auth, json={"api_key": "has spaces in it, not a key"}).status_code == 400
    r = client.put("/api/buffer/key", headers=auth, json={"api_key": "wrong_key_0123456789abcdefghij"})
    assert r.status_code == 400 and "refused the API key" in r.json()["detail"]
    assert client.get("/api/buffer", headers=auth).json()["connected"] is False  # a refused key is not kept

    saved = client.put("/api/buffer/key", headers=auth, json={"api_key": KEY})
    status = saved.json()
    assert saved.status_code == 200 and KEY not in saved.text and status["last4"] == KEY[-4:]
    names = {c["name"]: c for c in status["channels"]}
    assert set(names) == {"simran_sing0", "insta"}
    assert names["simran_sing0"]["enabled"] is True and names["insta"]["enabled"] is False  # only TikTok is on from the start
    assert names["simran_sing0"]["times"] == ["09:00", "13:00", "18:00"] and names["simran_sing0"]["daily_limit"] == 3 and names["simran_sing0"]["next_slot"]
    # Each workspace has its own rows, and another member sees none of it.
    assert len(client.get("/api/buffer?mode=podcasts", headers=auth).json()["channels"]) == 2
    assert client.get("/api/buffer", headers=member_auth).json() | {"time_zone": ""} == {"connected": False, "last4": "", "saved_at": None, "synced_at": None, "error": None, "public_url": False, "time_zone": "", "channels": []}
    channel_id = names["simran_sing0"]["id"]
    assert client.patch(f"/api/buffer/channels/{channel_id}", headers=member_auth, json={"enabled": False}).status_code == 404

    # The schedule: timezone, start date, times and daily limit.
    for bad in ({"daily_limit": 0}, {"times": ["9am"]}, {"time_zone": "Mars/Olympus"}, {"start_date": "tomorrow"}):
        assert client.patch(f"/api/buffer/channels/{channel_id}", headers=auth, json=bad).status_code == 422, bad
    changed = client.patch(f"/api/buffer/channels/{channel_id}", headers=auth, json={"daily_limit": 7, "times": ["18:00", "09:00"], "time_zone": "Asia/Karachi", "start_date": "2030-01-05"}).json()
    row = next(c for c in changed["channels"] if c["id"] == channel_id)
    assert (row["daily_limit"], row["times"], row["time_zone"], row["start_date"]) == (7, ["09:00", "18:00"], "Asia/Karachi", "2030-01-05")
    assert row["next_slot"].startswith("2030-01-05T04:00")
    assert client.patch(f"/api/buffer/channels/{channel_id}", headers=auth, json={"start_date": None}).json()["channels"][0]["start_date"] is None

    # An account disconnected in Buffer is dropped; the key can be removed.
    fake.channels = fake.channels[:1]
    assert [c["name"] for c in client.post("/api/buffer/refresh", headers=auth).json()["channels"]] == ["simran_sing0"]
    assert client.delete("/api/buffer/key", headers=auth).json() | {"time_zone": "", "public_url": False} == {"connected": False, "last4": "", "saved_at": None, "synced_at": None, "error": None, "public_url": False, "time_zone": "", "channels": []}
    assert db.scalar(select(BufferChannel)) is None


def _connect(client, auth, db, monkeypatch):
    client.put("/api/buffer/key", headers=auth, json={"api_key": KEY})
    monkeypatch.setattr(push, "base_url", lambda: "https://clips.example.com")
    return db.scalar(select(BufferChannel).where(BufferChannel.buffer_id == "ch-tiktok", BufferChannel.mode == Mode.SHORTS))


def test_a_clip_goes_out_through_buffer(client, auth, db, fake, monkeypatch):
    job = _make_job(db, status=JobStatus.READY)
    # With no Buffer key the clip waits, and says why; nothing is lost.
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_KEY and job.status == JobStatus.READY
    db.commit()
    assert client.get(f"/api/jobs/{job.id}", headers=auth).json()["waiting_for_account"] is True
    job.next_check_at = None
    db.commit()
    channel = _connect(client, auth, db, monkeypatch)

    assert pipeline.upload_job(db, job.id) == "scheduled"
    db.refresh(job)
    assert job.status == JobStatus.SCHEDULED and job.buffer_post_id == "post-1" and job.buffer_channel_id == channel.id
    sent = fake.posts[0]
    assert 'channelId: "ch-tiktok"' in sent and "Crete's secret" in sent and "#crete" in sent
    assert f"https://clips.example.com/api/public/clip/{job.share_token}/clip.mp4" in sent
    assert job.buffer_due_at == buffer.next_slot(db, channel, utcnow() - timedelta(days=1)) or job.buffer_due_at > utcnow()
    assert pipeline.upload_job(db, job.id) == "skipped" and len(fake.posts) == 1  # never handed over twice

    # Buffer fetches the clip from the private link; nothing else opens it.
    clip = client.get(f"/api/public/clip/{job.share_token}/clip.mp4")
    assert clip.status_code == 200 and clip.headers["content-type"] == "video/mp4" and len(clip.content) == 4096
    assert client.head(f"/api/public/clip/{job.share_token}/clip.mp4").status_code == 200
    assert client.get(f"/api/public/clip/{'0' * 48}/clip.mp4").status_code == 404

    # The next clip takes the next time; the account shows what is waiting.
    second = _make_job(db, status=JobStatus.READY, youtube_video_id="v2")
    assert pipeline.upload_job(db, second.id) == "scheduled"
    db.commit()
    db.refresh(second)
    assert second.buffer_due_at > job.buffer_due_at
    view = client.get("/api/buffer", headers=auth).json()["channels"]
    row = next(c for c in view if c["id"] == channel.id)
    assert row["waiting"] == 2 and row["uploaded"] == 0
    listed = client.get("/api/jobs?status=waiting", headers=auth).json()["items"]
    assert {j["status"] for j in listed} == {"scheduled"} and listed[0]["buffer_channel"]["name"] == "simran_sing0" and listed[0]["waiting_for_account"] is False
    stages = {s["key"]: s for s in client.get("/api/pipeline/status", headers=auth).json()["stages"]}
    assert stages["scheduled"]["total"] == 2 and stages["scheduled"]["items"][0]["buffer_channel"]["name"] == "simran_sing0"

    # Before its time nothing is asked; after it, Buffer's answer is recorded.
    assert pipeline.scheduler_tick(db)["buffer_checks"] == []
    db.commit()
    job.next_check_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert pipeline.scheduler_tick(db)["buffer_checks"] == [job.id]
    db.commit()
    assert buffer.check(db, job.id) == JobStatus.SCHEDULED and job.next_check_at > utcnow()  # not sent yet: asked again later
    fake.post_state = {"status": "sent", "sentAt": "2026-10-14T13:00:05.000Z", "externalLink": "https://www.tiktok.com/@simran_sing0/video/1"}
    assert buffer.check(db, job.id) == JobStatus.POSTED
    assert job.posted_at == at("2026-10-14T13:00:05") and job.buffer_link.endswith("/video/1")
    db.commit()
    assert client.get(f"/api/public/clip/{job.share_token}/clip.mp4").status_code == 404  # published: the link is closed
    live = client.get(f"/api/buffer/channels/{channel.id}/status", headers=auth).json()
    assert live["uploaded"]["lifetime"] == 1 and live["waiting"] == 1 and sorted(c["state"] for c in live["recent"]) == ["published", "scheduled"]
    assert client.get(f"/api/jobs/{job.id}", headers=auth).json()["post_url"] == "https://www.tiktok.com/@simran_sing0/video/1"

    # Buffer could not publish the other one.
    fake.post_state = {"status": "error", "error": {"message": "TikTok rejected the video"}}
    assert buffer.check(db, second.id) == JobStatus.FAILED and "TikTok rejected the video" in second.error
    assert db.scalar(select(BufferLog).where(BufferLog.job_id == second.id)).state == "failed"
    # Retrying hands it over afresh.
    pipeline.retry_job(db, second)
    assert second.status == JobStatus.READY and second.buffer_post_id is None
    assert pipeline.upload_job(db, second.id) == "scheduled" and len(fake.posts) == 3


def test_a_clip_waits_when_buffer_cannot_take_it(client, auth, db, fake, monkeypatch):
    job = _make_job(db, status=JobStatus.READY)
    client.put("/api/buffer/key", headers=auth, json={"api_key": KEY})
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_PUBLIC_URL and job.status == JobStatus.READY  # http://api.test is not public
    channel = _connect(client, auth, db, monkeypatch)

    def change(**values):  # the page saves through its own connection; this one then reads the account afresh
        response = client.patch(f"/api/buffer/channels/{channel.id}", headers=auth, json=values)
        db.expire_all()
        return response

    change(times=[])
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_TIMES
    change(times=["09:00"], enabled=False)
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_ACCOUNT
    assert client.patch(f"/api/jobs/{job.id}", headers=auth, json={"buffer_channel_id": channel.id}).status_code == 400  # switched off
    change(enabled=True)
    assert client.patch(f"/api/jobs/{job.id}", headers=auth, json={"buffer_channel_id": channel.id}).json()["buffer_channel"]["id"] == channel.id
    assert client.patch(f"/api/jobs/{job.id}", headers=auth, json={"buffer_channel_id": 9999}).status_code == 404
    db.expire_all()

    # Buffer refuses the post: tried three times, then failed with Buffer's reason.
    fake.refuse = "Video is too long"
    for attempt in (1, 2):
        assert pipeline.upload_job(db, job.id) == "deferred" and job.status == JobStatus.READY and job.attempts == attempt
    assert pipeline.upload_job(db, job.id) == "failed" and job.status == JobStatus.FAILED and "Video is too long" in job.error
    assert db.scalars(select(BufferLog.state)).all() == ["failed"] * 3

