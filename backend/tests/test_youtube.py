import hashlib
import hmac
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select

from tests.conftest import ME
from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import ActivityLog, Channel, Job, JobStatus, RuleChange, SkipReason, Video, VideoStatus, utcnow
from app.services import detection, dispatch, rules

CHANNEL_ID = "UC" + "a" * 22
PAGE = f'''<html><head><link rel="canonical" href="https://www.youtube.com/channel/{CHANNEL_ID}">
<meta property="og:title" content="Northbound &amp; Co"><meta property="og:image" content="https://img.test/a.jpg">
</head><body>"vanityChannelUrl":"http://www.youtube.com/@northbound"</body></html>'''


def atom(*videos: tuple[str, str], channel: str = CHANNEL_ID) -> bytes:
    entries = "".join(
        f"<entry><yt:videoId>{video_id}</yt:videoId><yt:channelId>{channel}</yt:channelId><title>t {video_id}</title><published>{published}</published></entry>"
        for video_id, published in videos
    )
    return f'<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()


def meta(video_id: str, duration: float = 30, **extra) -> VideoMeta:
    values = {"title": f"Title {video_id}", "description": "About the trip", "tags": ["travel"], "published_at": utcnow(), "channel_id": CHANNEL_ID}
    return VideoMeta(video_id, duration_seconds=duration, **{**values, **extra})


@pytest.fixture
def details(monkeypatch):
    """Metadata for `youtube.video_details`, by video id (30 seconds unless set)."""
    known: dict[str, VideoMeta] = {}
    monkeypatch.setattr(youtube, "video_details", lambda video_id: known.get(video_id) or meta(video_id))
    monkeypatch.setattr(youtube, "is_short", lambda video_id: video_id.startswith("short"))
    return known


# ---------------------------------------------------------------- YouTube integration

def test_channel_query_forms():
    parse = youtube.parse_channel_query
    assert parse("@northbound") == ("handle", "@northbound") and parse("northbound") == ("handle", "@northbound")
    assert parse(f"https://www.youtube.com/channel/{CHANNEL_ID}/videos") == ("id", CHANNEL_ID)
    assert parse("youtube.com/@northbound/shorts") == ("handle", "@northbound")
    assert parse("https://youtube.com/c/Northbound") == ("path", "/c/Northbound")
    for bad in ("https://www.youtube.com/watch?v=abc", "https://youtu.be/abc", "https://vimeo.com/x", ""):
        with pytest.raises(youtube.YouTubeError):
            parse(bad)


@respx.mock
def test_resolve_channel_from_the_public_page():
    respx.get("https://www.youtube.com/@northbound").mock(return_value=httpx.Response(200, text=PAGE))
    info = youtube.resolve_channel("@northbound")
    assert (info.youtube_channel_id, info.display_name, info.handle, info.thumbnail_url) == (CHANNEL_ID, "Northbound & Co", "@northbound", "https://img.test/a.jpg")
    respx.get("https://www.youtube.com/@nobody").mock(return_value=httpx.Response(404))
    with pytest.raises(youtube.YouTubeError, match="No YouTube channel"):
        youtube.resolve_channel("@nobody")


@respx.mock
def test_feed_is_parsed_oldest_first():
    respx.get(youtube.FEED_URL).mock(return_value=httpx.Response(200, content=atom(("new", "2026-10-02T10:00:00+00:00"), ("old", "2026-10-01T10:00:00+00:00"))))
    assert [e.video_id for e in youtube.feed(CHANNEL_ID)] == ["old", "new"]


def test_xml_with_entities_is_refused():
    with pytest.raises(youtube.YouTubeError):
        youtube.parse_notification(b'<!DOCTYPE x [<!ENTITY a "b">]><feed/>')


def test_iso_duration_and_signature():
    assert youtube.parse_iso_duration("PT1M5S") == 65 and youtube.parse_iso_duration("PT45S") == 45 and youtube.parse_iso_duration("x") is None
    body = b"<feed/>"
    good = hmac.new(youtube.hub_secret().encode(), body, hashlib.sha1).hexdigest()
    assert youtube.verify_signature(body, f"sha1={good}")
    assert not youtube.verify_signature(body, "sha1=forged") and not youtube.verify_signature(body, None)


# ---------------------------------------------------------------- rules

