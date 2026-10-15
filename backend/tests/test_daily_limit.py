"""The daily limit: once it is used up, usable uploads are recorded under Not Processed, not edited."""

from sqlalchemy import func, select

from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import Job, SkipReason, Video, VideoStatus, utcnow
from app.services import detection, limits


def _upload(db, channel, monkeypatch, vid: str, seconds: float = 30) -> Video:
    monkeypatch.setattr(youtube, "video_details", lambda _: VideoMeta(vid, title=f"Title {vid}", duration_seconds=seconds, published_at=utcnow()))
    video = detection.discover(db, channel, vid)
    db.commit()
    return video


def test_the_limit_matches_the_accounts_then_holds_videos(client, auth, db, channel, buffer_account, monkeypatch):
    buffer_account.daily_limit = 2  # one switched-on account posting 2 a day: 2 videos a day are taken
    db.commit()
    today = client.get("/api/limits/daily", headers=auth).json()
    assert (today["limit"], today["used"], today["source"], today["accounts"], today["reached"]) == (2, 0, "accounts", 1, False)

    first, second = _upload(db, channel, monkeypatch, "lim1"), _upload(db, channel, monkeypatch, "lim2")
    assert first.status == second.status == VideoStatus.ACCEPTED
    third = _upload(db, channel, monkeypatch, "lim3")
    assert third.status == VideoStatus.SKIPPED and third.skip_reason == SkipReason.DAILY_LIMIT and "2 of 2" in third.rejection_reason
    assert db.scalar(select(func.count(Job.id)).where(Job.video_id == third.id)) == 0  # recorded, not downloaded or edited
    monkeypatch.setattr(youtube, "is_short", lambda _: False)
    long_one = _upload(db, channel, monkeypatch, "lim4", seconds=900)
    assert long_one.skip_reason == SkipReason.LONG_FORM  # a filter still comes first: it stays under Skipped

    # Not Processed lists the usable ones held by a limit; Skipped keeps the rest.
    held = client.get("/api/videos?status=skipped&kind=limit", headers=auth).json()
    filtered = client.get("/api/videos?status=skipped&kind=filtered", headers=auth).json()
    assert [v["id"] for v in held] == [third.id] and [v["id"] for v in filtered] == [long_one.id]
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert (nav["not_processed_videos"], nav["skipped_videos"]) == (1, 1)
    assert client.get("/api/limits/daily", headers=auth).json()["reached"] is True

    # Process now pushes it through anyway; it counts against today.
    assert client.post(f"/api/videos/{third.id}/process", headers=auth).status_code == 200
    db.expire_all()
    assert db.get(Video, third.id).status == VideoStatus.ACCEPTED and limits.used_today(db, 1, "shorts", "Asia/Karachi") == 3

    # Set by hand, the number of the rule applies instead of the accounts.
    assert client.put("/api/settings/rules", headers=auth, json={"values": {"daily_limit_mode": "manual", "daily_limit": 5}}).status_code == 200
    today = client.get("/api/limits/daily", headers=auth).json()
    assert (today["limit"], today["used"], today["source"]) == (5, 3, "manual")
    # The daily limit has room, but this channel has had its 3 for today: also held under Not Processed.
    fifth = _upload(db, channel, monkeypatch, "lim5")
    assert fifth.skip_reason == SkipReason.CHANNEL_CAP
    assert fifth.id in [v["id"] for v in client.get("/api/videos?status=skipped&kind=limit", headers=auth).json()]


def test_with_no_account_switched_on_the_manual_number_applies(client, auth, db, channel, buffer_account):
    buffer_account.enabled = False
    db.commit()
    today = client.get("/api/limits/daily", headers=auth).json()
    assert (today["limit"], today["source"], today["set_to_match"]) == (15, "manual", True)
    assert client.get("/api/limits/daily?mode=podcasts", headers=auth).json()["limit"] == 5
