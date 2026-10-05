from datetime import timedelta

import httpx
import pytest
import respx

from app.api.sources import parse_entry
from app.integrations import http, instagram, tiktok
from app.integrations.http import AuthError, RateLimitError
from app.models import TikTokStatus, utcnow
from app.security import decrypt, encrypt
from app.services import prompts, tokens
from tests.helpers import TT, ig_video


@respx.mock
def test_http_retries_with_backoff():
    route = respx.get("https://x.test/").mock(side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json={})])
    assert http.request("GET", "https://x.test/").status_code == 200
    assert route.call_count == 3


def test_backoff_grows_exponentially():
    assert http.backoff_delay(0, base=1) <= 1
    assert 4 <= http.backoff_delay(3, base=1) * 2 <= 16
    assert http.backoff_delay(30, base=1, cap=60) <= 60


def test_token_encryption_roundtrip():
    secret = "IGQVJ-very-secret"
    stored = encrypt(secret)
    assert stored != secret and decrypt(stored) == secret


def test_media_item_title_and_tags():
    item = instagram.MediaItem(**{**ig_video("1", caption="3 hidden beaches in Crete #Crete #travel\nmore text #crete"), "timestamp": None})
    assert item.title == "3 hidden beaches in Crete"
    assert item.tags == ["crete", "travel"]


@respx.mock
def test_instagram_auth_error_mapping():
    respx.get(url__startswith="https://graph.instagram.com/v21.0/me").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Session expired", "type": "OAuthException", "code": 190}})
    )
    with pytest.raises(AuthError):
        instagram.get_profile("bad")


@respx.mock
def test_instagram_oauth_exchange_gets_long_lived_token():
    respx.post(instagram.TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "short", "user_id": 1789}))
    respx.get("https://graph.instagram.com/access_token").mock(return_value=httpx.Response(200, json={"access_token": "long", "expires_in": 5184000}))
    result = instagram.exchange_code("code")
    assert result.access_token == "long" and result.user_id == "1789"
    assert result.expires_at > utcnow() + timedelta(days=59)


def test_parse_entry():
    assert parse_entry("@SlowTravel") == ("username", "slowtravel")
    assert parse_entry("https://www.instagram.com/daily.nature/") == ("username", "daily.nature")
    assert parse_entry("https://instagram.com/profile/123456") == ("id", "123456")
    assert parse_entry("not a valid name!") is None


def test_tiktok_chunk_plan():
    assert tiktok.chunk_plan(4 * 1024 * 1024) == (4 * 1024 * 1024, 1)
    size = 100 * 1024 * 1024
    chunk, count = tiktok.chunk_plan(size)
    assert chunk == 10 * 1024 * 1024 and count == 10


@respx.mock
def test_tiktok_error_mapping():
    respx.post(f"{TT}/post/publish/creator_info/query/").mock(
        return_value=httpx.Response(401, json={"error": {"code": "access_token_invalid", "message": "bad"}})
    )
    with pytest.raises(AuthError):
        tiktok.creator_info("x")
    respx.post(f"{TT}/post/publish/status/fetch/").mock(
        return_value=httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "slow"}})
    )
    with pytest.raises(RateLimitError):
        tiktok.fetch_status("x", "pub")


@respx.mock
def test_tiktok_token_refresh(db, tiktok_account):
    tiktok_account.token_expires_at = utcnow() + timedelta(minutes=5)
    db.commit()
    respx.post(f"{TT}/oauth/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "new-access", "refresh_token": "new-refresh", "open_id": "open-1", "expires_in": 86400, "refresh_expires_in": 31536000, "scope": "video.publish"})
    )
    assert tokens.tiktok_token(db, tiktok_account) == "new-access"
    assert decrypt(tiktok_account.refresh_token_enc) == "new-refresh"


@respx.mock
def test_tiktok_refresh_failure_marks_expired(db, tiktok_account):
    tiktok_account.token_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    respx.post(f"{TT}/oauth/token/").mock(return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "expired"}))
    with pytest.raises(AuthError):
        tokens.tiktok_token(db, tiktok_account)
    assert tiktok_account.status == TikTokStatus.EXPIRED


@respx.mock
def test_instagram_token_refresh_near_expiry(db, source):
    source.token_expires_at = utcnow() + timedelta(days=3)
    source.token_refreshed_at = utcnow() - timedelta(days=2)
    db.commit()
    respx.get("https://graph.instagram.com/refresh_access_token").mock(return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 5184000}))
    assert tokens.instagram_token(db, source) == "fresh"
    assert source.token_expires_at > utcnow() + timedelta(days=50)


def test_prompt_render_variables_and_aliases():
    out = prompts.render("Rewrite {caption} / {original_title} / {tags} / {unknown}", {"caption": "C", "title": "T", "tags": "#a"})
    assert out == "Rewrite C / T / #a / {unknown}"
    assert prompts.parse_hashtags("#Crete #hidden_gems greece #crete") == ["crete", "hidden_gems", "greece"]
