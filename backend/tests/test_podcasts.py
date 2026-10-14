from datetime import timedelta

import pytest
import respx
from sqlalchemy import select

from tests.conftest import ME
from app.integrations import youtube
from app.integrations.youtube import VideoMeta
from app.models import BufferAccount, BufferChannel, Channel, Job, JobStatus, Mode, Video, VideoStatus, utcnow
from app.security import encrypt
from app.services import buffer, detection, dispatch, pipeline, podcasts, rules
from tests.helpers import ANTHROPIC, claude

POD = "UC" + "p" * 22
# A 20-minute talk: one caption line every 5 seconds.
SEGMENTS = [(float(t), f"line at {t}") for t in range(0, 1200, 5)]


@pytest.fixture
def podcast_account(db):
    """A Buffer account switched on in the Podcasts workspace only."""
    if not db.get(BufferAccount, 1):
        db.add(BufferAccount(user_id=1, api_key_enc=encrypt("buf-key-0123456789abcdefghij")))
    account = BufferChannel(user_id=1, mode=Mode.PODCASTS, buffer_id="ch-podclips", name="podclips", service="tiktok", enabled=True, daily_limit=3, times=["09:00"])
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def podcast_channel(db):
    row = Channel(youtube_channel_id=POD, user_id=1, mode=Mode.PODCASTS, display_name="Deep Talks", active=True, monitoring_since=utcnow() - timedelta(days=1))
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def source(monkeypatch):
    """YouTube for a podcast channel: every video is a 20-minute talk with subtitles unless set otherwise."""
    known: dict[str, VideoMeta] = {}

    def details(video_id):
        return known.get(video_id) or VideoMeta(video_id, title="How we built it", description="A long talk", tags=["talk"], duration_seconds=1200, published_at=utcnow(), channel_id=POD)

    monkeypatch.setattr(youtube, "video_details", details)
    monkeypatch.setattr(youtube, "transcript", lambda video_id: SEGMENTS)
    return known


def test_rules_are_separate_for_each_workspace(db, client, auth):
    assert rules.global_values(db, Mode.PODCASTS, 1)["fallback_hashtags"].startswith("podcast") and rules.global_values(db, user_id=1)["fallback_hashtags"].endswith("shorts")
    rules.set_values(db, {"hashtag_count": 4, "clips_per_video": 5}, mode=Mode.PODCASTS, user=ME)
    rules.set_values(db, {"cap_reset_timezone": "UTC"}, user=ME)  # plumbing is shared: Podcasts reads it from Shorts
    db.commit()
    pod, shorts = rules.global_values(db, Mode.PODCASTS, 1), rules.global_values(db, user_id=1)
    assert (pod["hashtag_count"], pod["clips_per_video"], pod["cap_reset_timezone"]) == (4, 5, "UTC")
    assert shorts["hashtag_count"] == 8 and "clips_per_video" not in shorts and "max_duration_seconds" not in pod
    for bad in ({"clips_per_video": 0}, {"framing": "zoom"}, {"clip_min_seconds": 90}, {"max_duration_seconds": 100}):
        with pytest.raises(ValueError):
            rules.set_values(db, bad, mode=Mode.PODCASTS, user=ME)

    r = client.get("/api/settings/rules?mode=podcasts", headers=auth).json()
    assert r["values"]["clips_per_video"] == 5 and "clip_max_seconds" in {d["key"] for d in r["definitions"]} and "framing" not in {d["key"] for d in r["definitions"]}
    assert "clips_per_video" not in client.get("/api/settings/rules", headers=auth).json()["values"]
    assert client.put("/api/settings/rules?mode=podcasts", headers=auth, json={"values": {"clip_max_seconds": 90}}).json()["values"]["clip_max_seconds"] == 90
    assert [c["key"] for c in client.get("/api/settings/rules/history?mode=podcasts", headers=auth).json()][:1] == ["clip_max_seconds"]
    assert all(c["key"] != "clip_max_seconds" for c in client.get("/api/settings/rules/history", headers=auth).json())
    assert client.get("/api/settings/rules?mode=radio", headers=auth).status_code == 422