def test_rules_inherit_override_and_audit(db, channel, client, auth):
    assert rules.effective(db, channel.id, user_id=1)["hashtag_count"] == 8 and rules.effective(db, user_id=1)["cap_reset_timezone"] == "Asia/Karachi"
    rules.set_values(db, {"hashtag_count": 10}, user=ME)
    rules.set_values(db, {"hashtag_count": 12, "videos_per_channel_per_day": 9}, channel=channel)
    assert rules.effective(db, user_id=1)["hashtag_count"] == 10 and rules.effective(db, channel.id, user_id=1)["hashtag_count"] == 12
    rules.set_values(db, {"hashtag_count": None}, channel=channel)  # remove the override: inherit again
    assert rules.effective(db, channel.id, user_id=1)["hashtag_count"] == 10 and rules.effective(db, channel.id, user_id=1)["videos_per_channel_per_day"] == 9
    changes = db.scalars(select(RuleChange).order_by(RuleChange.id)).all()
    assert [(c.key, c.old_value, c.new_value, c.channel_id) for c in changes] == [
        ("hashtag_count", 8, 10, None), ("hashtag_count", None, 12, channel.id), ("videos_per_channel_per_day", None, 9, channel.id), ("hashtag_count", 12, None, channel.id),
    ]
    for bad in ({"hashtag_count": -1}, {"hashtag_count": "many"}, {"hashtag_count": 16}, {"speed": 1.2}, {"cap_reset_timezone": "Mars/Base"}, {"nope": 1}, {"min_duration_seconds": 500}):
        with pytest.raises(ValueError):
            rules.set_values(db, bad, user=ME)
    for global_only in ({"cap_reset_timezone": "UTC"}, {"approval_required": False}):  # one switch, not one per channel
        with pytest.raises(ValueError, match="only be set globally"):
            rules.set_values(db, global_only, channel=channel)
    db.commit()

    r = client.put("/api/settings/rules", headers=auth, json={"values": {"hashtag_count": 5}})
    assert r.status_code == 200 and r.json()["values"]["hashtag_count"] == 5
    assert client.put("/api/settings/rules", headers=auth, json={"values": {"hashtag_count": 99}}).status_code == 422
    history = client.get("/api/settings/rules/history", headers=auth).json()
    assert history[0]["key"] == "hashtag_count" and history[0]["changed_by"] == "alex@example.com" and history[0]["changed_at"]
    r = client.put(f"/api/channels/{channel.id}/rules", headers=auth, json={"values": {"min_duration_seconds": 7}})
    assert r.json()["overrides"] == {"videos_per_channel_per_day": 9, "min_duration_seconds": 7} and r.json()["effective"]["hashtag_count"] == 5


# ---------------------------------------------------------------- detection

def test_new_upload_is_stored_once_and_gets_one_job(db, channel, details):
    video = detection.discover(db, channel, "abc")
    db.commit()
    assert video.status == VideoStatus.ACCEPTED and video.youtube_video_id == "abc" and video.channel_id == channel.id
    assert video.original_title == "Title abc" and video.original_caption == "About the trip" and video.duration_sec == 30
    job = db.scalar(select(Job))
    assert job.status == JobStatus.FETCHED and job.buffer_channel_id is None and job.error is None and job.approval_required is True
    # A repeat notification (YouTube sends one whenever the title is edited) changes nothing.
    assert detection.discover(db, channel, "abc") is None
    assert len(db.scalars(select(Video)).all()) == 1 and len(db.scalars(select(Job)).all()) == 1


def test_duration_checks_hold_the_video_with_a_reason(db, channel, details):
    details["long"], details["tiny"] = meta("long", 181), meta("tiny", 4)
    long_video, tiny = detection.discover(db, channel, "long"), detection.discover(db, channel, "tiny")
    assert (long_video.status, long_video.skip_reason) == (VideoStatus.SKIPPED, SkipReason.LONG_FORM) and "181s" in long_video.rejection_reason
    assert tiny.skip_reason == SkipReason.TOO_SHORT and db.scalar(select(Job)) is None
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "video_skipped"))
    rules.set_values(db, {"max_duration_seconds": 600}, channel=channel)  # a channel override applies to the next video
    details["long2"] = meta("long2", 181)
    assert detection.discover(db, channel, "long2").status == VideoStatus.ACCEPTED


