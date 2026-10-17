"""Cloud editing: a video is edited in Google Cloud Run when the member's PC Helper cannot edit it.

The owner deploys the editor in `cloud-editor/` to Cloud Run once and saves its address and a service account key
here (Integrations → Cloud editing). This server still downloads the video (with its cookies and proxy); Cloud Run
fetches the original and the member's files from this server with a one-job key, runs the same FFmpeg edit, and
sends the finished video back. So this server needs its public HTTPS address, as it does for Buffer.

The service account key is a secret: it is stored encrypted and never shown again, in the page or in the logs.
"""

import hashlib
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from urllib.parse import urlparse

import httpx
import jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting, Job, utcnow
from app.security import decrypt, encrypt
from app.services import media, push, workspace_settings

KEY = "cloud_editor"
FALLBACKS = ("fail", "server")  # when neither the PC nor the cloud can edit: show it as failed, or edit on this server
TOKEN_URI = "https://oauth2.googleapis.com/token"
RENDER_TIMEOUT = 40 * 60
MAX_RESULT_BYTES = 1024 * 1024 * 1024
FILES = ("source", "font", "watermark", "music")

_tokens: dict[str, tuple[str, float]] = {}  # audience -> (ID token, expires at)
_tokens_lock = threading.Lock()


class CloudError(Exception):
    """Cloud editing is not set up, or Cloud Run could not edit a video. The message is written for people."""


def _value(db: Session) -> dict:
    return workspace_settings.get(db, KEY)


def fallback(db: Session) -> str:
    value = _value(db).get("fallback")
    return value if value in FALLBACKS else "fail"


def _key(db: Session) -> dict | None:
    stored = _value(db).get("key_enc")
    if not stored:
        return None
    try:
        return json.loads(decrypt(stored) or "")
    except ValueError:
        return None


def ready(db: Session) -> bool:
    value = _value(db)
    return bool(value.get("url") and value.get("key_enc") and value.get("enabled", True))


def info(db: Session) -> dict:
    """What the owner's page shows. Never the key itself."""
    value = _value(db)
    base = push.base_url()
    return {
        "url": value.get("url") or "",
        "enabled": value.get("enabled", True) is not False,
        "has_key": bool(value.get("key_enc")),
        "client_email": value.get("client_email") or "",
        "project_id": value.get("project_id") or "",
        "fallback": fallback(db),
        "ready": ready(db),
        "public_url": base if push.is_public(base) else "",
        "last_test": value.get("last_test"),
    }


