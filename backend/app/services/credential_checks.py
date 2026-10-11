"""Validation for stored credentials. Each validator returns (ok, message):
ok=True valid · ok=False invalid · ok=None can't be verified yet (stays unverified)."""

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


def check_youtube(values: dict[str, str]) -> tuple[bool | None, str]:
    key = values.get("api_key", "")
    if not key:
        return False, "Paste a YouTube Data API key"
    try:
        response = request(
            "GET", "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "id", "id": "UCBR8-60-B28hp2BmDPdntcQ", "key": key}, retries=2, timeout=15,
        )
    except ApiError as exc:
        return False, str(exc)
    if response.status_code == 200:
        return True, "YouTube accepted the API key"
    return False, f"YouTube rejected the API key: {_error_text(response)}"


VALIDATORS = {"tiktok": check_tiktok, "youtube": check_youtube}


def check_smtp(values: dict[str, str]) -> tuple[bool | None, str]:
    import smtplib
    import socket

    from app.services import mailer

    if not values.get("host") or not values.get("from_address"):
        return False, "SMTP host and from address are required"
    if (values.get("security") or "starttls").lower() not in ("starttls", "ssl", "none"):
        return False, "Security must be starttls, ssl or none"
    try:
        mailer.check(values)
    except smtplib.SMTPAuthenticationError:
        return False, "The SMTP server rejected the username or password (Gmail needs an app password)"
    except (smtplib.SMTPException, OSError, socket.timeout, ValueError) as exc:
        return False, f"Could not connect to {values['host']}:{values.get('port') or 587}: {exc}"
    return True, "Connected and signed in to the SMTP server"


VALIDATORS["smtp"] = check_smtp


def run_daily(db) -> dict:
    """Re-validate stored credentials and AI models; alert ("Token problems") when one stops working."""
    from sqlalchemy import select

    from app.integrations import llm
    from app.models import LLMProvider, utcnow
    from app.services import activity, credentials, llm_registry, notify

    summary = {"checked": 0, "failed": []}
    for group, validator in VALIDATORS.items():
        saved = credentials.rows(db, group)
        if not saved:
            continue
        was_valid = all(r.status == "valid" for r in saved.values())
        values = {k.split(".", 1)[1]: credentials.get(k) for k in credentials.groups()[group]}
        ok, message = validator(values)
        summary["checked"] += 1
        credentials.set_status(db, group, "valid" if ok else "invalid" if ok is False else "unverified", None if ok else message)
        if ok is False:
            summary["failed"].append(group)
            activity.record(db, "Settings", f"Daily check: {group} credentials failed — {message[:200]}", level="error", event="credential_check_failed")
            if was_valid:
                notify.send(db, "token", f"{group.capitalize()} credentials stopped working: {message[:200]}")

    for row in db.scalars(select(LLMProvider)):
        was_valid = row.status == "valid"
        summary["checked"] += 1
        try:
            llm.list_models(llm_registry.to_config(row))
            row.status, row.last_error = "valid", None
        except (ApiError, RuntimeError) as exc:
            row.status, row.last_error = "invalid", str(exc)[:500]
            summary["failed"].append(f"llm:{row.label}")
            activity.record(db, "Settings", f"Daily check: AI model “{row.label}” failed — {str(exc)[:200]}", level="error", event="credential_check_failed")
            if was_valid:
                notify.send(db, "token", f"AI model “{row.label}” stopped working: {str(exc)[:200]}")
        row.last_tested_at = utcnow()
    db.flush()
    return summary
