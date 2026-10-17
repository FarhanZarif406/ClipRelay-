"""PC Helper: the member's page (connect a PC, see and disconnect PCs) and the calls the helper program makes.

The helper signs in with its own key (`Authorization: Bearer crh_…`), which only reaches that member's videos.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentUser
from app.models import EditorDevice
from app.services import dispatch, editors

router = APIRouter(tags=["helper"])


# ---------------------------------------------------------------- the member's page

@router.get("/helper")
def helper_page(db: DB, user: CurrentUser):
    return editors.view(db, user)


@router.post("/helper/code")
def connect_code(db: DB, user: CurrentUser):
    """A short code to type into the PC Helper; it works for ten minutes."""
    if not editors.plans.allows(db, user.id, "pc_editing"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PC Helper editing is not part of your plan. Ask the owner to upgrade it.")
    return editors.new_code(db, user)


@router.delete("/helper/devices/{device_id}", status_code=204)
def disconnect(device_id: int, db: DB, user: CurrentUser):
    device = db.get(EditorDevice, device_id)
    if not device or device.user_id != user.id:
        raise HTTPException(404, "PC not found")
    editors.remove(db, device)


@router.get("/helper/download/{platform}", include_in_schema=False)
def download_helper(platform: str):
    """The PC Helper program, when the owner put it in the server's helper folder. It holds no secrets."""
    path = editors.helper_file(platform)
    if not path:
        raise HTTPException(404, "The PC Helper for this computer is not on the server. Ask the owner for the link.")
    return FileResponse(path, filename=editors.HELPER_FILES[platform], media_type="application/octet-stream")


# ---------------------------------------------------------------- the helper program

def current_device(db: DB, authorization: Annotated[str | None, Header()] = None) -> EditorDevice:
    token = (authorization or "").removeprefix("Bearer ").strip()
    device = editors.device_for_token(db, token)
    if not device:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This PC is not connected any more. Connect it again with a new code from the website.")
    user = device.user
    if not user or not user.is_active or (user.suspended and not user.is_owner):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your account is suspended. Contact the owner.")
    return device


Device = Annotated[EditorDevice, Depends(current_device)]


class ConnectIn(BaseModel):
    code: str = Field(min_length=4, max_length=20)
    name: str = Field(default="My computer", max_length=80)
    platform: str = Field(default="", max_length=16)
    version: str = Field(default="", max_length=20)


@router.post("/helper/connect")
def connect(body: ConnectIn, db: DB):
    """The helper exchanges the code for its own key (shown to it once; stored here only as a hash)."""
    try:
        device, token = editors.connect(db, body.code, name=body.name, platform=body.platform, version=body.version)
    except editors.EditorError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"token": token, "device": editors.device_view(device), "account": device.user.email}


class BeatIn(BaseModel):
    version: str = Field(default="", max_length=20)
    paused: bool | None = None


@router.post("/helper/beat")
def beat(body: BeatIn, db: DB, device: Device):
    return {**editors.beat(db, device, version=body.version, paused=body.paused), "device": editors.device_view(device),
            "account": device.user.email, "language": device.user.language}


@router.post("/helper/next")
def next_job(db: DB, device: Device):
    job = editors.next_job(db, device)
    return {"job": editors.public_spec(job) if job else None}


@router.get("/helper/jobs/{job_id}/files/{kind}")
def job_file(job_id: int, kind: str, db: DB, device: Device):
    try:
        return FileResponse(editors.file_path(db, device, job_id, kind))
    except editors.NotYours as exc:
        raise HTTPException(409, str(exc)) from exc
    except editors.EditorError as exc:
        raise HTTPException(404, str(exc)) from exc


class ProgressIn(BaseModel):
    stage: str = Field(pattern="^(download|editing)$")
    percent: float | None = None


@router.post("/helper/jobs/{job_id}/progress")
def job_progress(job_id: int, body: ProgressIn, db: DB, device: Device):
    return editors.progress(db, device, job_id, body.stage, body.percent)


@router.post("/helper/jobs/{job_id}/result")
def job_result(job_id: int, db: DB, device: Device, file: UploadFile = File(...)):
    try:
        status_now = editors.finish(db, device, job_id, file.file)
    except editors.NotYours as exc:
        raise HTTPException(409, str(exc)) from exc
    except editors.EditorError as exc:
        raise HTTPException(422, str(exc)) from exc
    if status_now == "ready":
        dispatch.upload_job(job_id)  # straight to Buffer, without waiting for the next scheduler tick
    return {"status": status_now}


class FailedIn(BaseModel):
    stage: str = Field(pattern="^(download|editing)$")
    message: str = Field(default="", max_length=2000)


@router.post("/helper/jobs/{job_id}/failed")
def job_failed(job_id: int, body: FailedIn, db: DB, device: Device):
    editors.failed(db, device, job_id, body.stage, body.message)
    return {"ok": True}


@router.post("/helper/disconnect", status_code=204)
def disconnect_self(db: DB, device: Device):
    """The helper's own Disconnect: its key stops working."""
    editors.remove(db, device)
