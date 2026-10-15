"""Every member has their own channels, Buffer accounts, videos and rules. Nobody sees anybody else's."""

from datetime import timedelta

import pytest
import respx
from sqlalchemy import select

from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import ActivityLog, BufferChannel, BufferKey, Channel, Job, JobStatus, User, Video, utcnow
from app.security import encrypt
from app.services import buffer, detection, rules

A_CHANNEL, B_CHANNEL = "UC" + "a" * 22, "UC" + "b" * 22


def page(channel_id: str, name: str) -> str:
    return f'<link rel="canonical" href="https://www.youtube.com/channel/{channel_id}"><meta property="og:title" content="{name}">'


@pytest.fixture
def youtube_pages(monkeypatch):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"https://www.youtube.com/channel/{A_CHANNEL}").respond(200, text=page(A_CHANNEL, "Alpha"))
        mock.get(f"https://www.youtube.com/channel/{B_CHANNEL}").respond(200, text=page(B_CHANNEL, "Bravo"))
        monkeypatch.setattr(youtube, "video_details", lambda vid: VideoMeta(vid, title=f"Title {vid}", duration_seconds=30, published_at=utcnow()))
        yield mock


def account(db, user_id: int, name: str) -> BufferChannel:
    """A member's Buffer key and one account connected there."""
    key = BufferKey(user_id=user_id, label="Key 1", api_key_enc=encrypt(f"key-of-{name}-0123456789"), saved_at=utcnow())
    db.add(key)
    db.flush()
    row = BufferChannel(user_id=user_id, key_id=key.id, mode="shorts", buffer_id=f"ch-{name}", name=name, service="tiktok", enabled=True, daily_limit=3, times=["09:00"])
    db.add(row)
    db.commit()
    return row


def ids(db) -> tuple[int, int]:
    users = db.scalars(select(User).order_by(User.id)).all()
    return users[0].id, users[1].id


def test_members_have_their_own_channels(client, auth, member_auth, db, youtube_pages):
    assert client.post("/api/channels", headers=auth, json={"query": A_CHANNEL}).status_code == 201
    assert client.post("/api/channels", headers=member_auth, json={"query": B_CHANNEL}).status_code == 201
    names = lambda who: [c["display_name"] for c in client.get("/api/channels", headers=who).json()["items"]]  # noqa: E731
    assert names(auth) == ["Alpha"] and names(member_auth) == ["Bravo"]

    # A channel belongs to the member who added it first; the other member is told who that is.
    r = client.post("/api/channels", headers=member_auth, json={"query": A_CHANNEL})
    assert r.status_code == 409 and r.json()["detail"] == "This channel has already been added by Alex Smith"
    card = client.post("/api/channels/resolve", headers=member_auth, json={"query": A_CHANNEL}).json()
    assert card["already_added"] is True and card["added_by"] == "Alex Smith"
    assert client.post("/api/channels/resolve", headers=auth, json={"query": A_CHANNEL}).json()["added_by"] is None  # your own

    # The other member's channel does not exist as far as you can tell.
    alpha = db.scalar(select(Channel).where(Channel.youtube_channel_id == A_CHANNEL))
    for method, path, body in (
        ("patch", f"/api/channels/{alpha.id}", {"active": False}), ("delete", f"/api/channels/{alpha.id}", None),
        ("post", f"/api/channels/{alpha.id}/check", None), ("get", f"/api/channels/{alpha.id}/rules", None),
        ("put", f"/api/channels/{alpha.id}/rules", {"values": {"hashtag_count": 3}}),
    ):
        response = getattr(client, method)(path, headers=member_auth, **({"json": body} if body else {}))
        assert response.status_code == 404, (method, path)
    assert db.get(Channel, alpha.id).active is True


def test_videos_reports_and_review_are_private(client, auth, member_auth, db, youtube_pages):
    mine, theirs = ids(db)
    client.post("/api/channels", headers=auth, json={"query": A_CHANNEL})
    client.post("/api/channels", headers=member_auth, json={"query": B_CHANNEL})
    alpha, bravo = (db.scalar(select(Channel).where(Channel.youtube_channel_id == c)) for c in (A_CHANNEL, B_CHANNEL))
    for channel in (alpha, bravo):
        channel.monitoring_since = utcnow() - timedelta(days=1)
    video_a, video_b = detection.discover(db, alpha, "aaa"), detection.discover(db, bravo, "bbb")
    assert (video_a.user_id, video_b.user_id) == (mine, theirs)
    job_a, job_b = (db.scalar(select(Job).where(Job.video_id == v.id)) for v in (video_a, video_b))
    job_a.status = job_b.status = JobStatus.AWAITING_APPROVAL
    job_a.video.rendered_file_path = job_b.video.rendered_file_path = "videos/none.mp4"
    db.commit()

    queue = lambda who: [j["id"] for j in client.get("/api/jobs?status=review", headers=who).json()["items"]]  # noqa: E731
    assert queue(auth) == [job_a.id] and queue(member_auth) == [job_b.id]
    for path in (f"/api/jobs/{job_a.id}", ):
        assert client.get(path, headers=member_auth).status_code == 404
    for action in ("approve", "cancel", "retry"):
        assert client.post(f"/api/jobs/{job_a.id}/{action}", headers=member_auth).status_code == 404
    assert client.post(f"/api/jobs/{job_a.id}/reject", headers=member_auth, json={"reason": "no"}).status_code == 404
    assert client.patch(f"/api/jobs/{job_a.id}", headers=member_auth, json={"rewritten_caption": "x"}).status_code == 404
    token = client.get("/api/auth/media-token", headers=member_auth).json()["token"]
    assert client.get(f"/api/videos/{video_a.id}/file?token={token}").status_code == 404
    assert db.get(Job, job_a.id).status == JobStatus.AWAITING_APPROVAL

    for who, expected in ((auth, 1), (member_auth, 1)):
        assert client.get("/api/dashboard/summary", headers=who).json()["kpis"][0]["value"] == expected
        assert client.get("/api/dashboard/nav", headers=who).json()["review_jobs"] == 1
        assert client.get("/api/pipeline/status", headers=who).json()["today"]["total"] == 1
        assert client.get("/api/reports/daily", headers=who).json()["accepted"] == 1
    # Activity: each member sees their own video; the admin's Logs page is the whole system log.
    activity = lambda who: " ".join(e["message"] for e in client.get("/api/dashboard/summary", headers=who).json()["recent_activity"])  # noqa: E731
    assert "Alpha" in activity(auth) and "Bravo" not in activity(auth) and "Bravo" in activity(member_auth) and "Alpha" not in activity(member_auth)
    member_log = " ".join(e["message"] for e in client.get("/api/logs", headers=member_auth).json()["items"])
    assert "Bravo" in member_log and "Alpha" not in member_log
    assert "Bravo" in " ".join(e["message"] for e in client.get("/api/logs", headers=auth).json()["items"])
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "video_detected", ActivityLog.user_id == theirs))


