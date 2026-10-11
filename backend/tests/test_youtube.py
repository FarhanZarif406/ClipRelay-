import hashlib
import hmac
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import select

from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import ActivityLog, Channel, Job, JobStatus, RuleChange, SkipReason, Video, VideoStatus, utcnow
from app.services import detection, dispatch, media, rules

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
    monkeypatch.setattr(youtube, "is_short", lambda video_id: not video_id.startswith("regular"))
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


def test_render_command_only_does_the_two_edits():
    cmd = " ".join(media.render_command("in.mp4", "out.mp4", speed=1.08, flip=True, keep_audio=True, has_audio=True))
    assert "-vf hflip,setpts=PTS/1.0800" in cmd and "-af atempo=1.0800" in cmd and "libx264" in cmd and "aac" in cmd
    assert "crop" not in cmd and "scale" not in cmd and " -t " not in cmd and " -r " not in cmd
    untouched = " ".join(media.render_command("in.mp4", "out.mp4", speed=1.0, flip=False, keep_audio=True, has_audio=True))
    assert "-c:v copy" in untouched and "-c:a copy" in untouched  # nothing to change, nothing re-encoded
    muted = media.render_command("in.mp4", "out.mp4", speed=1.0, flip=True, keep_audio=False, has_audio=True)
    assert "-an" in muted and "-af" not in muted


# ---------------------------------------------------------------- rules

def test_rules_inherit_override_and_audit(db, channel, client, auth):
    assert rules.effective(db, channel.id)["speed"] == 1.08 and rules.effective(db)["cap_reset_timezone"] == "Asia/Karachi"
    rules.set_values(db, {"speed": 1.2})
    rules.set_values(db, {"speed": 1.4, "approval_required": False}, channel=channel)
    assert rules.effective(db)["speed"] == 1.2 and rules.effective(db, channel.id)["speed"] == 1.4
    rules.set_values(db, {"speed": None}, channel=channel)  # remove the override: inherit again
    assert rules.effective(db, channel.id)["speed"] == 1.2 and rules.effective(db, channel.id)["approval_required"] is False
    changes = db.scalars(select(RuleChange).order_by(RuleChange.id)).all()
    assert [(c.key, c.old_value, c.new_value, c.channel_id) for c in changes] == [
        ("speed", 1.08, 1.2, None), ("speed", None, 1.4, channel.id), ("approval_required", None, False, channel.id), ("speed", 1.4, None, channel.id),
    ]
    for bad in ({"speed": 2}, {"speed": "fast"}, {"hashtag_count": 16}, {"cap_reset_timezone": "Mars/Base"}, {"nope": 1}, {"min_duration_seconds": 500}):
        with pytest.raises(ValueError):
            rules.set_values(db, bad)
    with pytest.raises(ValueError, match="only be set globally"):
        rules.set_values(db, {"cap_reset_timezone": "UTC"}, channel=channel)
    db.commit()

    r = client.put("/api/settings/rules", headers=auth, json={"values": {"hashtag_count": 5}})
    assert r.status_code == 200 and r.json()["values"]["hashtag_count"] == 5
    assert client.put("/api/settings/rules", headers=auth, json={"values": {"speed": 9}}).status_code == 422
    history = client.get("/api/settings/rules/history", headers=auth).json()
    assert history[0]["key"] == "hashtag_count" and history[0]["changed_by"] == "alex@example.com" and history[0]["changed_at"]
    r = client.put(f"/api/channels/{channel.id}/rules", headers=auth, json={"values": {"horizontal_flip": False}})
    assert r.json()["overrides"] == {"approval_required": False, "horizontal_flip": False} and r.json()["effective"]["hashtag_count"] == 5


# ---------------------------------------------------------------- detection

def test_new_upload_is_stored_once_and_gets_one_job(db, channel, tiktok_account, details):
    video = detection.discover(db, channel, "abc")
    db.commit()
    assert video.status == VideoStatus.ACCEPTED and video.youtube_video_id == "abc" and video.channel_id == channel.id
    assert video.original_title == "Title abc" and video.original_caption == "About the trip" and video.duration_sec == 30
    job = db.scalar(select(Job))
    assert job.status == JobStatus.FETCHED and job.tiktok_account_id == tiktok_account.id and job.approval_required is True
    # A repeat notification (YouTube sends one whenever the title is edited) changes nothing.
    assert detection.discover(db, channel, "abc") is None
    assert len(db.scalars(select(Video)).all()) == 1 and len(db.scalars(select(Job)).all()) == 1


