"""Videos are edited on the member's own PC (PC Helper) first; when it is off they move on to Google Cloud Run."""

import io
import json
import os
from datetime import timedelta

import httpx
import respx

from app.models import EditorDevice, Job, JobStatus, utcnow
from app.services import cloud_editor, editors, pipeline, push
from tests.test_pipeline import _make_job  # noqa: E402

FAKE_KEY = {"type": "service_account", "client_email": "editor@demo.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n", "project_id": "demo"}


def _connect(client, auth, name="Office PC") -> dict:
    code = client.post("/api/helper/code", headers=auth).json()["code"]
    r = client.post("/api/helper/connect", json={"code": code, "name": name, "platform": "windows", "version": "1.0.0"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mp4(seconds=1) -> bytes:
    import subprocess
    import tempfile

    from app.services import media

    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    subprocess.run([media.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=64x112:d={seconds}", "-pix_fmt", "yuv420p", path], check=True)
    with open(path, "rb") as fh:
        data = fh.read()
    os.remove(path)
    return data


def test_a_pc_connects_with_a_short_code_and_its_key_is_kept_secret(client, auth, db):
    r = client.post("/api/helper/connect", json={"code": "AAA-BBB", "name": "PC"})
    assert r.status_code == 400 and "wrong or has expired" in r.json()["detail"]
    helper = _connect(client, auth)
    assert client.post("/api/helper/beat", headers=helper, json={"version": "1.0.0"}).json()["ok"] is True
    device = db.scalar(db.query(EditorDevice).statement)
    assert device.token_hash and not device.token_hash.startswith("crh_")  # only a hash is stored
    page = client.get("/api/helper", headers=auth).json()
    assert [d["name"] for d in page["devices"]] == ["Office PC"] and page["devices"][0]["online"] is True
    assert "token" not in json.dumps(page)

    # A code works once.
    code = client.post("/api/helper/code", headers=auth).json()["code"]
    assert client.post("/api/helper/connect", json={"code": code}).status_code == 200
    assert client.post("/api/helper/connect", json={"code": code}).status_code == 400

    assert client.delete(f"/api/helper/devices/{device.id}", headers=auth).status_code == 204
    assert client.post("/api/helper/beat", headers=helper, json={}).status_code == 401  # its key stops working


def test_the_pc_downloads_and_edits_and_sends_back_only_the_finished_video(client, auth, db, fake_media):
    helper = _connect(client, auth)
    job = _make_job(db, rendered=False)
    second = _make_job(db, rendered=False, youtube_video_id="v2")

    # The PC is on: the server neither downloads nor edits it, it waits for the PC.
    assert pipeline.process_video(db, job.id) == JobStatus.FETCHED and fake_media == []

    got = client.post("/api/helper/next", headers=helper).json()["job"]
    assert got["job_id"] == job.id and got["url"].endswith("watch?v=v1") and got["look"] and got["short_side"] in (720, 1080)
    assert "path" not in json.dumps(got)  # links to fetch files, never paths on the server
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.DOWNLOADING and db.get(Job, job.id).edit_place == "pc"
    assert client.post("/api/helper/next", headers=helper).json()["job"]["job_id"] == job.id  # one at a time: the same one again

    assert client.post(f"/api/helper/jobs/{job.id}/progress", headers=helper, json={"stage": "download", "percent": 50}).json() == {"stop": False}
    assert client.post(f"/api/helper/jobs/{job.id}/progress", headers=helper, json={"stage": "editing", "percent": 20}).json() == {"stop": False}
    db.expire_all()
    assert db.get(Job, job.id).status == JobStatus.RENDERING and db.get(Job, job.id).progress == 20

    r = client.post(f"/api/helper/jobs/{job.id}/result", headers=helper, files={"file": ("clip.mp4", io.BytesIO(_mp4()), "video/mp4")})
    assert r.status_code == 200, r.text
    db.expire_all()
    done = db.get(Job, job.id)
    assert done.video.rendered_file_path and done.status in (JobStatus.AWAITING_APPROVAL, JobStatus.READY) and fake_media == []
    assert "edited on Office PC" in " ".join(e.message for e in done.events) or any("PC Helper" in e.message for e in done.events)

    # Now the member's next video.
    assert client.post("/api/helper/next", headers=helper).json()["job"]["job_id"] == second.id


def test_a_pc_that_stops_answering_hands_its_video_on_after_three_minutes(client, auth, db, fake_media, monkeypatch):
    helper = _connect(client, auth)
    job = _make_job(db, rendered=False)
    client.post("/api/helper/next", headers=helper)
    device = db.scalar(db.query(EditorDevice).statement)
    device.last_seen_at = utcnow() - timedelta(minutes=2)
    db.commit()
    pipeline.scheduler_tick(db)
    db.commit()
    db.expire_all()
    assert db.get(Job, job.id).edit_place == "pc"  # two minutes: still the PC's

    device = db.scalar(db.query(EditorDevice).statement)
    device.last_seen_at = utcnow() - timedelta(minutes=4)
    db.commit()
    assert job.id in pipeline.scheduler_tick(db)["process"]  # moves on, and is processed at once
    db.commit()
    db.expire_all()
    moved = db.get(Job, job.id)
    assert moved.status == JobStatus.FETCHED and moved.edit_place is None
    assert "stopped answering for 3 minutes" in moved.events[-1].message

    # Late result from that PC: refused, so a video is never made twice.
    r = client.post(f"/api/helper/jobs/{job.id}/result", headers=helper, files={"file": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")})
    assert r.status_code == 409

    # Without cloud editing and with the owner's choice "fail", nothing can edit it: shown as failed.
    monkeypatch.setattr(cloud_editor, "fallback", lambda db: "fail")
    assert pipeline.process_video(db, job.id) == JobStatus.FAILED
    assert "cloud editing is not set up" in db.get(Job, job.id).error


def test_a_failure_on_the_pc_is_tried_again_and_a_paused_video_is_dropped(client, auth, db, fake_media):
    helper = _connect(client, auth)
    job = _make_job(db, rendered=False)
    client.post("/api/helper/next", headers=helper)
    client.post(f"/api/helper/jobs/{job.id}/failed", headers=helper, json={"stage": "download", "message": "The video is private"})
    db.expire_all()
    again = db.get(Job, job.id)
    assert again.status == JobStatus.FETCHED and again.attempts == 1 and "private" in again.error
    assert client.post("/api/helper/next", headers=helper).json()["job"] is None  # it waits a little before trying again

    again.next_check_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/helper/next", headers=helper).json()["job"]["job_id"] == job.id
    db.expire_all()
    pipeline.pause_job(db, db.get(Job, job.id))
    db.commit()
    assert client.post(f"/api/helper/jobs/{job.id}/progress", headers=helper, json={"stage": "editing", "percent": 40}).json() == {"stop": True}


def test_a_paused_helper_or_another_members_pc_gets_nothing(client, auth, member_auth, db):
    helper = _connect(client, auth)
    theirs = _connect(client, member_auth, "Sam's laptop")
    job = _make_job(db, rendered=False)
    assert client.post("/api/helper/next", headers=theirs).json()["job"] is None  # another member's video
    client.post("/api/helper/beat", headers=helper, json={"paused": True})
    assert client.post("/api/helper/next", headers=helper).json()["job"] is None
    assert editors.online_device(db, 1) is None  # paused counts as off: its videos go elsewhere
    assert client.get(f"/api/helper/jobs/{job.id}/files/font", headers=theirs).status_code == 409


@respx.mock
def test_cloud_run_edits_when_the_pc_is_off(db, fake_media, monkeypatch):
    monkeypatch.setattr(push, "base_url", lambda: "https://clips.example.com")
    monkeypatch.setattr(cloud_editor, "id_token", lambda key, audience: "id-token")
    cloud_editor.save(db, url="https://editor-abc.a.run.app", key_text=json.dumps(FAKE_KEY))
    assert cloud_editor.ready(db) and "private_key" not in json.dumps(cloud_editor.info(db))
    job = _make_job(db, rendered=False)
    seen = {}

    def render(request: httpx.Request):
        body = json.loads(request.content)
        seen.update(body=body, auth=request.headers["authorization"])
        assert body["files"]["source"]["url"].startswith("https://clips.example.com/api/cloud/jobs/") and body["files"]["source"]["ext"] == ".mp4"
        with open(cloud_editor.incoming_path(job.id), "wb") as fh:  # what the result link receives from Cloud Run
            fh.write(_mp4())
        return httpx.Response(200, json={"ok": True, "seconds": 1})

    respx.post("https://editor-abc.a.run.app/render").mock(side_effect=render)
    status = pipeline.process_video(db, job.id)
    assert status in (JobStatus.AWAITING_APPROVAL, JobStatus.READY, JobStatus.REWRITING), status
    assert fake_media == [] and seen["auth"] == "Bearer id-token"  # the server downloaded it; Cloud Run edited it
    db.refresh(job)
    assert job.edit_place == "cloud" and job.edit_token_hash is None and job.video.rendered_file_path
    assert any("Google Cloud" in e.message for e in job.events)


@respx.mock
def test_a_cloud_failure_is_retried_then_shown_as_failed(db, fake_media, monkeypatch):
    monkeypatch.setattr(push, "base_url", lambda: "https://clips.example.com")
    monkeypatch.setattr(cloud_editor, "id_token", lambda key, audience: "id-token")
    cloud_editor.save(db, url="https://editor-abc.a.run.app", key_text=json.dumps(FAKE_KEY))
    respx.post("https://editor-abc.a.run.app/render").mock(return_value=httpx.Response(422, json={"error": "FFmpeg could not read the file"}))
    job = _make_job(db, rendered=False)
    assert pipeline.process_video(db, job.id) == JobStatus.DOWNLOADING
    db.refresh(job)
    assert job.attempts == 1 and "FFmpeg could not read the file" in job.error and job.video.source_file_path  # the download is kept
    pipeline.process_video(db, job.id)
    assert pipeline.process_video(db, job.id) == JobStatus.FAILED


def test_the_cloud_links_open_only_with_the_one_job_key(client, db):
    job = _make_job(db, rendered=False)
    job.edit_token_hash = cloud_editor._hash("right-key")
    job.edit_spec = {"files": {"source": __file__}}
    job.status = JobStatus.RENDERING
    db.commit()
    assert client.get(f"/api/cloud/jobs/{job.id}/files/source?t=wrong").status_code == 404
    assert client.get(f"/api/cloud/jobs/{job.id}/files/source?t=right-key").status_code == 200
    assert client.post(f"/api/cloud/jobs/{job.id}/progress?t=right-key", json={"percent": 30}).json() == {"stop": False}
    assert client.put(f"/api/cloud/jobs/{job.id}/result?t=right-key", content=b"video").json()["bytes"] == 5


def test_only_the_owner_sets_up_cloud_editing_and_a_wrong_key_is_refused(client, auth, member_auth):
    assert client.get("/api/integrations/cloud-editing", headers=member_auth).status_code == 403
    r = client.post("/api/integrations/cloud-editing/key", headers=auth, files={"file": ("key.json", b'{"type": "user"}', "application/json")})
    assert r.status_code == 400 and "service account" in r.json()["detail"]
    r = client.post("/api/integrations/cloud-editing/key", headers=auth, files={"file": ("key.json", json.dumps(FAKE_KEY).encode(), "application/json")})
    assert r.status_code == 200 and r.json()["has_key"] and "private_key" not in r.text
    assert client.put("/api/integrations/cloud-editing", headers=auth, json={"url": "http://not-https"}).status_code == 400
    assert client.put("/api/integrations/cloud-editing", headers=auth, json={"fallback": "server"}).json()["fallback"] == "server"


def test_the_helper_can_disconnect_itself(client, auth, db):
    helper = _connect(client, auth)
    assert client.post("/api/helper/disconnect", headers=helper).status_code == 204
    assert client.get("/api/helper", headers=auth).json()["devices"] == []
    assert client.post("/api/helper/beat", headers=helper, json={}).status_code == 401


def test_the_server_can_hand_out_the_helper_program(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(editors, "helper_folder", lambda: str(tmp_path))
    page = client.get("/api/helper", headers=auth).json()
    assert page["download_mac"] == "/api/helper/download/mac" and page["ready_mac"] is False  # the button works, and says the file is on its way
    missing = client.get("/api/helper/download/windows")
    assert missing.status_code == 404 and "on its way" in missing.text and "text/html" in missing.headers["content-type"]
    (tmp_path / "ClipRelay-Helper-windows.exe").write_bytes(b"MZ program")
    page = client.get("/api/helper", headers=auth).json()
    assert page["download_windows"] == "/api/helper/download/windows" and page["ready_windows"] is True
    r = client.get("/api/helper/download/windows")
    assert r.status_code == 200 and r.content == b"MZ program" and "ClipRelay-Helper-windows.exe" in r.headers["content-disposition"]
    assert client.get("/api/helper/download/linux").status_code == 404


def test_the_helper_window_shows_the_plan_and_three_months(client, auth, db, fake_media):
    helper = _connect(client, auth)
    job = _make_job(db, rendered=False)
    got = client.post("/api/helper/next", headers=helper).json()["job"]
    assert got["link"].endswith("watch?v=v1") and got["thumbnail"].startswith("https://i.ytimg.com/vi/v1/")
    client.post(f"/api/helper/jobs/{job.id}/result", headers=helper, files={"file": ("clip.mp4", io.BytesIO(_mp4()), "video/mp4")})
    view = client.get("/api/helper/overview", headers=helper).json()
    assert view["plan"]["name"] == "Owner" and len(view["months"]) == 3
    assert view["months"][0]["edited_on_pc"] == 1 and view["months"][0]["edited"] == 1 and view["months"][1]["edited"] == 0
    assert view["recent"][0]["title"] == "Hidden beaches in Crete" and view["recent"][0]["url"].endswith("v=v1")