def test_short_means_under_the_limit_or_a_youtube_short(db, channel, details):
    details["regular1"] = meta("regular1", 95)  # under the limit: short-form, whatever YouTube calls it
    assert detection.discover(db, channel, "regular1").status == VideoStatus.ACCEPTED
    details["short-long"] = meta("short-long", 200)  # over the limit, but YouTube lists it as a Short
    assert detection.discover(db, channel, "short-long").status == VideoStatus.ACCEPTED
    details["regular2"] = meta("regular2", 200)  # over the limit and not a Short: long-form
    video = detection.discover(db, channel, "regular2")
    assert (video.status, video.skip_reason) == (VideoStatus.SKIPPED, "long-form")


def test_push_status(db, channel, monkeypatch):
    assert detection.push_status(channel) == "unavailable"  # no public HTTPS address in the test settings
    monkeypatch.setattr(youtube, "push_available", lambda: True)
    assert detection.push_status(channel) == "pending"
    channel.pubsub_subscription_expires_at = utcnow() + timedelta(days=3)
    assert detection.push_status(channel) == "subscribed"
    channel.pubsub_subscription_expires_at = utcnow() - timedelta(minutes=1)
    assert detection.push_status(channel) == "expired"
    channel.pubsub_error = "hub refused"
    assert detection.push_status(channel) == "failed"
    channel.active = False
    assert detection.push_status(channel) == "off"


@respx.mock
def test_subscriptions_are_renewed_before_they_lapse(db, channel, monkeypatch):
    monkeypatch.setattr(youtube, "push_available", lambda: True)
    hub = respx.post(youtube.HUB_URL).mock(return_value=httpx.Response(202))
    channel.pubsub_subscription_expires_at = utcnow() + timedelta(days=4)
    assert detection.renew_subscriptions(db) == {"renewed": 0} and hub.call_count == 0
    channel.pubsub_subscription_expires_at = utcnow() + timedelta(hours=20)
    assert detection.renew_subscriptions(db) == {"renewed": 1}
    sent = hub.calls[0].request.content.decode()
    assert "hub.mode=subscribe" in sent and "hub.secret=" in sent and "channel_id%3D" + channel.youtube_channel_id in sent
    assert "hub.callback=http%3A%2F%2Fapi.test%2Fapi%2Fyoutube%2Fwebhook" in sent
    hub.mock(return_value=httpx.Response(500, text="down"))
    channel.pubsub_subscription_expires_at = None
    assert detection.renew_subscriptions(db) == {"renewed": 0} and detection.push_status(channel) == "failed"


@respx.mock
def test_is_short_reads_youtubes_own_answer(db, channel, details, monkeypatch):
    monkeypatch.undo()
    respx.get("https://www.youtube.com/shorts/s1").mock(return_value=httpx.Response(200, text="ok"))
    respx.get("https://www.youtube.com/shorts/v1").mock(return_value=httpx.Response(303, headers={"location": "https://www.youtube.com/watch?v=v1"}))
    respx.get("https://www.youtube.com/shorts/x1").mock(return_value=httpx.Response(302, headers={"location": "https://consent.youtube.com/m?continue=x"}))
    assert youtube.is_short("s1") is True and youtube.is_short("v1") is False
    with pytest.raises(youtube.YouTubeError):
        youtube.is_short("x1")
    # No answer from YouTube: nothing is stored, so the next poll or push tries the video again.
    monkeypatch.setattr(youtube, "video_details", lambda video_id: meta(video_id, 400))
    with pytest.raises(youtube.YouTubeError):
        detection.discover(db, channel, "x1")
    assert db.scalar(select(Video)) is None


def test_old_live_and_foreign_videos_are_ignored(db, channel, details):
    details["old"] = meta("old", published_at=utcnow() - timedelta(days=30))  # e.g. an old video whose title was edited
    details["live"] = meta("live", live=True)
    details["other"] = meta("other", channel_id="UC" + "b" * 22)
    assert [detection.discover(db, channel, v) for v in ("old", "live", "other")] == [None, None, None]
    assert db.scalar(select(Video)) is None


