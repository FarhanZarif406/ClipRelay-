"""TikTok Login Kit (OAuth v2) + Content Posting API (direct post) + Display API video query.

Docs:
  https://developers.tiktok.com/doc/login-kit-web
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
  https://developers.tiktok.com/doc/content-posting-api-reference-get-video-status
"""

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.config import get_settings
from app.services import credentials
from app.integrations.http import ApiError, AuthError, RateLimitError, request

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"

MIN_CHUNK = 5 * 1024 * 1024
SINGLE_CHUNK_MAX = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024

AUTH_CODES = {"access_token_invalid", "scope_not_authorized", "token_not_authorized_for_specified_open_id"}
RATE_CODES = {"rate_limit_exceeded", "spam_risk_too_many_pending_share"}
# Publish failure reasons that mean TikTok's moderation rejected / removed the content.
VIOLATION_REASONS = {
    "spam_risk",
    "spam_risk_text",
    "spam_risk_user_banned_from_posting",
    "spam_risk_too_many_posts",
    "content_violation",
    "community_guidelines_violation",
    "copyright_violation",
}


class NotSupportedError(ApiError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    open_id: str
    scope: str
    expires_at: datetime
    refresh_expires_at: datetime


def redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/tiktok/oauth/callback"


def authorize_url(state: str) -> str:
    s = get_settings()
    query = {
        "client_key": credentials.get("tiktok.client_key"),
        "scope": s.tiktok_scopes,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _check(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        body = {}
    # OAuth endpoints return {"error": "...", "error_description": "..."}; API endpoints return {"error": {"code": ...}}
    err = body.get("error")
    if isinstance(err, str):
        code, message = err, body.get("error_description", err)
    elif isinstance(err, dict):
        code, message = err.get("code", "ok"), err.get("message", "")
    else:
        code, message = ("ok" if response.status_code < 400 else str(response.status_code)), response.text
    if code != "ok" or response.status_code >= 400:
        if code in AUTH_CODES or code == "invalid_grant" or response.status_code == 401:
            raise AuthError(f"TikTok auth error: {code} {message}", status=response.status_code, code=code, body=body)
        if code in RATE_CODES or response.status_code == 429:
            raise RateLimitError(f"TikTok rate limit: {code} {message}", status=response.status_code, code=code, body=body)
        raise ApiError(f"TikTok API error: {code} {message}", status=response.status_code, code=code, body=body)
    return body


def _token_set(data: dict) -> TokenSet:
    now = datetime.now(timezone.utc)
    return TokenSet(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        open_id=data["open_id"],
        scope=data.get("scope", ""),
        expires_at=now + timedelta(seconds=int(data.get("expires_in", 86400))),
        refresh_expires_at=now + timedelta(seconds=int(data.get("refresh_expires_in", 31536000))),
    )


def exchange_code(code: str) -> TokenSet:
    get_settings()
    data = _check(
        request(
            "POST",
            f"{API}/oauth/token/",
            data={
                "client_key": credentials.get("tiktok.client_key"),
                "client_secret": credentials.get("tiktok.client_secret"),
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )
    return _token_set(data)


def refresh(refresh_token: str) -> TokenSet:
    get_settings()
    data = _check(
        request(
            "POST",
            f"{API}/oauth/token/",
            data={
                "client_key": credentials.get("tiktok.client_key"),
                "client_secret": credentials.get("tiktok.client_secret"),
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    )
    return _token_set(data)


def revoke(access_token: str) -> None:
    get_settings()
    request(
        "POST",
        f"{API}/oauth/revoke/",
        data={"client_key": credentials.get("tiktok.client_key"), "client_secret": credentials.get("tiktok.client_secret"), "token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        retries=1,
    )


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}


def user_info(token: str) -> dict:
    fields = "open_id,avatar_url,display_name"
    if "user.info.profile" in get_settings().tiktok_scopes:
        fields += ",username"
    data = _check(request("GET", f"{API}/user/info/", params={"fields": fields}, headers=_auth(token)))
    return data.get("data", {}).get("user", {})


def creator_info(token: str) -> dict:
    return _check(request("POST", f"{API}/post/publish/creator_info/query/", headers=_auth(token), json={}))["data"]


def chunk_plan(size: int) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) following TikTok's media transfer rules."""
    if size <= SINGLE_CHUNK_MAX:
        return size, 1
    count = math.floor(size / CHUNK)
    return CHUNK, count


def init_direct_post(token: str, *, title: str, privacy_level: str, video_size: int, creator: dict) -> dict:
    chunk_size, count = chunk_plan(video_size)
    body = {
        "post_info": {
            "title": title[:2200],
            "privacy_level": privacy_level,
            "disable_duet": bool(creator.get("duet_disabled", False)),
            "disable_comment": bool(creator.get("comment_disabled", False)),
            "disable_stitch": bool(creator.get("stitch_disabled", False)),
            "video_cover_timestamp_ms": 1000,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": count,
        },
    }
    return _check(request("POST", f"{API}/post/publish/video/init/", headers=_auth(token), json=body, retries=2))["data"]


def init_inbox_upload(token: str, *, video_size: int) -> dict:
    """Upload-to-inbox: the video lands in the creator's TikTok inbox and they finish the post in the app.

    Needs the `video.upload` scope. This is the mode to launch with: before TikTok's audit is approved,
    direct posts are forced private and the API gives no signal that it is happening.
    """
    chunk_size, count = chunk_plan(video_size)
    body = {"source_info": {"source": "FILE_UPLOAD", "video_size": video_size, "chunk_size": chunk_size, "total_chunk_count": count}}
    return _check(request("POST", f"{API}/post/publish/inbox/video/init/", headers=_auth(token), json=body, retries=2))["data"]


def upload_file(upload_url: str, path: str) -> None:
    size = os.path.getsize(path)
    chunk_size, count = chunk_plan(size)
    with open(path, "rb") as fh:
        for index in range(count):
            start = index * chunk_size
            end = size - 1 if index == count - 1 else start + chunk_size - 1
            fh.seek(start)
            payload = fh.read(end - start + 1)
            response = request(
                "PUT",
                upload_url,
                content=payload,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(payload)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                timeout=300,
            )
            if response.status_code not in (200, 201, 206):
                raise ApiError(f"TikTok chunk upload failed ({response.status_code}): {response.text[:200]}", status=response.status_code)


def fetch_status(token: str, publish_id: str) -> dict:
    return _check(
        request("POST", f"{API}/post/publish/status/fetch/", headers=_auth(token), json={"publish_id": publish_id})
    )["data"]


def query_videos(token: str, video_ids: list[str]) -> list[dict]:
    data = _check(
        request(
            "POST",
            f"{API}/video/query/",
            params={"fields": "id,title,share_url,create_time,view_count"},
            headers=_auth(token),
            json={"filters": {"video_ids": video_ids}},
        )
    )
    return data.get("data", {}).get("videos", [])


def delete_video(token: str, video_id: str) -> None:
    """TikTok's public API exposes no endpoint to delete a published post.

    Kept as an explicit integration point so the violation checker can attempt removal if TikTok adds
    one (or if you have partner access). Callers fall back to `manual_required`.
    """
    raise NotSupportedError("TikTok's public API does not support deleting posts; remove it in the TikTok app.")
