from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.integrations import tiktok
from app.integrations.http import ApiError
from app.models import Job, JobStatus, TikTokAccount, TikTokStatus, Violation
from app.schemas import TikTokUpdate
from app.security import create_oauth_state, decrypt, verify_oauth_state
from app.services import activity, serializers, stats, tokens

router = APIRouter(tags=["tiktok"])
COLORS = ["blue", "orange", "pink", "violet", "green"]


@router.get("/tiktok/oauth/start")
def oauth_start(db: DB, user: CurrentUser):
    s = get_settings()
    if not s.tiktok_client_key or not s.tiktok_client_secret:
        raise HTTPException(400, "TikTok app is not configured (TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET)")
    active = db.scalar(select(func.count(TikTokAccount.id)).where(TikTokAccount.status != TikTokStatus.REVOKED)) or 0
    if active >= s.max_tiktok_accounts:
        raise HTTPException(400, f"Limit of {s.max_tiktok_accounts} TikTok accounts reached")
    return {"url": tiktok.authorize_url(create_oauth_state("tiktok", user.id))}


@router.get("/tiktok/oauth/callback", include_in_schema=False)
def oauth_callback(db: DB, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    front = f"{get_settings().frontend_url.rstrip('/')}/tiktok"

    def back(**params):
        return RedirectResponse(f"{front}?{urlencode(params)}")

    if error or not code or not state:
        return back(error=error_description or error or "TikTok authorization was cancelled")
    try:
        verify_oauth_state(state, "tiktok")
    except Exception:
        return back(error="Invalid or expired OAuth state — please try again")
    try:
        token_set = tiktok.exchange_code(code)
        info = tiktok.user_info(token_set.access_token)
    except ApiError as exc:
        activity.record(db, "OAuth", f"TikTok connection failed: {exc}", level="error", event="oauth_failed")
        db.commit()
        return back(error=str(exc))

    account = db.scalar(select(TikTokAccount).where(TikTokAccount.open_id == token_set.open_id))
    if not account:
        count = db.scalar(select(func.count(TikTokAccount.id)).where(TikTokAccount.status != TikTokStatus.REVOKED)) or 0
        if count >= get_settings().max_tiktok_accounts:
            return back(error="TikTok account limit reached")
        account = TikTokAccount(open_id=token_set.open_id, username="", color=COLORS[count % len(COLORS)])
        db.add(account)
    account.username = (info.get("username") or info.get("display_name") or token_set.open_id[:12]).lstrip("@")
    account.display_name = info.get("display_name")
    account.avatar_url = info.get("avatar_url")
    tokens.store_tiktok_tokens(account, token_set)
    db.flush()
    activity.record(db, "OAuth", f"TikTok account @{account.username} connected", event="tiktok_connected")
    db.commit()
    return back(connected=account.username)


@router.get("/tiktok-accounts")
def list_accounts(db: DB, _: CurrentUser):
    accounts = db.scalars(
        select(TikTokAccount).where(TikTokAccount.status != TikTokStatus.REVOKED).order_by(TikTokAccount.id)
    ).all()
    per = stats.account_stats(db)
    return {
        "items": [serializers.tiktok_account(a, per.get(a.id)) for a in accounts],
        "capacity": get_settings().max_tiktok_accounts,
    }


@router.patch("/tiktok-accounts/{account_id}")
def update_account(account_id: int, body: TikTokUpdate, db: DB, _: CurrentUser):
    account = db.get(TikTokAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    db.commit()
    return serializers.tiktok_account(account, stats.account_stats(db).get(account.id))


@router.delete("/tiktok-accounts/{account_id}", status_code=204)
def disconnect(account_id: int, db: DB, _: CurrentUser):
    account = db.get(TikTokAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    try:
        if account.access_token_enc:
            tiktok.revoke(decrypt(account.access_token_enc) or "")
    except Exception:
        pass  # best effort — the account is removed locally regardless
    # Keep the row (history, unique video guard) but drop credentials and links.
    account.status = TikTokStatus.REVOKED
    account.access_token_enc = account.refresh_token_enc = None
    account.sources = []
    # Jobs that hadn't started uploading are cancelled.
    for job in db.scalars(select(Job).where(Job.tiktok_account_id == account.id, Job.status.in_(JobStatus.PENDING - {JobStatus.UPLOADING}))):
        job.status = JobStatus.CANCELLED
        job.error = "TikTok account disconnected"
    activity.record(db, "OAuth", f"TikTok account @{account.username} disconnected", event="tiktok_disconnected")
    db.commit()


@router.get("/tiktok-accounts/{account_id}/health")
def health(account_id: int, db: DB, _: CurrentUser):
    account = db.get(TikTokAccount, account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    published = db.scalar(select(func.count(Job.id)).where(Job.tiktok_account_id == account.id, Job.posted_at.is_not(None))) or 0
    violations = db.scalars(select(Violation).where(Violation.tiktok_account_id == account.id).order_by(Violation.id.desc()).limit(50)).all()
    failed = db.scalar(select(func.count(Job.id)).where(Job.tiktok_account_id == account.id, Job.status == JobStatus.FAILED)) or 0
    rate = (1 - len(violations) / published) * 100 if published else 100.0
    score = "healthy" if rate >= 98 and account.status == TikTokStatus.ACTIVE else "at_risk" if rate >= 90 else "poor"
    return {
        "account": serializers.tiktok_account(account, stats.account_stats(db).get(account.id)),
        "published": published,
        "failed": failed,
        "violation_count": len(violations),
        "compliance_rate": round(rate, 1),
        "health": score,
        "violations": [serializers.violation(v) for v in violations],
    }


@router.get("/tiktok-accounts/routes-preview")
def routes_preview(db: DB, _: CurrentUser):
    """Upcoming unique video → destination pairs (READY / awaiting approval jobs)."""
    jobs = db.scalars(
        select(Job)
        .where(Job.status.in_([JobStatus.READY, JobStatus.AWAITING_APPROVAL, JobStatus.UPLOADING]), Job.tiktok_account_id.is_not(None))
        .order_by(Job.id)
        .limit(6)
    ).all()
    return [
        {"job_id": j.id, "title": j.rewritten_title or j.video.original_title, "source": serializers.source_ref(j.video.source), "video_id": j.video_id, "tiktok_account": serializers.tiktok_ref(j.tiktok_account), "status": j.status}
        for j in jobs
    ]
