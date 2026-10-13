from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Workspace
from app.config import get_settings
from app.integrations import tiktok
from app.integrations.http import ApiError
from app.models import Job, JobStatus, Mode, TikTokAccount, TikTokStatus, User, Violation
from app.schemas import TikTokUpdate
from app.security import create_oauth_state, decrypt, oauth_state_claims
from app.services import activity, credentials, pipeline, rules, serializers, stats, tokens

router = APIRouter(tags=["tiktok"])
COLORS = ["blue", "orange", "pink", "violet", "green"]


def _default_cap(db, mode: str = Mode.SHORTS, user_id: int | None = None) -> int:
    return int(rules.global_values(db, mode, user_id)["uploads_per_tiktok_account_per_day"])


def _mine(db, account_id: int, user: User) -> TikTokAccount:
    account = db.get(TikTokAccount, account_id)
    if not account or account.user_id != user.id:
        raise HTTPException(404, "Account not found")
    return account


@router.get("/tiktok/oauth/start")
def oauth_start(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    s = get_settings()
    if not credentials.get("tiktok.client_key") or not credentials.get("tiktok.client_secret"):
        raise HTTPException(400, "TikTok app is not configured — the admin adds the client key and secret on the Integrations page")
    active = db.scalar(select(func.count(TikTokAccount.id)).where(TikTokAccount.status != TikTokStatus.REVOKED, TikTokAccount.user_id == user.id)) or 0
    if active >= s.max_tiktok_accounts:
        raise HTTPException(400, f"Limit of {s.max_tiktok_accounts} TikTok accounts reached")
    return {"url": tiktok.authorize_url(create_oauth_state("tiktok", user.id, mode=mode))}


@router.get("/tiktok/oauth/callback", include_in_schema=False)
def oauth_callback(db: DB, code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    site = get_settings().frontend_url.rstrip("/")
    mode = Mode.SHORTS

    def back(**params):
        # Back to the TikTok Accounts page of the workspace the connection was started from.
        prefix = "/podcasts" if mode == Mode.PODCASTS else ""
        return RedirectResponse(f"{site}{prefix}/tiktok?{urlencode(params)}")

    try:
        claims = oauth_state_claims(state or "", "tiktok")
        mode = claims.get("mode") if claims.get("mode") in Mode.ALL else Mode.SHORTS
        member_id = int(claims["sub"])  # the member who pressed Connect
    except Exception:
        return back(error="Invalid or expired OAuth state — please try again")
    if error or not code:
        return back(error=error_description or error or "TikTok authorization was cancelled")
    try:
        token_set = tiktok.exchange_code(code)
        info = tiktok.user_info(token_set.access_token)
    except ApiError as exc:
        activity.record(db, "OAuth", f"TikTok connection failed: {exc}", level="error", event="oauth_failed")
        db.commit()
        return back(error=str(exc))

    account = db.scalar(select(TikTokAccount).where(TikTokAccount.open_id == token_set.open_id))
    if account and account.status != TikTokStatus.REVOKED and account.user_id not in (None, member_id):
        return back(error="This TikTok account is already connected by another member")
    if not account:
        count = db.scalar(select(func.count(TikTokAccount.id)).where(TikTokAccount.status != TikTokStatus.REVOKED, TikTokAccount.user_id == member_id)) or 0
        if count >= get_settings().max_tiktok_accounts:
            return back(error="TikTok account limit reached")
        account = TikTokAccount(open_id=token_set.open_id, username="", color=COLORS[count % len(COLORS)])
        db.add(account)
    account.mode = mode  # connecting an account from the other workspace moves it here
    account.user_id = member_id
    account.username = (info.get("username") or info.get("display_name") or token_set.open_id[:12]).lstrip("@")
    account.display_name = info.get("display_name")
    account.avatar_url = info.get("avatar_url")
    tokens.store_tiktok_tokens(account, token_set)
    credentials.set_status(db, "tiktok", "valid")
    db.flush()
    waiting = pipeline.assign_waiting_jobs(db)  # videos that were waiting for an account can go out now
    activity.record(db, "OAuth", f"TikTok account @{account.username} connected" + (f" · {waiting} waiting video(s) assigned to it" if waiting else ""), event="tiktok_connected", user_id=member_id)
    db.commit()
    return back(connected=account.username)


@router.get("/tiktok-accounts")
def list_accounts(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    accounts = db.scalars(
        select(TikTokAccount).where(TikTokAccount.status != TikTokStatus.REVOKED, TikTokAccount.mode == mode, TikTokAccount.user_id == user.id).order_by(TikTokAccount.id)
    ).all()
    per = stats.account_stats(db, user_id=user.id)
    return {
        "items": [serializers.tiktok_account(a, per.get(a.id), _default_cap(db, mode, user.id)) for a in accounts],
        "capacity": get_settings().max_tiktok_accounts,
    }


@router.patch("/tiktok-accounts/{account_id}")
def update_account(account_id: int, body: TikTokUpdate, db: DB, user: CurrentUser):
    account = _mine(db, account_id, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    if "daily_cap" in body.model_fields_set and body.daily_cap is None:
        account.daily_cap = None  # back to the global rule
    db.commit()
    return serializers.tiktok_account(account, stats.account_stats(db, user_id=user.id).get(account.id), _default_cap(db, account.mode, account.user_id))


@router.delete("/tiktok-accounts/{account_id}", status_code=204)
def disconnect(account_id: int, db: DB, user: CurrentUser):
    account = _mine(db, account_id, user)
    try:
        if account.access_token_enc:
            tiktok.revoke(decrypt(account.access_token_enc) or "")
    except Exception:
        pass  # best effort — the account is removed locally regardless
    # Keep the row (history, unique video guard) but drop credentials.
    account.status = TikTokStatus.REVOKED
    account.access_token_enc = account.refresh_token_enc = None
    # Jobs that hadn't started uploading are cancelled.
    for job in db.scalars(select(Job).where(Job.tiktok_account_id == account.id, Job.status.in_(JobStatus.PENDING - {JobStatus.UPLOADING}))):
        job.status = JobStatus.CANCELLED
        job.error = "TikTok account disconnected"
    activity.record(db, "OAuth", f"TikTok account @{account.username} disconnected", event="tiktok_disconnected", user_id=user.id)
    db.commit()


@router.get("/tiktok-accounts/{account_id}/health")
def health(account_id: int, db: DB, user: CurrentUser):
    account = _mine(db, account_id, user)
    published = db.scalar(select(func.count(Job.id)).where(Job.tiktok_account_id == account.id, Job.posted_at.is_not(None))) or 0
    violations = db.scalars(select(Violation).where(Violation.tiktok_account_id == account.id).order_by(Violation.id.desc()).limit(50)).all()
    failed = db.scalar(select(func.count(Job.id)).where(Job.tiktok_account_id == account.id, Job.status == JobStatus.FAILED)) or 0
    rate = (1 - len(violations) / published) * 100 if published else 100.0
    score = "healthy" if rate >= 98 and account.status == TikTokStatus.ACTIVE else "at_risk" if rate >= 90 else "poor"
    return {
        "account": serializers.tiktok_account(account, stats.account_stats(db, user_id=user.id).get(account.id), _default_cap(db, account.mode, account.user_id)),
        "published": published,
        "failed": failed,
        "violation_count": len(violations),
        "compliance_rate": round(rate, 1),
        "health": score,
        "violations": [serializers.violation(v) for v in violations],
    }


@router.get("/tiktok-accounts/routes-preview")
def routes_preview(db: DB, user: CurrentUser, mode: Workspace = Mode.SHORTS):
    """Upcoming video → destination pairs (READY / awaiting approval jobs)."""
    jobs = db.scalars(
        select(Job)
        .where(Job.status.in_([JobStatus.READY, JobStatus.AWAITING_APPROVAL, JobStatus.UPLOADING]), Job.tiktok_account_id.is_not(None))
        .where(Job.tiktok_account_id.in_(select(TikTokAccount.id).where(TikTokAccount.mode == mode, TikTokAccount.user_id == user.id)))
        .order_by(Job.id)
        .limit(6)
    ).all()
    return [
        {"job_id": j.id, "title": j.rewritten_title or j.video.original_title, "video_id": j.video_id, "tiktok_account": serializers.tiktok_ref(j.tiktok_account), "status": j.status}
        for j in jobs
    ]
