"""Validation for stored credentials. Each validator returns (ok, message):
ok=True valid · ok=False invalid · ok=None can't be verified yet (stays unverified)."""

import re

from app.integrations.http import ApiError, request

TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def _error_text(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or f"HTTP {response.status_code}"
    err = body.get("error")
    if isinstance(err, dict):
        return err.get("message") or err.get("code") or str(err)
    return body.get("error_description") or (err if isinstance(err, str) else None) or f"HTTP {response.status_code}"


def check_instagram(values: dict[str, str]) -> tuple[bool | None, str]:
    app_id, secret = values.get("app_id", ""), values.get("app_secret", "")
    if not app_id or not secret:
        return False, "App ID and App secret are both required"
    if not re.fullmatch(r"\d{6,25}", app_id):
        return False, "The Instagram App ID should be numeric (copy it from Instagram → API setup with Instagram login)"
    if not re.fullmatch(r"[0-9a-fA-F]{32}", secret):
        return False, "The Instagram App secret should be 32 hexadecimal characters"
    # Meta offers no client-credentials check for Instagram Login; the next successful OAuth callback confirms it.
    return None, "Format looks right — it will be confirmed on the next successful Instagram sign-in"


def check_tiktok(values: dict[str, str]) -> tuple[bool | None, str]:
    key, secret = values.get("client_key", ""), values.get("client_secret", "")
    if not key or not secret:
        return False, "Client key and client secret are both required"
    try:
        response = request(
            "POST",
            TIKTOK_TOKEN_URL,
            data={"client_key": key, "client_secret": secret, "grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            retries=2,
            timeout=15,
        )
    except ApiError as exc:
        return False, str(exc)
    if response.status_code == 200:
        try:
            if response.json().get("access_token"):
                return True, "TikTok accepted the client key and secret"
        except ValueError:
            pass
    return False, f"TikTok rejected the credentials: {_error_text(response)}"


def check_transcription(values: dict[str, str]) -> tuple[bool | None, str]:
    key = values.get("api_key", "")
    base = (values.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    if not key:
        return False, "API key is required"
    try:
        response = request("GET", f"{base}/models", headers={"Authorization": f"Bearer {key}"}, retries=2, timeout=15)
    except ApiError as exc:
        return False, str(exc)
    if response.status_code == 200:
        return True, "Transcription API key accepted"
    return False, f"Provider rejected the key ({response.status_code}): {_error_text(response)}"


VALIDATORS = {"instagram": check_instagram, "tiktok": check_tiktok, "transcription": check_transcription}
