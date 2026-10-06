"""Instagram API with Instagram Login (official Graph API).

Only Business/Creator accounts that complete OAuth with this app can be read — ClipRelay never scrapes.
Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.config import get_settings
from app.services import credentials
from app.integrations.http import ApiError, AuthError, RateLimitError, request

AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
TOKEN_URL = "https://api.instagram.com/oauth/access_token"
GRAPH = "https://graph.instagram.com"

HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


@dataclass
class TokenResult:
    access_token: str
    expires_at: datetime | None
    user_id: str | None = None


@dataclass
class MediaItem:
    id: str
    caption: str
    media_type: str
    media_product_type: str | None
    media_url: str | None
    permalink: str | None
    thumbnail_url: str | None
    timestamp: datetime | None

    @property
    def is_video(self) -> bool:
        return self.media_type == "VIDEO"

    @property
    def title(self) -> str:
        first_line = (self.caption or "").strip().split("\n", 1)[0]
        return HASHTAG_RE.sub("", first_line).strip()[:150]

    @property
    def tags(self) -> list[str]:
        return list(dict.fromkeys(tag.lower() for tag in HASHTAG_RE.findall(self.caption or "")))


def redirect_uri() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/api/instagram/oauth/callback"


def authorize_url(state: str) -> str:
    s = get_settings()
    query = {
        "client_id": credentials.get("instagram.app_id"),
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": s.instagram_scopes,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


def _check(response) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {}
    if response.status_code >= 400 or "error" in data or "error_type" in data:
        err = data.get("error") if isinstance(data.get("error"), dict) else data
        message = err.get("message") or err.get("error_message") or response.text
        code = err.get("code")
        if code in (190, 102) or response.status_code == 401:
            raise AuthError(f"Instagram auth error: {message}", status=response.status_code, code=str(code), body=data)
        if code in (4, 17, 32, 613) or response.status_code == 429:
            raise RateLimitError(f"Instagram rate limit: {message}", status=response.status_code, code=str(code), body=data)
        raise ApiError(f"Instagram API error: {message}", status=response.status_code, code=str(code), body=data)
    return data


def _expires(seconds) -> datetime | None:
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds)) if seconds else None


def exchange_code(code: str) -> TokenResult:
    """Exchange the OAuth code for a short-lived token, then upgrade it to a 60-day long-lived token."""
    get_settings()
    data = _check(
        request(
            "POST",
            TOKEN_URL,
            data={
                "client_id": credentials.get("instagram.app_id"),
                "client_secret": credentials.get("instagram.app_secret"),
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(),
                "code": code,
            },
        )
    )
    if isinstance(data.get("data"), list) and data["data"]:
        data = data["data"][0]
    short = data["access_token"]
    long_lived = _check(
        request(
            "GET",
            f"{GRAPH}/access_token",
            params={"grant_type": "ig_exchange_token", "client_secret": credentials.get("instagram.app_secret"), "access_token": short},
        )
    )
    return TokenResult(long_lived["access_token"], _expires(long_lived.get("expires_in")), str(data.get("user_id") or ""))


def refresh_token(token: str) -> TokenResult:
    data = _check(
        request("GET", f"{GRAPH}/refresh_access_token", params={"grant_type": "ig_refresh_token", "access_token": token})
    )
    return TokenResult(data["access_token"], _expires(data.get("expires_in")))


def get_profile(token: str) -> dict:
    v = get_settings().instagram_api_version
    return _check(
        request(
            "GET",
            f"{GRAPH}/{v}/me",
            params={"fields": "user_id,username,name,profile_picture_url,account_type", "access_token": token},
        )
    )


def list_media(token: str, ig_user_id: str, limit: int = 25) -> list[MediaItem]:
    v = get_settings().instagram_api_version
    data = _check(
        request(
            "GET",
            f"{GRAPH}/{v}/{ig_user_id}/media",
            params={
                "fields": "id,caption,media_type,media_product_type,media_url,permalink,thumbnail_url,timestamp",
                "limit": limit,
                "access_token": token,
            },
        )
    )
    items = []
    for raw in data.get("data", []):
        ts = raw.get("timestamp")
        items.append(
            MediaItem(
                id=str(raw["id"]),
                caption=raw.get("caption") or "",
                media_type=raw.get("media_type", ""),
                media_product_type=raw.get("media_product_type"),
                media_url=raw.get("media_url"),
                permalink=raw.get("permalink"),
                thumbnail_url=raw.get("thumbnail_url"),
                timestamp=datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z") if ts else None,
            )
        )
    return items
