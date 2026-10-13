import respx

from app.models import Job, JobStatus, Video, VideoStatus, utcnow
from app.services import dispatch
from tests.helpers import ANTHROPIC, claude


def test_dashboard_and_report_empty(client, auth):
    summary = client.get("/api/dashboard/summary", headers=auth).json()
    assert [k["key"] for k in summary["kpis"]] == ["fetched", "published", "pending", "failed"]
    assert client.get("/api/dashboard/performance?days=30", headers=auth).json()["values"] == [0] * 30
    report = client.get("/api/reports/daily", headers=auth).json()
    assert report["uploaded"] == 0 and len(report["hourly"]) == 12
    assert client.get("/api/reports/daily.csv", headers=auth).text.startswith("date,account")
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert "monthly_quota" not in nav and "monthly_jobs" not in nav and nav["failed_jobs"] == 0
    assert report["timezone"] == "Asia/Karachi" and summary["timezone"] == "Asia/Karachi"


def test_dashboard_counts(client, auth, db, buffer_account):
    video = Video(user_id=1, youtube_video_id="1", status=VideoStatus.ACCEPTED)
    rejected = Video(user_id=1, youtube_video_id="2", status=VideoStatus.SKIPPED, rejection_reason="Duration 70.0s is not under 60s")
    db.add_all([video, rejected])
    db.flush()
    db.add(Job(video_id=video.id, buffer_channel_id=buffer_account.id, status=JobStatus.POSTED, posted_at=utcnow()))
    db.commit()
    summary = client.get("/api/dashboard/summary", headers=auth).json()
    kpis = {k["key"]: k["value"] for k in summary["kpis"]}
    assert kpis == {"fetched": 2, "published": 1, "pending": 0, "failed": 0}
    assert summary["rejections"]["items"][0]["rejection_reason"].startswith("Duration")
    assert summary["accounts"] == [{"id": buffer_account.id, "name": "northbound", "service": "tiktok", "initials": "NO", "enabled": True, "posts_today": 1, "lifetime_posts": 1}]
    report = client.get("/api/reports/daily", headers=auth).json()
    assert report["accounts"][0]["posts_today"] == 1 and report["active_accounts"] == 1 and report["lifetime_uploads"] == 1
    assert "northbound,on,1,100,0,1" in client.get("/api/reports/daily.csv", headers=auth).text
    assert "automations_paused" not in summary and summary["rejections"]["max_duration_seconds"] == 180
    assert "detected_language" not in summary["rejections"]["items"][0]
    assert "source" not in summary["rejections"]["items"][0]
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert nav["buffer_connected"] is True and nav["buffer_accounts"] == 1 and "tiktok_accounts" not in nav and "unacknowledged_violations" not in nav


@respx.mock
def test_prompt_studio_flow(client, auth):
    r = client.post("/api/prompts", headers=auth, json={"name": "Travel v3", "caption_prompt": "Rewrite {caption}"})
    prompt = r.json()
    assert prompt["is_default"] is False  # the seeded "Default rewrite" template stays default
    assert client.post(f"/api/prompts/{prompt['id']}/default", headers=auth).json()["is_default"] is True
    assert [p["name"] for p in client.get("/api/prompts", headers=auth).json() if p["is_default"]] == ["Travel v3"]
    prompt["caption_prompt"] = "Rewrite {caption} for TikTok"
    assert client.put(f"/api/prompts/{prompt['id']}", headers=auth, json=prompt).status_code == 200
    versions = client.get(f"/api/prompts/{prompt['id']}/versions", headers=auth).json()
    assert [v["version"] for v in versions] == [2, 1]
    restored = client.post(f"/api/prompts/{prompt['id']}/versions/1/restore", headers=auth).json()
    assert restored["caption_prompt"] == "Rewrite {caption}"

    respx.post(ANTHROPIC).mock(return_value=claude("Crete gave us this."))
    out = client.post("/api/prompts/test", headers=auth, json={"caption_prompt": "Rewrite {caption}", "caption": "We found a beach"}).json()
    assert out["caption"] == "Crete gave us this."
    assert client.delete(f"/api/prompts/{prompt['id']}", headers=auth).status_code == 400  # default can't be deleted


def test_job_approve_edit_cancel(client, auth, db, buffer_account):
    video = Video(user_id=1, youtube_video_id="1", status=VideoStatus.ACCEPTED, original_caption="Original")
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, buffer_channel_id=buffer_account.id, status=JobStatus.AWAITING_APPROVAL, approval_required=True)
    db.add(job)
    db.commit()

    r = client.patch(f"/api/jobs/{job.id}", headers=auth, json={"rewritten_caption": "Edited caption", "rewritten_tags": ["#crete", "travel"]})
    assert r.json()["rewritten_tags"] == ["crete", "travel"]
    r = client.post(f"/api/jobs/{job.id}/approve", headers=auth)
    assert r.json()["status"] == JobStatus.READY and dispatch.sent[-1][0] == "upload_job"
    assert client.post(f"/api/jobs/{job.id}/approve", headers=auth).status_code == 409

    listing = client.get("/api/jobs?status=pending&q=northbound", headers=auth).json()
    assert listing["total"] == 1
    assert client.post(f"/api/jobs/{job.id}/cancel", headers=auth).json()["status"] == JobStatus.CANCELLED
    detail = client.get(f"/api/jobs/{job.id}", headers=auth).json()
    assert [e["status"] for e in detail["events"]] == [JobStatus.READY, JobStatus.CANCELLED]