def test_duration_checks_hold_the_video_with_a_reason(db, channel, details):
    details["long"], details["tiny"] = meta("long", 181), meta("tiny", 4)
    long_video, tiny = detection.discover(db, channel, "long"), detection.discover(db, channel, "tiny")
    assert (long_video.status, long_video.skip_reason) == (VideoStatus.SKIPPED, SkipReason.TOO_LONG) and "181s" in long_video.rejection_reason
    assert tiny.skip_reason == SkipReason.TOO_SHORT and db.scalar(select(Job)) is None
    assert db.scalar(select(ActivityLog).where(ActivityLog.event == "video_skipped"))
    rules.set_values(db, {"max_duration_seconds": 600}, channel=channel)  # a channel override applies to the next video
    details["long2"] = meta("long2", 181)
    assert detection.discover(db, channel, "long2").status == VideoStatus.ACCEPTED


def test_only_shorts_are_processed(db, channel, details):
    details["regular1"] = meta("regular1", 95)  # short enough, but a normal video, not a Short
    video = detection.discover(db, channel, "regular1")
    assert (video.status, video.skip_reason) == (VideoStatus.SKIPPED, SkipReason.NOT_SHORT) and db.scalar(select(Job)) is None
    assert detection.discover(db, channel, "short1").status == VideoStatus.ACCEPTED
    rules.set_values(db, {"shorts_only": False})  # switched off: duration alone decides
    assert detection.discover(db, channel, "regular2").status == VideoStatus.ACCEPTED


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
    monkeypatch.setattr(youtube, "video_details", lambda video_id: meta(video_id))
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
    rules.set_values(db, {"videos_per_channel_per_day": 2})
    statuses = [detection.discover(db, channel, v) for v in ("a", "b", "c")]
    assert [v.status for v in statuses] == [VideoStatus.ACCEPTED, VideoStatus.ACCEPTED, VideoStatus.SKIPPED]
    held = statuses[2]
    assert held.skip_reason == SkipReason.CHANNEL_CAP
    job = detection.process_anyway(db, held)
    assert held.status == VideoStatus.ACCEPTED and held.forced and held.skip_reason is None and job.status == JobStatus.FETCHED
    with pytest.raises(ValueError):
        detection.process_anyway(db, held)


def test_account_cap_counts_published_and_pending(db, channel, tiktok_account, details):
    tiktok_account.daily_cap = None
    rules.set_values(db, {"uploads_per_tiktok_account_per_day": 2, "videos_per_channel_per_day": 10})
    first = detection.discover(db, channel, "a")
    db.scalar(select(Job).where(Job.video_id == first.id)).posted_at = utcnow()
    detection.discover(db, channel, "b")  # still on its way: counts as well
    blocked = detection.discover(db, channel, "c")
    assert blocked.skip_reason == SkipReason.ACCOUNT_CAP and "@northbound" in blocked.rejection_reason
    tiktok_account.daily_cap = 5  # the account's own cap wins over the global rule
    assert detection.discover(db, channel, "d").status == VideoStatus.ACCEPTED


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
def test_add_channel(client, auth, db, tiktok_account):
    respx.get("https://www.youtube.com/@northbound").mock(return_value=httpx.Response(200, text=PAGE))
    card = client.post("/api/channels/resolve", headers=auth, json={"query": "@northbound"}).json()
    assert card["display_name"] == "Northbound & Co" and card["already_added"] is False
    body = {"query": "@northbound", "default_tiktok_account_id": tiktok_account.id}
    r = client.post("/api/channels", headers=auth, json=body)
    assert r.status_code == 201 and r.json()["default_tiktok_account"]["username"] == "northbound"
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


def test_review_published_and_skipped_screens(client, auth, db, channel, tiktok_account, details):
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
    assert [(v["youtube_video_id"], v["skip_reason"]) for v in skipped] == [("long", "too_long")]
    dispatch.sent.clear()
    forced = client.post(f"/api/videos/{skipped[0]['id']}/process", headers=auth).json()
    assert forced["status"] == "fetched" and [name for name, _ in dispatch.sent] == ["process_video", "rewrite_job"]
    assert client.get("/api/videos?status=skipped", headers=auth).json() == []
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert nav["channels"] == 1 and nav["review_jobs"] == 0 and nav["skipped_videos"] == 0


def test_video_file_needs_a_media_token(client, auth, db, tiktok_account):
    import os

    from app.services.storage import get_storage

    path = os.path.join(get_storage().root, "videos", "9.mp4")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x00" * 64)
    video = Video(youtube_video_id="f", status=VideoStatus.ACCEPTED, rendered_file_path="videos/9.mp4")
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
