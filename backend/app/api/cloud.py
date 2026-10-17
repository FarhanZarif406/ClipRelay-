"""Cloud editing: the owner's settings (Integrations → Cloud editing), and the links Cloud Run uses for one edit.

Cloud Run has no login here: each edit gets a one-job key (`?t=`) that opens only that video's files and result,
and stops working when the edit is over.
"""

import os

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import DB, OwnerUser
from app.models import JobStatus
from app.services import activity, cloud_editor
from app.services.pipeline import STOPPED

router = APIRouter(tags=["cloud editing"])
MAX_KEY_BYTES = 64 * 1024


@router.get("/integrations/cloud-editing")
def cloud_status(db: DB, _: OwnerUser):
    return cloud_editor.info(db)


class CloudIn(BaseModel):
    url: str | None = Field(default=None, max_length=300)
    fallback: str | None = Field(default=None, pattern="^(fail|server)$")
    enabled: bool | None = None


@router.put("/integrations/cloud-editing")
def save_cloud(body: CloudIn, db: DB, user: OwnerUser):
    try:
        out = cloud_editor.save(db, url=body.url, fallback_to=body.fallback, enabled=body.enabled)
    except cloud_editor.CloudError as exc:
        raise HTTPException(400, str(exc)) from exc
    activity.record(db, "Cloud editing", f"{user.email} changed the cloud editing settings", event="cloud_settings", user_id=user.id)
    db.commit()
    return out


@router.post("/integrations/cloud-editing/key")
async def upload_key(db: DB, user: OwnerUser, file: UploadFile = File(...)):
    """The service account key file (JSON). Stored encrypted; never shown or logged again."""
    data = await file.read(MAX_KEY_BYTES + 1)
    if len(data) > MAX_KEY_BYTES:
        raise HTTPException(400, "That file is too large to be a key file.")
    try:
        out = cloud_editor.save(db, key_text=data.decode("utf-8", "replace"))
    except cloud_editor.CloudError as exc:
        raise HTTPException(400, str(exc)) from exc
    activity.record(db, "Cloud editing", f"{user.email} saved a service account key", event="cloud_key", user_id=user.id)
    db.commit()
    return out


@router.delete("/integrations/cloud-editing/key")
def remove_key(db: DB, user: OwnerUser):
    out = cloud_editor.remove_key(db)
    activity.record(db, "Cloud editing", f"{user.email} removed the service account key", event="cloud_key_removed", user_id=user.id)
    db.commit()
    return out


@router.post("/integrations/cloud-editing/test")
def test_cloud(db: DB, _: OwnerUser):
    return cloud_editor.test(db)


# ---------------------------------------------------------------- called by Cloud Run during one edit

def _job(db, job_id: int, token: str):
    job = cloud_editor.job_for_token(db, job_id, token)
    if not job:
        raise HTTPException(404, "Not found")
    return job


@router.get("/cloud/jobs/{job_id}/files/{kind}", include_in_schema=False)
def cloud_file(job_id: int, kind: str, t: str, db: DB):
    job = _job(db, job_id, t)
    path = ((job.edit_spec or {}).get("files") or {}).get(kind)
    if kind not in cloud_editor.FILES or not path or not os.path.isfile(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path)


class CloudProgressIn(BaseModel):
    percent: float = Field(ge=0, le=100)


@router.post("/cloud/jobs/{job_id}/progress", include_in_schema=False)
def cloud_progress(job_id: int, body: CloudProgressIn, t: str, db: DB):
    """How far the edit is. {"stop": true} when the video was paused or stopped meanwhile."""
    job = _job(db, job_id, t)
    if job.status in STOPPED or job.status != JobStatus.RENDERING:
        return {"stop": True}
    job.progress = max(0, min(99, int(body.percent)))
    db.commit()
    return {"stop": False}


@router.put("/cloud/jobs/{job_id}/result", include_in_schema=False)
async def cloud_result(job_id: int, t: str, request: Request, db: DB):
    """The finished video, sent as the request body. The waiting worker picks it up."""
    _job(db, job_id, t)
    path = cloud_editor.incoming_path(job_id)
    written = 0
    with open(path + ".part", "wb") as out:
        async for chunk in request.stream():
            written += len(chunk)
            if written > cloud_editor.MAX_RESULT_BYTES:
                out.close()
                os.remove(path + ".part")
                raise HTTPException(413, "The edited video is larger than 1 GB")
            out.write(chunk)
    os.replace(path + ".part", path)
    return {"ok": True, "bytes": written}
