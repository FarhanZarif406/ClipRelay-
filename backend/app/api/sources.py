import re
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.integrations import instagram
from app.integrations.http import ApiError
from app.models import InstagramSource, PromptTemplate, TikTokAccount, utcnow
from app.schemas import BulkAddIn, BulkUpdateIn, SourceUpdate
from app.security import create_oauth_state, encrypt, verify_oauth_state
from app.services import activity, credentials, dispatch, serializers, workspace_settings

router = APIRouter(tags=["instagram"])
COLORS = ["blue", "orange", "pink", "green", "violet"]
USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")


def _get(db, source_id: int) -> InstagramSource:
    source = db.get(InstagramSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


# ------------------------------------------------------------------ OAuth

@router.get("/instagram/oauth/start")
def oauth_start(user: CurrentUser):
    if not credentials.get("instagram.app_id") or not credentials.get("instagram.app_secret"):
        raise HTTPException(400, "Instagram app is not configured — add the App ID and secret in Settings → API keys")
    return {"url": instagram.authorize_url(create_oauth_state("instagram", user.id))}


@router.get("/instagram/oauth/callback", include_in_schema=False)
def oauth_callback(db: DB, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    front = f"{get_settings().frontend_url.rstrip('/')}/sources"

    def back(**params):
        return RedirectResponse(f"{front}?{urlencode(params)}")

    if error or not code or not state:
        return back(error=error_description or error or "Instagram authorization was cancelled")
    try:
        verify_oauth_state(state, "instagram")
    except Exception:
        return back(error="Invalid or expired OAuth state — please try again")
    try:
        token = instagram.exchange_code(code.removesuffix("#_"))
        profile = instagram.get_profile(token.access_token)
    except ApiError as exc:
        activity.record(db, "OAuth", f"Instagram connection failed: {exc}", level="error", event="oauth_failed")
        db.commit()
        return back(error=str(exc))

    credentials.set_status(db, "instagram", "valid")  # the code exchange succeeded, so the app ID/secret work
    account_type = str(profile.get("account_type") or "").upper()
    if account_type not in ("BUSINESS", "MEDIA_CREATOR"):
        activity.record(db, "OAuth", f"Instagram account @{profile.get('username', '?')} rejected: account type {account_type or 'unknown'}", level="warning", event="oauth_rejected")
        db.commit()
        return back(error="This Instagram account must be Business or Creator. Switch it in Instagram → Settings → Account type and tools.")

    ig_user_id = str(profile.get("user_id") or profile.get("id"))
    source = db.scalar(select(InstagramSource).where(InstagramSource.ig_user_id == ig_user_id))
    if not source:
        if db.scalar(select(func.count(InstagramSource.id))) >= get_settings().max_instagram_sources:
            return back(error="Instagram source limit reached")
        policy = workspace_settings.get(db, "policy")
        count = db.scalar(select(func.count(InstagramSource.id))) or 0
        source = InstagramSource(
            ig_user_id=ig_user_id,
            username=profile["username"].lower(),
            color=COLORS[count % len(COLORS)],
            refresh_interval_minutes=policy["default_interval_minutes"],
            is_active=True,
            next_run_at=utcnow(),
        )
        db.add(source)
    source.username = profile["username"].lower()
    source.name = profile.get("name")
    source.profile_picture_url = profile.get("profile_picture_url")
    source.access_token_enc = encrypt(token.access_token)
    source.token_expires_at = token.expires_at
    source.token_refreshed_at = utcnow()
    source.last_error = None
    source.needs_reconnect = False
    credentials.set_status(db, "instagram", "valid")  # a completed OAuth exchange proves the app ID/secret
    db.flush()
    activity.record(db, "OAuth", f"Instagram account @{source.username} connected", event="instagram_connected")
    db.commit()
    return back(connected=source.username)


# ------------------------------------------------------------------ Sources

@router.get("/sources")
def list_sources(
    db: DB,
    _: CurrentUser,
    q: str | None = None,
    status: str | None = Query(None, pattern="^(active|paused|error)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    stmt = select(InstagramSource)
    if q:
        stmt = stmt.where(or_(InstagramSource.username.ilike(f"%{q.lstrip('@')}%"), InstagramSource.name.ilike(f"%{q}%")))
    if status == "active":
        stmt = stmt.where(InstagramSource.is_active.is_(True))
    elif status == "paused":
        stmt = stmt.where(InstagramSource.is_active.is_(False))
    elif status == "error":
        stmt = stmt.where(InstagramSource.last_error.is_not(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(InstagramSource.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [serializers.source(s) for s in items],
        "total": total,
        "connected": db.scalar(select(func.count(InstagramSource.id))),
        "capacity": get_settings().max_instagram_sources,
    }


def parse_entry(entry: str) -> tuple[str, str] | None:
    """Return ('username'|'id', value) for '@name', 'name', or an instagram.com profile link."""
    value = entry.strip()
    if not value:
        return None
    if "instagram.com" in value or value.startswith("http"):
        url = urlparse(value if value.startswith("http") else f"https://{value}")
        parts = [p for p in url.path.split("/") if p]
        if not parts:
            return None
        if parts[0] == "profile" and len(parts) > 1:
            return ("id", parts[1])
        value = parts[0]
    value = value.lstrip("@").lower()
    if value.isdigit():
        return ("id", value)
    return ("username", value) if USERNAME_RE.match(value) else None


@router.post("/sources/bulk")
def bulk_add(body: BulkAddIn, db: DB, user: CurrentUser):
    """Activate up to 30 authorized Instagram accounts by username/profile link.

    Only accounts that completed Instagram OAuth with this app can be monitored (official Graph API);
    others are returned in `not_authorized` along with an authorization link.
    """
    activated, already, not_authorized, invalid = [], [], [], []
    seen = set()
    for raw in body.entries:
        parsed = parse_entry(raw)
        if not parsed:
            invalid.append(raw)
            continue
        kind, value = parsed
        if (kind, value) in seen:
            continue
        seen.add((kind, value))
        column = InstagramSource.username if kind == "username" else InstagramSource.ig_user_id
        source = db.scalar(select(InstagramSource).where(column == value))
        if not source:
            not_authorized.append(raw.strip())
        elif source.is_active:
            already.append(source.username)
        else:
            source.is_active = True
            source.next_run_at = utcnow()
            activated.append(source.username)
    if activated:
        activity.record(db, "Instagram", f"{len(activated)} sources activated: " + ", ".join(f"@{u}" for u in activated[:5]), event="sources_activated")
    db.commit()
    authorize = None
    if not_authorized and credentials.get("instagram.app_id"):
        authorize = instagram.authorize_url(create_oauth_state("instagram", user.id))
    return {"activated": activated, "already_active": already, "not_authorized": not_authorized, "invalid": invalid, "authorize_url": authorize}


def _apply_update(db, source: InstagramSource, body: SourceUpdate) -> None:
    if body.is_active is not None and body.is_active != source.is_active:
        source.is_active = body.is_active
        if body.is_active:
            source.next_run_at = utcnow()
        activity.record(db, "Scheduler", f"Source @{source.username} {'resumed' if body.is_active else 'paused'}", event="source_toggled")
    if body.refresh_interval_minutes is not None and body.refresh_interval_minutes != source.refresh_interval_minutes:
        source.refresh_interval_minutes = body.refresh_interval_minutes
        base = source.last_checked_at or utcnow()
        source.next_run_at = max(utcnow(), base + timedelta(minutes=body.refresh_interval_minutes))
    if body.approval_mode:
        source.approval_mode = body.approval_mode
    if body.clear_prompt_template:
        source.prompt_template_id = None
    elif body.prompt_template_id is not None:
        if not db.get(PromptTemplate, body.prompt_template_id):
            raise HTTPException(404, "Prompt template not found")
        source.prompt_template_id = body.prompt_template_id
    if body.tiktok_account_ids is not None:
        accounts = db.scalars(select(TikTokAccount).where(TikTokAccount.id.in_(body.tiktok_account_ids))).all()
        if len(accounts) != len(set(body.tiktok_account_ids)):
            raise HTTPException(404, "TikTok account not found")
        source.tiktok_accounts = list(accounts)


@router.patch("/sources/{source_id}")
def update_source(source_id: int, body: SourceUpdate, db: DB, _: CurrentUser):
    source = _get(db, source_id)
    _apply_update(db, source, body)
    db.commit()
    db.refresh(source)
    return serializers.source(source)


@router.post("/sources/bulk-update")
def bulk_update(body: BulkUpdateIn, db: DB, _: CurrentUser):
    sources = db.scalars(select(InstagramSource).where(InstagramSource.id.in_(body.ids))).all()
    for source in sources:
        if body.action == "delete":
            db.delete(source)
        elif body.action == "assign":
            if body.tiktok_account_ids is None:
                raise HTTPException(422, "tiktok_account_ids is required for assign")
            _apply_update(db, source, SourceUpdate(tiktok_account_ids=body.tiktok_account_ids))
        else:
            _apply_update(db, source, SourceUpdate(is_active=body.action == "resume"))
    if body.action == "delete":
        activity.record(db, "Instagram", f"{len(sources)} sources deleted", event="sources_deleted")
    db.commit()
    return {"updated": len(sources)}


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: DB, _: CurrentUser):
    source = _get(db, source_id)
    activity.record(db, "Instagram", f"Source @{source.username} deleted", event="source_deleted")
    db.delete(source)
    db.commit()


@router.post("/sources/{source_id}/run", status_code=202)
def run_now(source_id: int, db: DB, _: CurrentUser):
    source = _get(db, source_id)
    source.next_run_at = utcnow() + timedelta(minutes=source.refresh_interval_minutes)
    activity.record(db, "Scheduler", f"Manual run started for @{source.username}", event="run_now")
    db.commit()
    dispatch.run_source(source.id, manual=True)
    return {"queued": [source.id]}


@router.post("/runs", status_code=202)
def run_all(db: DB, _: CurrentUser):
    sources = db.scalars(select(InstagramSource).where(InstagramSource.is_active.is_(True))).all()
    now = utcnow()
    for source in sources:
        source.next_run_at = now + timedelta(minutes=source.refresh_interval_minutes)
    activity.record(db, "Scheduler", f"Automation started · scanning {len(sources)} Instagram sources", event="run_all")
    db.commit()
    for source in sources:
        dispatch.run_source(source.id, manual=True)
    return {"queued": [s.id for s in sources]}