def test_even_moments_and_validation():
    spread = podcasts.even_moments("Talk", 1200, 3, 60)
    assert [(m.start, m.end) for m in spread] == [(270.0, 330.0), (570.0, 630.0), (870.0, 930.0)]
    raw = [{"start": 100, "end": 400, "title": "too long"}, {"start": 120, "end": 150, "title": "overlaps"}, {"start": 1190, "end": 1300}, {"start": "x"}, {"start": 500, "end": 505}]
    kept = podcasts._valid(raw, 1200, 5, 30, 60)
    # too long is cut to 60s; the overlap and the broken item are dropped; the end of the video and the too-short one are stretched to 30s
    assert [(m.start, m.end) for m in kept] == [(100.0, 160.0), (500.0, 530.0), (1170.0, 1200.0)]
    assert podcasts.transcript_lines([(0, "a"), (5, "b"), (21, "c"), (30, " ")]) == [(0, "a b"), (21, "c")]


@respx.mock
def test_ai_picks_the_moments(db):
    route = respx.post(ANTHROPIC).mock(return_value=claude('Sure: [{"start": 60, "end": 110, "title": "The first customer"}, {"start": 600, "end": 655, "title": "Why we almost quit"}]'))
    moments, how = podcasts.pick_moments("How we built it", 1200, SEGMENTS, count=3, shortest=30, longest=60)
    assert how == "ai" and "[60] line at 60" in route.calls[0].request.content.decode()
    assert [(m.start, m.end, m.title) for m in moments[:1]] == [(60.0, 110.0, "The first customer")]
    assert len(moments) == 3 and "line at 65" in moments[0].text  # two from the model, one evenly placed to make three
    # no subtitles, or a model that fails: clips are spread evenly, and the reason is reported
    assert podcasts.pick_moments("T", 1200, [], count=3, shortest=30, longest=60)[1] == "this video has no subtitles to read"
    respx.post(ANTHROPIC).mock(return_value=claude("I cannot do that"))
    fallback, why = podcasts.pick_moments("T", 1200, SEGMENTS, count=3, shortest=30, longest=60)
    assert "AI model failed" in why and len(fallback) == 3


def test_a_podcast_channel_takes_long_videos_only(db, podcast_channel, source):
    source["short1"] = VideoMeta("short1", title="A short", duration_seconds=45, published_at=utcnow(), channel_id=POD)
    short = detection.discover(db, podcast_channel, "short1")
    assert (short.status, short.skip_reason) == (VideoStatus.SKIPPED, "not_a_podcast") and "under the 300s minimum" in short.rejection_reason
    talk = detection.discover(db, podcast_channel, "talk1")
    job = db.scalar(select(Job).where(Job.video_id == talk.id))
    assert talk.status == VideoStatus.ACCEPTED and talk.mode == Mode.PODCASTS and talk.is_podcast_source
    assert job.status == JobStatus.FETCHED and job.buffer_channel_id is None and job.error is None and job.caption_status == "done"
    rules.set_values(db, {"videos_per_channel_per_day": 1}, mode=Mode.PODCASTS, user=ME)
    assert detection.discover(db, podcast_channel, "talk2").skip_reason == "skipped_channel_cap"


@respx.mock
def test_podcast_becomes_clips_that_travel_the_normal_pipeline(db, podcast_channel, podcast_account, source, fake_media, template):
    respx.post(ANTHROPIC).mock(return_value=claude('[{"start": 60, "end": 110, "title": "The first customer"}, {"start": 300, "end": 345, "title": "Hiring"}, {"start": 600, "end": 655, "title": "Why we almost quit"}]'))
    talk = detection.discover(db, podcast_channel, "talk1")
    parent = db.scalar(select(Job).where(Job.video_id == talk.id))
    assert pipeline.process_video(db, parent.id) == JobStatus.CLIPPED
    db.commit()

    clips = db.scalars(select(Video).where(Video.parent_id == talk.id).order_by(Video.clip_start)).all()
    assert [(c.clip_start, c.clip_end, c.original_title) for c in clips] == [(60.0, 110.0, "The first customer"), (300.0, 345.0, "Hiring"), (600.0, 655.0, "Why we almost quit")]
    assert all(c.youtube_video_id is None and c.mode == Mode.PODCASTS and "line at" in c.original_caption for c in clips)
    assert clips[0].permalink == "https://www.youtube.com/watch?v=talk1&t=60s"
    jobs = [db.scalar(select(Job).where(Job.video_id == c.id)) for c in clips]
    assert {buffer.choose(db, j)[0].id for j in jobs} == {podcast_account.id}  # never the Shorts account
    # the podcast itself is finished and is never uploaded
    assert pipeline.upload_job(db, parent.id) == "skipped"
    due = pipeline.scheduler_tick(db)
    assert sorted(due["process"]) == sorted(j.id for j in jobs) and parent.id not in due["process"]

    respx.post(ANTHROPIC).mock(return_value=claude("text"))
    assert pipeline.process_video(db, jobs[0].id) == JobStatus.REWRITING
    assert fake_media[-1] == {"speed": 1.0, "flip": False, "keep_audio": True, "aspect": "9:16"}  # the Podcasts rules, not the Shorts ones
    assert pipeline.rewrite_job(db, jobs[0].id) == JobStatus.AWAITING_APPROVAL
    assert pipeline.rewrite_job(db, parent.id) == JobStatus.CLIPPED and db.get(Job, parent.id).status == JobStatus.CLIPPED