def test_tiktok_and_compliance_are_gone(client, auth):
    for method, path in [("get", "/api/tiktok-accounts"), ("get", "/api/tiktok/oauth/start"), ("get", "/api/audit"), ("get", "/api/settings/audit"),
                         ("get", "/api/settings/policy"), ("get", "/api/publishing/route"), ("post", "/api/jobs/process-next")]:
        assert getattr(client, method)(path, headers=auth).status_code in (404, 405), path
    assert {i["key"] for i in client.get("/api/settings/integrations", headers=auth).json()} == {"llm", "storage", "ffmpeg", "ytdlp"}
    assert [c["group"] for c in client.get("/api/credentials", headers=auth).json()] == ["youtube", "smtp"]
    keys = {d["key"] for d in client.get("/api/settings/rules", headers=auth).json()["definitions"]}
    assert not {"uploads_per_tiktok_account_per_day", "publish_mode"} & keys and "cap_reset_timezone" in keys
    assert set(client.get("/api/settings/notifications", headers=auth).json()) == {"webhook_url", "email", "notify_failures", "notify_tokens"}


def test_logs_filter_and_csv(client, auth, db):
    from app.services import activity

    activity.record(db, "Publisher", "Video published to @northbound", event="posted")
    db.commit()
    logs = client.get("/api/logs?service=Publisher", headers=auth).json()
    assert logs["total"] == 1 and "Publisher" in logs["services"]
    assert "Video published" in client.get("/api/logs.csv", headers=auth).text


def test_instagram_is_gone(client, auth, db, buffer_account):
    for method, path in [("get", "/api/sources"), ("post", "/api/sources/bulk"), ("post", "/api/runs"), ("get", "/api/fetch-runs"),
                         ("get", "/api/fetched-videos"), ("get", "/api/instaloader/status"), ("get", "/api/instagram/oauth/start")]:
        assert getattr(client, method)(path, headers=auth).status_code == 404, path
    assert "{source}" not in client.get("/api/prompts/meta", headers=auth).json()["variables"]

    video = Video(user_id=1, youtube_video_id="1", status=VideoStatus.ACCEPTED, original_caption="Goa sunset")
    db.add(video)
    db.flush()
    db.add(Job(video_id=video.id, buffer_channel_id=buffer_account.id, status=JobStatus.READY, rewritten_title="Goa"))
    db.commit()
    listing = client.get("/api/jobs?q=sunset", headers=auth).json()
    assert listing["total"] == 1 and "source" not in listing["items"][0] and "source" not in listing["items"][0]["video"]
    assert client.get("/api/jobs?q=northbound", headers=auth).json()["total"] == 1  # searchable by the account it goes to


def test_live_status_lists_every_stage(client, auth, db):
    def add(youtube_id, status, **fields):
        video = Video(user_id=1, youtube_video_id=youtube_id, status=VideoStatus.ACCEPTED, original_title=f"Title {youtube_id}", **{k: v for k, v in fields.items() if k in ("source_file_path", "rendered_file_path")})
        db.add(video)
        db.flush()
        job = Job(video_id=video.id, status=status, **{k: v for k, v in fields.items() if k in ("progress", "posted_at", "attempts", "error")})
        db.add(job)
        return job

    add("a", JobStatus.FETCHED)
    add("b", JobStatus.DOWNLOADING, progress=40)
    add("c", JobStatus.RENDERING, progress=75, source_file_path="source/c.mp4")
    add("d", JobStatus.READY, source_file_path="source/d.mp4", rendered_file_path="videos/d.mp4")
    add("e", JobStatus.POSTED, source_file_path="source/e.mp4", rendered_file_path="videos/e.mp4", posted_at=utcnow())
    add("f", JobStatus.FAILED, error="Download failed after 3 attempts: The video is private")
    db.commit()
    status = client.get("/api/pipeline/status", headers=auth).json()
    stages = {s["key"]: s for s in status["stages"]}
    assert [s["key"] for s in status["stages"]] == ["waiting", "downloading", "editing", "caption", "review", "upload_wait", "uploading", "scheduled"]
    assert stages["waiting"]["items"][0]["title"] == "Title a" and stages["downloading"]["items"][0]["progress"] == 40
    assert stages["editing"]["items"][0]["progress"] == 75 and stages["upload_wait"]["total"] == 1 and stages["review"]["total"] == 0
    assert status["today"] == {"total": 6, "downloaded": 3, "download_left": 2, "edited": 2, "edit_left": 1, "uploaded": 1, "upload_left": 1, "failed": 1}
    assert client.get("/api/pipeline/status?mode=podcasts", headers=auth).json()["today"]["total"] == 0  # each workspace has its own
