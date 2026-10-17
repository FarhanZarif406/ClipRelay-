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
KEY2 = "buf_second_key_0123456789abcdefgh"
UTC = timezone.utc


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


class FakeBuffer:
    """Stands in for Buffer's GraphQL API: answers by the name of the operation."""

    def __init__(self):
        self.channels = [{"id": "ch-tiktok", "name": "simran", "displayName": "simran_sing0", "service": "tiktok", "avatar": None},
                         {"id": "ch-insta", "name": "insta", "displayName": None, "service": "instagram", "avatar": None}]
        self.second = [{"id": "ch-tiktok-2", "name": "two", "displayName": "second_tt", "service": "tiktok", "avatar": None},
                       {"id": "ch-tiktok", "name": "simran", "displayName": "simran_sing0", "service": "tiktok", "avatar": None}]  # reached by both keys
        self.posts: list[str] = []
        self.used: list[str] = []  # the key each post was made with
        self.post_state = {"status": "scheduled"}
        self.refuse: str | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.headers["authorization"].removeprefix("Bearer ")
        if key not in (KEY, KEY2):
            return httpx.Response(401, json={"errors": [{"message": "unauthorized"}]})
        query = json.loads(request.content)["query"]
        if query.startswith("query Organizations"):
            return httpx.Response(200, json={"data": {"account": {"organizations": [{"id": "org-1", "name": "Mine"}]}}})
        if query.startswith("query Channels"):
            return httpx.Response(200, json={"data": {"channels": self.channels if key == KEY else self.second}})
        if query.startswith("mutation CreatePost"):
            self.posts.append(query)
            self.used.append(key)
            if self.refuse:
                return httpx.Response(200, json={"data": {"createPost": {"message": self.refuse}}})
            due = query.split('dueAt: "')[1].split('"')[0] if 'dueAt: "' in query else utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")  # shareNow: at once
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
    assert client.post("/api/buffer/keys", headers=auth, json={"api_key": "has spaces in it, not a key"}).status_code == 400
    r = client.post("/api/buffer/keys", headers=auth, json={"api_key": "wrong_key_0123456789abcdefghij"})
    assert r.status_code == 400 and "refused the API key" in r.json()["detail"]
    assert client.get("/api/buffer", headers=auth).json()["connected"] is False  # a refused key is not kept

    saved = client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY})
    status = saved.json()
    assert saved.status_code == 200 and KEY not in saved.text and [(k["label"], k["last4"], k["accounts"]) for k in status["keys"]] == [("Key 1", KEY[-4:], 2)]
    names = {c["name"]: c for c in status["channels"]}
    assert set(names) == {"simran_sing0", "insta"}
    assert names["simran_sing0"]["enabled"] is True and names["insta"]["enabled"] is False  # only TikTok is on from the start
    assert names["simran_sing0"]["times"] == ["09:00", "13:00", "18:00"] and names["simran_sing0"]["daily_limit"] == 3 and names["simran_sing0"]["next_slot"]
    # Each workspace has its own rows, and another member sees none of it.
    assert len(client.get("/api/buffer?mode=podcasts", headers=auth).json()["channels"]) == 2
    assert client.get("/api/buffer", headers=member_auth).json() | {"time_zone": ""} == {"connected": False, "max_keys": 10, "max_accounts": 0, "keys": [], "public_url": False, "time_zone": "", "up_next": None, "channels": []}
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
    key_id = status["keys"][0]["id"]
    assert client.delete(f"/api/buffer/keys/{key_id}", headers=member_auth).status_code == 404
    assert client.delete(f"/api/buffer/keys/{key_id}", headers=auth).json() | {"time_zone": "", "public_url": False} == {"connected": False, "max_keys": 10, "max_accounts": 0, "keys": [], "public_url": False, "time_zone": "", "up_next": None, "channels": []}
    assert db.scalar(select(BufferChannel)) is None


def _connect(client, auth, db, monkeypatch):
    client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY})
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
    client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY})
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_PUBLIC_URL and job.status == JobStatus.READY  # http://api.test is not public
    channel = _connect(client, auth, db, monkeypatch)

    def change(**values):  # the page saves through its own connection; this one then reads the account afresh
        response = client.patch(f"/api/buffer/channels/{channel.id}", headers=auth, json=values)
        db.expire_all()
        return response

    change(times=[], start_date="2099-01-01")  # no times, and not started yet: nothing can go out
    assert pipeline.upload_job(db, job.id) == "deferred" and job.error == buffer.NO_TIMES
    change(start_date=None)
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