def test_channel_cap_and_process_anyway(db, channel, details):
    rules.set_values(db, {"videos_per_channel_per_day": 2}, user=ME)
    statuses = [detection.discover(db, channel, v) for v in ("a", "b", "c")]
    assert [v.status for v in statuses] == [VideoStatus.ACCEPTED, VideoStatus.ACCEPTED, VideoStatus.SKIPPED]
    held = statuses[2]
    assert held.skip_reason == SkipReason.CHANNEL_CAP
    job = detection.process_anyway(db, held)
    assert held.status == VideoStatus.ACCEPTED and held.forced and held.skip_reason is None and job.status == JobStatus.FETCHED
    with pytest.raises(ValueError):
        detection.process_anyway(db, held)


@respx.mock
def test_poll_finds_only_new_uploads(db, channel, details):
    old = (utcnow() - timedelta(days=5)).isoformat()
    new = utcnow().isoformat()
    respx.get(youtube.FEED_URL).mock(return_value=httpx.Response(200, content=atom(("before", old), ("fresh", new))))
    assert [v.youtube_video_id for v in detection.poll_channel(db, channel)] == ["fresh"]
    assert channel.last_checked_at and channel.next_poll_at > utcnow() and channel.last_error is None
    assert detection.poll_channel(db, channel) == []  # caught exactly once
    respx.get(youtube.FEED_URL).mock(return_value=httpx.Response(500))
    assert detection.poll_channel(db, channel) == [] and "500" in channel.last_error


def test_due_channels_are_leased(db, channel):
    assert detection.due_channels(db) == [channel.id] and detection.due_channels(db) == []
    channel.active, channel.next_poll_at = False, None
    assert detection.due_channels(db) == []


# ---------------------------------------------------------------- API

@respx.mock
def test_add_channel(client, auth, db):
    respx.get("https://www.youtube.com/@northbound").mock(return_value=httpx.Response(200, text=PAGE))
    card = client.post("/api/channels/resolve", headers=auth, json={"query": "@northbound"}).json()
    assert card["display_name"] == "Northbound & Co" and card["already_added"] is False
    body = {"query": "@northbound"}
    r = client.post("/api/channels", headers=auth, json=body)
    assert r.status_code == 201 and r.json()["display_name"] == "Northbound & Co" and "default_tiktok_account" not in r.json()
    row = db.scalar(select(Channel))
    assert row.added_by and row.ownership_confirmed_at is None and row.pubsub_subscription_expires_at is None
    assert client.post("/api/channels", headers=auth, json=body).status_code == 409
    assert client.post("/api/channels/resolve", headers=auth, json={"query": "https://youtu.be/x"}).status_code == 400

    listing = client.get("/api/channels", headers=auth).json()
    assert listing["push_available"] is False and listing["items"][0]["active"] is True
    assert client.patch(f"/api/channels/{row.id}", headers=auth, json={"active": False}).json()["active"] is False
    assert client.delete(f"/api/channels/{row.id}", headers=auth).status_code == 204


@respx.mock
def test_check_now_queues_download_and_caption_together(client, auth, channel, details):
    respx.get(youtube.FEED_URL).mock(return_value=httpx.Response(200, content=atom(("fresh", utcnow().isoformat()))))
    r = client.post(f"/api/channels/{channel.id}/check", headers=auth).json()
    assert r == {"found": 1, "queued": 1, "skipped": 0, "error": None}
    assert [name for name, _args in dispatch.sent] == ["process_video", "rewrite_job"]


def test_push_webhook(client, db, channel, monkeypatch):
    monkeypatch.setattr(youtube, "push_available", lambda: True)
    topic = youtube.topic_url(channel.youtube_channel_id)
    r = client.get("/api/youtube/webhook", params={"hub.mode": "subscribe", "hub.topic": topic, "hub.challenge": "xyz", "hub.lease_seconds": 432000})
    assert r.status_code == 200 and r.text == "xyz"
    db.refresh(channel)
    assert channel.pubsub_subscription_expires_at > utcnow() + timedelta(days=4)
    unknown = youtube.topic_url("UC" + "z" * 22)
    assert client.get("/api/youtube/webhook", params={"hub.mode": "subscribe", "hub.topic": unknown, "hub.challenge": "x"}).status_code == 404

    body = atom(("abc", utcnow().isoformat()))
    signature = "sha1=" + hmac.new(youtube.hub_secret().encode(), body, hashlib.sha1).hexdigest()
    assert client.post("/api/youtube/webhook", content=body, headers={"X-Hub-Signature": "sha1=forged"}).status_code == 204
    assert dispatch.sent == []  # unsigned notifications are ignored
    assert client.post("/api/youtube/webhook", content=body, headers={"X-Hub-Signature": signature}).status_code == 204
    assert dispatch.sent == [("discover_video", (channel.youtube_channel_id, "abc"))]


