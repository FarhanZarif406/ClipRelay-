from datetime import timedelta

import respx

from app.models import Job, JobStatus, TikTokAccount, Video, VideoStatus, Violation, utcnow
from app.services import dispatch
from tests.helpers import ANTHROPIC, claude


def test_dashboard_and_report_empty(client, auth):
    summary = client.get("/api/dashboard/summary", headers=auth).json()
    assert [k["key"] for k in summary["kpis"]] == ["fetched", "published", "pending", "failed", "removed"]
    assert client.get("/api/dashboard/performance?days=30", headers=auth).json()["values"] == [0] * 30
    report = client.get("/api/reports/daily", headers=auth).json()
    assert report["uploaded"] == 0 and len(report["hourly"]) == 12
    assert client.get("/api/reports/daily.csv", headers=auth).text.startswith("date,account")
    nav = client.get("/api/dashboard/nav", headers=auth).json()
    assert nav["monthly_quota"] == 1000


def test_dashboard_counts(client, auth, db, source, tiktok_account):
    video = Video(source_id=source.id, ig_media_id="1", status=VideoStatus.ACCEPTED)
    rejected = Video(source_id=source.id, ig_media_id="2", status=VideoStatus.REJECTED, rejection_reason="Duration 70.0s is not under 60s")
    db.add_all([video, rejected])
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=tiktok_account.id, status=JobStatus.VIOLATED, posted_at=utcnow())
    db.add(job)
    db.flush()
    db.add(Violation(job_id=job.id, tiktok_account_id=tiktok_account.id, reason="removed"))
    db.commit()
    summary = client.get("/api/dashboard/summary", headers=auth).json()
    kpis = {k["key"]: k["value"] for k in summary["kpis"]}
    assert kpis == {"fetched": 2, "published": 1, "pending": 0, "failed": 0, "removed": 1}
    assert summary["rejections"]["items"][0]["rejection_reason"].startswith("Duration")
    assert summary["accounts"][0]["posts_today"] == 1
    assert client.get("/api/dashboard/nav", headers=auth).json()["unacknowledged_violations"] == 1


def test_sources_crud_and_bulk(client, auth, db, source, tiktok_account):
    source.is_active = False
    db.commit()
    r = client.post("/api/sources/bulk", headers=auth, json={"entries": ["@slowtravel", "@someone_else", "bad name!"]})
    body = r.json()
    assert body["activated"] == ["slowtravel"]
    assert body["not_authorized"] == ["@someone_else"] and body["invalid"] == ["bad name!"]
    assert body["authorize_url"].startswith("https://www.instagram.com/oauth/authorize")

    r = client.patch(f"/api/sources/{source.id}", headers=auth, json={"refresh_interval_minutes": 15, "approval_mode": "manual"})
    assert r.json()["refresh_interval_minutes"] == 15 and r.json()["approval_mode"] == "manual"
    assert client.patch(f"/api/sources/{source.id}", headers=auth, json={"refresh_interval_minutes": 1}).status_code == 422

    listing = client.get("/api/sources?q=slow", headers=auth).json()
    assert listing["total"] == 1 and listing["items"][0]["tiktok_accounts"][0]["username"] == "northbound"

    assert client.post(f"/api/sources/{source.id}/run", headers=auth).status_code == 202
    assert dispatch.sent[-1] == ("run_source", (source.id, True))

    assert client.post("/api/sources/bulk-update", headers=auth, json={"ids": [source.id], "action": "pause"}).json() == {"updated": 1}
    assert client.get("/api/sources?status=paused", headers=auth).json()["total"] == 1


def test_oauth_start_urls(client, auth):
    ig = client.get("/api/instagram/oauth/start", headers=auth).json()["url"]
    assert "client_id=ig-app" in ig and "redirect_uri=http%3A%2F%2Fapi.test%2Fapi%2Finstagram%2Foauth%2Fcallback" in ig
    tt = client.get("/api/tiktok/oauth/start", headers=auth).json()["url"]
    assert tt.startswith("https://www.tiktok.com/v2/auth/authorize/") and "client_key=tt-key" in tt


def test_oauth_callback_rejects_bad_state(client):
    r = client.get("/api/tiktok/oauth/callback?code=x&state=forged", follow_redirects=False)
    assert r.status_code == 307 and "error=" in r.headers["location"]


def test_tiktok_disconnect_cancels_pending(client, auth, db, source, tiktok_account):
    video = Video(source_id=source.id, ig_media_id="1", status=VideoStatus.ACCEPTED)
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=tiktok_account.id, status=JobStatus.READY)
    db.add(job)
    db.commit()
    with respx.mock:
        respx.post(url__startswith="https://open.tiktokapis.com/v2/oauth/revoke/").respond(200, json={})
        assert client.delete(f"/api/tiktok-accounts/{tiktok_account.id}", headers=auth).status_code == 204
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.CANCELLED
    assert db.get(TikTokAccount, tiktok_account.id).access_token_enc is None
    assert client.get("/api/tiktok-accounts", headers=auth).json()["items"] == []


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


def test_job_approve_edit_cancel(client, auth, db, source, tiktok_account):
    video = Video(source_id=source.id, ig_media_id="1", status=VideoStatus.ACCEPTED, original_caption="Original")
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=tiktok_account.id, status=JobStatus.AWAITING_APPROVAL, approval_required=True)
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


def test_settings_validation(client, auth):
    assert client.put("/api/settings/policy", headers=auth, json={"max_duration_sec": 90}).status_code == 422
    assert client.put("/api/settings/policy", headers=auth, json={"timezone": "Mars/Base"}).status_code == 422
    r = client.put("/api/settings/policy", headers=auth, json={"active_window_start": "09:00", "hourly_cap": 6, "active_days": [0, 1, 2]})
    assert r.json()["hourly_cap"] == 6 and r.json()["active_days"] == [0, 1, 2]
    r = client.put("/api/settings/audit", headers=auth, json={"check_hours": [24, 1, 6]})
    assert r.json()["check_hours"] == [1, 6, 24]
    assert {i["key"] for i in client.get("/api/settings/integrations", headers=auth).json()} >= {"llm", "tiktok", "instagram", "storage"}


def test_audit_and_violation_ack(client, auth, db, source, tiktok_account):
    video = Video(source_id=source.id, ig_media_id="1", status=VideoStatus.ACCEPTED, original_title="Beach")
    db.add(video)
    db.flush()
    job = Job(video_id=video.id, tiktok_account_id=tiktok_account.id, status=JobStatus.MONITORING, posted_at=utcnow() - timedelta(hours=7))
    db.add(job)
    db.flush()
    violation = Violation(job_id=job.id, tiktok_account_id=tiktok_account.id, reason="spam", removal_status="manual_required")
    db.add(violation)
    db.commit()
    audit = client.get("/api/audit", headers=auth).json()
    item = audit["items"][0]
    assert item["display_status"] == "Checking" and 16 < item["hours_left"] < 18
    assert [c["done"] for c in item["checkpoints"]] == [True, True, True, False, False]
    r = client.post(f"/api/violations/{violation.id}/ack", headers=auth).json()
    assert r["acknowledged"] and r["removal_status"] == "removed_manually"
    health = client.get(f"/api/tiktok-accounts/{tiktok_account.id}/health", headers=auth).json()
    assert health["violation_count"] == 1


def test_logs_filter_and_csv(client, auth):
    client.post("/api/runs", headers=auth)
    logs = client.get("/api/logs?service=Scheduler", headers=auth).json()
    assert logs["total"] == 1 and "Scheduler" in logs["services"]
    assert "Automation started" in client.get("/api/logs.csv", headers=auth).text