def test_several_keys_and_accounts_take_turns(client, auth, db, fake, monkeypatch):
    first = client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY}).json()
    assert client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY}).json()["detail"] == "This key is already saved."
    both = client.post("/api/buffer/keys", headers=auth, json={"api_key": KEY2, "label": "Brand page"}).json()
    assert [(k["label"], k["accounts"]) for k in both["keys"]] == [("Key 1", 2), ("Brand page", 1)]  # simran is reached by both keys, listed once
    assert {(c["name"], c["key_label"]) for c in both["channels"]} == {("simran_sing0", "Key 1"), ("insta", "Key 1"), ("second_tt", "Brand page")}
    assert client.post("/api/buffer/keys", headers=auth, json={"api_key": "buf_third_key_0123456789abcdefg"}).status_code == 400  # Buffer refuses it
    assert client.patch(f"/api/buffer/keys/{both['keys'][1]['id']}", headers=auth, json={"label": "Key 1"}).status_code == 400  # names stay apart
    monkeypatch.setattr(buffer, "MAX_KEYS", 2)
    assert "Up to 2" in client.post("/api/buffer/keys", headers=auth, json={"api_key": "buf_third_key_0123456789abcdefg"}).json()["detail"]
    monkeypatch.setattr(push, "base_url", lambda: "https://clips.example.com")
    for c in both["channels"]:  # every account on, with the same times, so only the turns decide
        client.patch(f"/api/buffer/channels/{c['id']}", headers=auth, json={"enabled": True, "times": ["09:00", "13:00", "18:00"], "daily_limit": 10})
    db.expire_all()

    # Six clips go round the three accounts twice, each with the key that reaches it.
    picked = []
    for n in range(6):
        job = _make_job(db, status=JobStatus.READY, youtube_video_id=f"turn{n}")
        assert pipeline.upload_job(db, job.id) == "scheduled"
        db.commit()
        db.refresh(job)
        picked.append(job.buffer_channel.name)
    assert picked[:3] == ["insta", "simran_sing0", "second_tt"] and picked[3:] == picked[:3]
    assert fake.used == [KEY, KEY, KEY2] * 2
    insta = db.scalar(select(BufferChannel).where(BufferChannel.name == "insta", BufferChannel.mode == Mode.SHORTS))
    assert client.get("/api/buffer", headers=auth).json()["up_next"] == insta.id

    # A switched-off account is passed over; the others keep taking turns.
    client.patch(f"/api/buffer/channels/{insta.id}", headers=auth, json={"enabled": False})
    db.expire_all()
    job = _make_job(db, status=JobStatus.READY, youtube_video_id="turn6")
    pipeline.upload_job(db, job.id)
    db.commit()
    db.refresh(job)
    assert job.buffer_channel.name == "simran_sing0"
    db.commit()

    # Removing Key 1 hands simran to the other key that reaches it; insta goes with the key.
    removed = client.delete(f"/api/buffer/keys/{first['keys'][0]['id']}", headers=auth).json()
    assert [k["label"] for k in removed["keys"]] == ["Brand page"]
    assert {(c["name"], c["key_label"]) for c in removed["channels"]} == {("simran_sing0", "Brand page"), ("second_tt", "Brand page")}


def test_an_account_without_times_publishes_at_once(client, auth, db, fake, monkeypatch):
    channel = _connect(client, auth, db, monkeypatch)
    client.patch(f"/api/buffer/channels/{channel.id}", headers=auth, json={"times": [], "daily_limit": 2})
    db.expire_all()
    row = next(c for c in client.get("/api/buffer", headers=auth).json()["channels"] if c["id"] == channel.id)
    assert row["at_once"] is True and row["next_slot"]  # it can take a clip right now

    first = _make_job(db, status=JobStatus.READY, youtube_video_id="now1")
    assert pipeline.upload_job(db, first.id) == "scheduled"
    assert "mode: shareNow" in fake.posts[-1] and 'dueAt: "' not in fake.posts[-1]
    db.commit()
    assert abs((first.buffer_due_at - utcnow()).total_seconds()) < 120  # counts on today's limit
    second = _make_job(db, status=JobStatus.READY, youtube_video_id="now2")
    assert pipeline.upload_job(db, second.id) == "scheduled"
    db.commit()
    # Its daily limit of 2 is used: the third waits for room instead of going out.
    third = _make_job(db, status=JobStatus.READY, youtube_video_id="now3")
    assert pipeline.upload_job(db, third.id) == "deferred" and third.error == buffer.NO_TIMES and len(fake.posts) == 2

    # An account with times keeps its schedule: the next clip waits for its time there.
    client.patch(f"/api/buffer/channels/{channel.id}", headers=auth, json={"times": ["09:00"], "daily_limit": 5})
    db.expire_all()
    third.next_check_at = None
    db.commit()
    assert pipeline.upload_job(db, third.id) == "scheduled" and "mode: customScheduled" in fake.posts[-1]


def test_the_plan_caps_how_many_buffer_accounts_connect(client, member_auth, db, fake):
    from app.models import Plan, User

    plan = Plan(name="Tiny", features={}, limits={"buffer_keys": 1, "buffer_accounts": 1})
    db.add(plan)
    db.flush()
    member = db.scalar(select(User).where(User.role == "member"))
    member.plan_id = plan.id
    db.commit()

    status = client.post("/api/buffer/keys", headers=member_auth, json={"api_key": KEY}).json()
    assert status["max_accounts"] == 1 and status["max_keys"] == 1
    assert len({c["name"] for c in status["channels"]}) == 1  # Buffer has 2; the plan allows 1
    assert "allows 1 Buffer account" in status["keys"][0]["error"] and "1 more were not connected" in status["keys"][0]["error"]
    assert "Up to 1 Buffer key" in client.post("/api/buffer/keys", headers=member_auth, json={"api_key": KEY2}).json()["detail"]

    # A bigger plan connects the rest on the next refresh.
    plan.limits = {"buffer_keys": 3, "buffer_accounts": 9}
    db.commit()
    again = client.post("/api/buffer/refresh", headers=member_auth).json()
    assert len({c["name"] for c in again["channels"]}) == 2 and again["keys"][0]["error"] is None