def test_members_have_their_own_buffer_accounts(client, auth, member_auth, db, youtube_pages, monkeypatch):
    mine, theirs = ids(db)
    acc_a, acc_b = account(db, mine, "alpha_tt"), account(db, theirs, "bravo_tt")
    names = lambda who: [a["name"] for a in client.get("/api/buffer", headers=who).json()["channels"]]  # noqa: E731
    assert names(auth) == ["alpha_tt"] and names(member_auth) == ["bravo_tt"]
    assert client.patch(f"/api/buffer/channels/{acc_a.id}", headers=member_auth, json={"daily_limit": 9}).status_code == 404
    assert client.get(f"/api/buffer/channels/{acc_a.id}/status", headers=member_auth).status_code == 404
    assert db.get(BufferChannel, acc_a.id).daily_limit == 3

    # A member's videos go only to that member's accounts: never to another member's, even when theirs is switched off.
    client.post("/api/channels", headers=member_auth, json={"query": B_CHANNEL})
    bravo = db.scalar(select(Channel).where(Channel.youtube_channel_id == B_CHANNEL))
    bravo.monitoring_since = utcnow() - timedelta(days=1)
    video = detection.discover(db, bravo, "bbb")
    job = db.scalar(select(Job).where(Job.video_id == video.id))
    assert buffer.choose(db, job)[0].id == acc_b.id
    assert client.patch(f"/api/jobs/{job.id}", headers=member_auth, json={"buffer_channel_id": acc_a.id}).status_code == 404  # not yours to choose
    acc_b.enabled = False
    db.commit()
    assert buffer.choose(db, job) == (None, buffer.NO_ACCOUNT)  # it waits
    # Removing your key removes only your own accounts.
    assert client.delete(f"/api/buffer/keys/{acc_b.key_id}", headers=member_auth).json()["channels"] == [] and names(auth) == ["alpha_tt"]


def test_members_have_their_own_rules(client, auth, member_auth, db, youtube_pages):
    mine, theirs = ids(db)
    assert client.put("/api/settings/rules", headers=member_auth, json={"values": {"hashtag_count": 12, "approval_required": False}}).status_code == 200
    assert client.put("/api/settings/rules?mode=podcasts", headers=member_auth, json={"values": {"clips_per_video": 5}}).status_code == 200
    get = lambda who, mode="": client.get(f"/api/settings/rules{mode}", headers=who).json()["values"]  # noqa: E731
    assert get(member_auth)["hashtag_count"] == 12 and get(auth)["hashtag_count"] == 8  # the admin's rules did not move
    assert get(member_auth, "?mode=podcasts")["clips_per_video"] == 5 and get(auth, "?mode=podcasts")["clips_per_video"] == 3
    assert rules.global_values(db, user_id=theirs)["approval_required"] is False and rules.global_values(db, user_id=mine)["approval_required"] is True
    assert len(client.get("/api/settings/rules/history", headers=member_auth).json()) == 2
    assert client.get("/api/settings/rules/history", headers=auth).json() == []

    # The rules that edit a video are its owner's.
    client.post("/api/channels", headers=auth, json={"query": A_CHANNEL})
    client.post("/api/channels", headers=member_auth, json={"query": B_CHANNEL})
    alpha, bravo = (db.scalar(select(Channel).where(Channel.youtube_channel_id == c)) for c in (A_CHANNEL, B_CHANNEL))
    alpha.monitoring_since = bravo.monitoring_since = utcnow() - timedelta(days=1)
    video_a, video_b = detection.discover(db, alpha, "aaa"), detection.discover(db, bravo, "bbb")
    assert rules.for_video(db, video_a)["hashtag_count"] == 8 and rules.for_video(db, video_b)["hashtag_count"] == 12
    job_a, job_b = (db.scalar(select(Job).where(Job.video_id == v.id)) for v in (video_a, video_b))
    assert job_a.approval_required is True and job_b.approval_required is False
    assert db.scalar(select(Video).where(Video.user_id.is_(None))) is None
