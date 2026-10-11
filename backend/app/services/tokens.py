"""Encrypted token storage + automatic refresh for TikTok."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations import tiktok
from app.integrations.http import ApiError, AuthError
from app.models import TikTokAccount, TikTokStatus, utcnow
from app.security import decrypt, encrypt
from app.services import activity, notify

TT_REFRESH_WINDOW = timedelta(minutes=30)
TT_EXPIRING_WINDOW = timedelta(days=3)


def store_tiktok_tokens(account: TikTokAccount, tokens: tiktok.TokenSet) -> None:
    account.access_token_enc = encrypt(tokens.access_token)
    account.refresh_token_enc = encrypt(tokens.refresh_token)
    account.token_expires_at = tokens.expires_at
    account.refresh_expires_at = tokens.refresh_expires_at
    account.scopes = tokens.scope
    account.status = TikTokStatus.ACTIVE
    account.last_error = None


def tiktok_token(db: Session, account: TikTokAccount) -> str:
    """Return a valid TikTok access token (24h lifetime), refreshing with the 365-day refresh token."""
    if account.status in (TikTokStatus.EXPIRED, TikTokStatus.REVOKED):
        raise AuthError(f"@{account.username} is {account.status} — reconnect it")
    now = utcnow()
    if not account.token_expires_at or account.token_expires_at - now < TT_REFRESH_WINDOW:
        try:
            store_tiktok_tokens(account, tiktok.refresh(decrypt(account.refresh_token_enc) or ""))
        except AuthError as exc:
            account.status = TikTokStatus.EXPIRED
            account.last_error = str(exc)
            activity.record(db, "OAuth", f"Access token expired for @{account.username}", level="error", event="token_expired")
            notify.send(db, "token", f"TikTok token expired for @{account.username}")
            raise
        activity.record(db, "OAuth", f"TikTok token refreshed for @{account.username}", event="token_refreshed")
    return decrypt(account.access_token_enc) or ""


def refresh_all(db: Session) -> dict:
    """Periodic job: keep tokens fresh and keep account status (Active/Expiring/Expired) accurate."""
    refreshed = failed = 0
    now = utcnow()
    for account in db.scalars(select(TikTokAccount).where(TikTokAccount.status != TikTokStatus.REVOKED)):
        if account.refresh_expires_at and account.refresh_expires_at <= now:
            if account.status != TikTokStatus.EXPIRED:
                account.status = TikTokStatus.EXPIRED
                activity.record(db, "OAuth", f"Refresh token expired for @{account.username}", level="error", event="token_expired")
            continue
        try:
            if account.status == TikTokStatus.EXPIRED:
                continue
            if account.token_expires_at and account.token_expires_at - now < TT_REFRESH_WINDOW:
                tiktok_token(db, account)
                refreshed += 1
            if account.refresh_expires_at and account.refresh_expires_at - now < TT_EXPIRING_WINDOW:
                account.status = TikTokStatus.EXPIRING
        except ApiError:
            failed += 1
    return {"refreshed": refreshed, "failed": failed}