def test_review_published_and_skipped_screens(client, auth, db, channel, details):
    details["long"] = meta("long", 400)
    detection.discover(db, channel, "ok")
    detection.discover(db, channel, "long")
    job = db.scalar(select(Job))
    job.status, job.caption_status, job.video.rendered_file_path = JobStatus.AWAITING_APPROVAL, "caption_fallback", "videos/missing.mp4"
    db.commit()

    review = client.get("/api/jobs?status=review&order=oldest", headers=auth).json()["items"]
    assert len(review) == 1 and review[0]["caption_fallback"] is True and review[0]["video"]["channel"]["display_name"] == "Northbound"
    assert review[0]["video"]["permalink"] == "https://www.youtube.com/watch?v=ok"
    assert client.post(f"/api/jobs/{job.id}/reject", headers=auth, json={"reason": ""}).status_code == 422
    rejected = client.post(f"/api/jobs/{job.id}/reject", headers=auth, json={"reason": "Not ours"}).json()
    assert rejected["status"] == "cancelled" and rejected["reject_reason"] == "Not ours"

    skipped = client.get("/api/videos?status=skipped", headers=auth).json()
    assert [(v["youtube_video_id"], v["skip_reason"]) for v in skipped] == [("long", "long-form")]
    dispatch.sent.clear()
    forced = client.post(f"/api/videos/{skipped[0]['id']}/process", headers=auth).json()
    assert forced["status"] == "fetched" and [name for name, _ in dispatch.sent] == ["process_video", "rewrite_job"]
    assert client.get("/api/videos?status=skipped", headers=auth).json() == []
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert nav["channels"] == 1 and nav["review_jobs"] == 0 and nav["skipped_videos"] == 0


def test_video_file_needs_a_media_token(client, auth, db):
    import os

    from app.services.storage import get_storage

    path = os.path.join(get_storage().root, "videos", "9.mp4")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00" * 64)
    video = Video(user_id=1, youtube_video_id="f", status=VideoStatus.ACCEPTED, rendered_file_path="videos/9.mp4")
    db.add(video)
    db.commit()
    token = client.get("/api/auth/media-token", headers=auth).json()["token"]
    assert client.get(f"/api/videos/{video.id}/file?token={token}").headers["content-type"] == "video/mp4"
    login_token = auth["Authorization"].split()[1]
    assert client.get(f"/api/videos/{video.id}/file?token={login_token}").status_code == 401
    assert client.get("/api/dashboard/nav", headers={"Authorization": f"Bearer {token}"}).status_code == 401  # not a login


def test_terms_acceptance_is_recorded(client, auth, db):
    from app.models import User

    assert db.scalar(select(User)).terms_accepted_at is None
    r = client.post("/api/auth/login", json={"email": "alex@example.com", "password": "password123", "accept_terms": True})
    assert r.status_code == 200 and r.json()["user"]["terms_accepted_at"]


def test_removing_a_channel_stops_its_unfinished_videos_and_frees_them(client, auth, db, channel, details):
    waiting, posted = detection.discover(db, channel, "w1"), detection.discover(db, channel, "p1")
    job_posted = db.scalar(select(Job).where(Job.video_id == posted.id))
    job_posted.status, job_posted.buffer_due_at = JobStatus.SCHEDULED, utcnow()
    rules.set_values(db, {"hashtag_count": 3}, channel=channel)
    db.commit()
    old_id = channel.id
    assert client.delete(f"/api/channels/{old_id}", headers=auth).status_code == 204
    db.expire_all()
    assert db.scalar(select(Job).where(Job.video_id == waiting.id)).status == JobStatus.CANCELLED
    assert db.get(Job, job_posted.id).status == JobStatus.SCHEDULED  # already at Buffer: it still goes out
    # The videos stay as history but belong to no channel, so a new channel that gets the same id does not inherit them.
    assert [v.channel_id for v in db.scalars(select(Video))] == [None, None]
    assert db.scalar(select(func.count()).select_from(rules.RuleSetting).where(rules.RuleSetting.channel_id == old_id)) == 0