def test_workspaces_do_not_see_each_other(client, auth, db, channel, buffer_account, podcast_channel, podcast_account, source):
    talk = detection.discover(db, podcast_channel, "talk1")
    db.commit()
    names = lambda mode: [c["display_name"] for c in client.get(f"/api/channels{mode}", headers=auth).json()["items"]]  # noqa: E731
    assert names("") == ["Northbound"] and names("?mode=podcasts") == ["Deep Talks"]
    accounts = lambda mode: [a["name"] for a in client.get(f"/api/buffer{mode}", headers=auth).json()["channels"] if a["enabled"]]  # noqa: E731
    assert accounts("") == ["northbound"] and accounts("?mode=podcasts") == ["podclips"]
    assert client.get("/api/jobs", headers=auth).json()["total"] == 0 and client.get("/api/jobs?mode=podcasts", headers=auth).json()["total"] == 1
    shorts, pod = client.get("/api/dashboard/summary", headers=auth).json(), client.get("/api/dashboard/summary?mode=podcasts", headers=auth).json()
    assert shorts["kpis"][0]["value"] == 0 and pod["kpis"][0]["value"] == 1 and pod["kpis"][0]["label"] == "Podcasts detected"
    assert [a["name"] for a in pod["accounts"]] == ["podclips"] and pod["rejections"]["min_source_duration_seconds"] == 300
    nav = client.get("/api/dashboard/nav?mode=podcasts", headers=auth).json()
    assert (nav["channels"], nav["buffer_accounts"]) == (1, 1) and client.get("/api/dashboard/nav", headers=auth).json()["channels"] == 1
    assert client.get("/api/reports/daily?mode=podcasts", headers=auth).json()["accepted"] == 1

    # an account cannot be used from the other workspace
    clip_job = db.scalar(select(Job).where(Job.video_id == talk.id))
    assert client.patch(f"/api/jobs/{clip_job.id}", headers=auth, json={"buffer_channel_id": buffer_account.id}).status_code == 404
    assert client.patch(f"/api/jobs/{clip_job.id}", headers=auth, json={"buffer_channel_id": podcast_account.id}).status_code == 200
    with respx.mock:
        respx.get(f"https://www.youtube.com/channel/{POD}").respond(200, text=f'<link rel="canonical" href="https://www.youtube.com/channel/{POD}"><meta property="og:title" content="Deep Talks">')
        r = client.post("/api/channels", headers=auth, json={"query": POD})
        assert r.status_code == 409 and "Podcasts workspace" in r.json()["detail"]
    assert talk.channel_id == podcast_channel.id
    assert dispatch.sent == []



def test_only_the_pieces_a_clip_needs_are_fetched():
    from app.services import sources

    playlist = "#EXTM3U\n#EXT-X-MAP:URI=\"init.mp4\"\n" + "".join(f"#EXTINF:5.0,\nseg{i}.ts\n" for i in range(20)) + "#EXT-X-ENDLIST"
    init, pieces = sources.segments_for(playlist, 12, 31)
    assert init == "init.mp4" and pieces == [(10.0, "seg2.ts"), (15.0, "seg3.ts"), (20.0, "seg4.ts"), (25.0, "seg5.ts"), (30.0, "seg6.ts")]
    assert sources.segments_for("#EXTM3U\n#EXTINF:5,\na.ts\n", 50, 60) == (None, [])
