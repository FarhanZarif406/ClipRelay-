"""Integrations → Video Source: the downloader's version, cookies file, proxy, player client, test and diagnosis.

Admin only. The cookies file and the proxy address never leave the server.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import DB, OwnerUser
from app.services import activity, downloader

router = APIRouter(prefix="/integrations/source", tags=["integrations"])


class OptionsIn(BaseModel):
    proxy: str | None = Field(default=None, max_length=500)
    player_client: str | None = Field(default=None, max_length=40)


class UrlIn(BaseModel):
    url: str = Field(min_length=1, max_length=500)


@router.get("")
def source(_: OwnerUser):
    return downloader.info()


@router.put("")
def save_options(body: OptionsIn, db: DB, user: OwnerUser):
    try:
        downloader.save_options(proxy_address=body.proxy, client=body.player_client)
    except downloader.DownloaderError as exc:
        raise HTTPException(422, str(exc)) from exc
    changed = ", ".join(name for name, value in (("proxy", body.proxy), ("player client", body.player_client)) if value is not None)
    activity.record(db, "Settings", f"{user.email} changed the downloader's {changed}", event="downloader_updated", user_id=user.id)
    db.commit()
    return downloader.info()


@router.post("/cookies")
async def upload_cookies(request: Request, db: DB, user: OwnerUser):
    """The cookies.txt itself is the request body. Only its status is ever returned."""
    body = await request.body()
    try:
        info = downloader.save_cookies(body)
    except downloader.DownloaderError as exc:
        raise HTTPException(422, str(exc)) from exc
    activity.record(db, "Settings", f"{user.email} uploaded a cookies file for the downloader ({info['count']} cookies)", event="cookies_uploaded", user_id=user.id)
    db.commit()
    return info


@router.delete("/cookies", status_code=204)
def remove_cookies(db: DB, user: OwnerUser):
    downloader.remove_cookies()
    activity.record(db, "Settings", f"{user.email} removed the downloader's cookies file", event="cookies_removed", user_id=user.id)
    db.commit()


@router.post("/update")
def update(db: DB, user: OwnerUser):
    result = downloader.update()
    activity.record(db, "Settings", f"yt-dlp update by {user.email}: {result['message']}", event="downloader_update", level="info" if result["ok"] else "warning", user_id=user.id)
    db.commit()
    return result


@router.post("/test")
def test(body: UrlIn, _: OwnerUser):
    """Looks one video up through the saved proxy and cookies. Nothing is downloaded."""
    try:
        return downloader.test(body.url)
    except downloader.DownloaderError as exc:
        return {"ok": False, "message": str(exc)}


@router.post("/diagnose")
def diagnose(body: UrlIn, _: OwnerUser):
    """Tries one video with every player client, with and without cookies. Changes nothing."""
    try:
        return downloader.start_diagnosis(body.url)
    except downloader.DownloaderError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/diagnose/{run_id}")
def diagnosis(run_id: str, _: OwnerUser):
    run = downloader.get_diagnosis(run_id)
    if not run:
        raise HTTPException(404, "No such diagnosis.")
    return run