def read_key(text: str) -> dict:
    """Check a service account key file (JSON) from Google Cloud and keep only what is needed to sign in."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CloudError("That is not a key file: Google Cloud gives it as a .json file.") from exc
    if not isinstance(data, dict) or data.get("type") != "service_account" or not data.get("private_key") or not data.get("client_email"):
        raise CloudError("That file is not a service account key. In Google Cloud: IAM → Service accounts → Keys → Add key → JSON.")
    return {name: data[name] for name in ("client_email", "private_key", "private_key_id", "project_id", "token_uri") if data.get(name)}


def check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CloudError("The Cloud Run address starts with https:// (Cloud Run shows it at the top of the service, e.g. https://cliprelay-editor-abc123-uc.a.run.app).")
    return url


def save(db: Session, *, url: str | None = None, key_text: str | None = None, fallback_to: str | None = None, enabled: bool | None = None) -> dict:
    changes: dict = {}
    if url is not None:
        changes["url"] = check_url(url) if url.strip() else ""
    if key_text is not None:
        key = read_key(key_text)
        changes.update(key_enc=encrypt(json.dumps(key)), client_email=key["client_email"], project_id=key.get("project_id", ""))
    if fallback_to is not None:
        if fallback_to not in FALLBACKS:
            raise CloudError("Choose what happens when nothing can edit a video: fail, or edit on this server.")
        changes["fallback"] = fallback_to
    if enabled is not None:
        changes["enabled"] = bool(enabled)
    if url is not None or key_text is not None:
        changes["last_test"] = None  # a new address or key is tested afresh
        with _tokens_lock:
            _tokens.clear()
    workspace_settings.update(db, KEY, changes)
    db.commit()
    return info(db)


def remove_key(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    if row and isinstance(row.value, dict):
        row.value = {k: v for k, v in row.value.items() if k not in ("key_enc", "client_email", "project_id", "last_test")}
    db.commit()
    with _tokens_lock:
        _tokens.clear()
    return info(db)


# ---------------------------------------------------------------- signing in to Cloud Run

def id_token(key: dict, audience: str) -> str:
    """A Google ID token for the Cloud Run service, signed with the service account key (cached for 50 minutes)."""
    with _tokens_lock:
        cached = _tokens.get(audience)
        if cached and cached[1] > time.time():
            return cached[0]
    now = int(time.time())
    claims = {"iss": key["client_email"], "sub": key["client_email"], "aud": key.get("token_uri") or TOKEN_URI,
              "iat": now, "exp": now + 3600, "target_audience": audience}
    headers = {"kid": key["private_key_id"]} if key.get("private_key_id") else None
    try:
        assertion = jwt.encode(claims, key["private_key"], algorithm="RS256", headers=headers)
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise CloudError("The service account key could not be used. Download a new JSON key and save it again.") from exc
    try:
        response = httpx.post(key.get("token_uri") or TOKEN_URI, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}, timeout=30)
    except httpx.HTTPError as exc:
        raise CloudError(f"Google could not be reached to sign in: {exc}") from exc
    if response.status_code != 200 or "id_token" not in response.text:
        raise CloudError(f"Google refused the service account key (HTTP {response.status_code}). Check that the key is current and not deleted.")
    token = response.json()["id_token"]
    with _tokens_lock:
        _tokens[audience] = (token, time.time() + 50 * 60)
    return token


def _headers(db: Session) -> tuple[str, dict]:
    value = _value(db)
    url, key = value.get("url"), _key(db)
    if not url or not key:
        raise CloudError("Cloud editing is not set up: save the Cloud Run address and the service account key (Integrations → Cloud editing).")
    return url, {"Authorization": f"Bearer {id_token(key, url)}"}


def _answer(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error") or response.json().get("detail") or "")[:300]
    except ValueError:
        if response.status_code == 403:
            return "Cloud Run refused this service account: give it the Cloud Run Invoker role on the service."
        return response.text[:200]


def test(db: Session) -> dict:
    """Sign in and ask the editor whether it is ready. Saved, so the page shows the last result."""
    try:
        url, headers = _headers(db)
        response = httpx.get(f"{url}/health", headers=headers, timeout=60)
        if response.status_code != 200:
            raise CloudError(f"Cloud Run answered HTTP {response.status_code}: {_answer(response)}")
        facts = response.json()
        result = {"ok": True, "message": f"Connected · editor {facts.get('version', '?')} · {facts.get('ffmpeg', 'FFmpeg')}"}
    except (CloudError, httpx.HTTPError, ValueError) as exc:
        result = {"ok": False, "message": str(exc)[:300]}
    if result["ok"] and not push.is_public(push.base_url()):
        result = {"ok": False, "message": "Cloud Run is ready, but this server has no public HTTPS address for it to fetch videos from (Integrations → YouTube push)."}
    result["at"] = utcnow().isoformat()
    workspace_settings.update(db, KEY, {"last_test": result})
    db.commit()
    return result


# ---------------------------------------------------------------- one edit

def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def incoming_path(job_id: int) -> str:
    """Where the finished video Cloud Run sends back is written; shared by the API and the workers."""
    folder = os.path.join(get_settings().storage_local_path, "incoming")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"cloud-{job_id}.mp4")


def job_for_token(db: Session, job_id: int, token: str) -> Job | None:
    job = db.get(Job, job_id)
    if not job or not job.edit_token_hash or not token or not secrets.compare_digest(job.edit_token_hash, _hash(token)):
        return None
    return job


def render(db: Session, job: Job, source_path: str, look: dict, *, hook_text: str | None, font_file: str | None,
           watermark_file: str | None, music_file: str | None) -> media.RenderResult:
    """Have Cloud Run make the edit; returns the finished file on this server, like `media.render`."""
    base = push.base_url()
    if not push.is_public(base):
        raise CloudError("Cloud editing needs this server's public HTTPS address, for Cloud Run to fetch the video from (Integrations → YouTube push).")
    url, headers = _headers(db)
    token = secrets.token_urlsafe(32)
    files = {"source": source_path, "font": font_file or media.default_font(), "watermark": watermark_file, "music": music_file}
    job.edit_token_hash = _hash(token)
    job.edit_spec = {"files": {name: path for name, path in files.items() if path}}
    db.commit()
    link = f"{base}/api/cloud/jobs/{job.id}"
    body = {
        "job": job.id, "look": look, "hook_text": hook_text,
        # The extension tells FFmpeg what each file is (a still watermark image needs it).
        "files": {name: {"url": f"{link}/files/{name}?t={token}", "ext": os.path.splitext(path)[1].lower()} for name, path in files.items() if path},
        "progress_url": f"{link}/progress?t={token}",
        "result_url": f"{link}/result?t={token}",
    }
    result_path = incoming_path(job.id)
    if os.path.exists(result_path):
        os.remove(result_path)
    try:
        response = httpx.post(f"{url}/render", json=body, headers=headers, timeout=RENDER_TIMEOUT)
    except httpx.HTTPError as exc:
        raise CloudError(f"Cloud Run could not be reached: {exc}") from exc
    finally:
        db.refresh(job)
        job.edit_token_hash = None  # the key works for this one edit only
        job.edit_spec = None
        db.commit()
    if response.status_code != 200:
        raise CloudError(f"Cloud editing failed: {_answer(response) or f'HTTP {response.status_code}'}")
    if not os.path.exists(result_path) or os.path.getsize(result_path) == 0:
        raise CloudError("Cloud Run finished but the edited video did not arrive")
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    shutil.move(result_path, path)
    facts = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    return media.RenderResult(path, f"Google Cloud Run ({url})", float(facts.get("seconds") or 0), facts.get("note"), bool(facts.get("vertical_source")))
