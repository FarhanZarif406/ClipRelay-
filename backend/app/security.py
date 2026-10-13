from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(subject: str, expires_minutes: int | None = None, **claims) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {"sub": subject, "exp": expire, **claims}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise RuntimeError("ENCRYPTION_KEY is not set. Generate one with `python -m app.cli gen-key`.")
    return Fernet(key.encode())


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt stored token — has ENCRYPTION_KEY changed?") from exc


def create_oauth_state(provider: str, user_id: int, **claims) -> str:
    """Signed, short-lived OAuth `state` value (CSRF protection without a DB table)."""
    return create_access_token(str(user_id), expires_minutes=15, purpose=f"oauth:{provider}", **claims)


def oauth_state_claims(state: str, provider: str) -> dict:
    payload = decode_token(state)
    if payload.get("purpose") != f"oauth:{provider}":
        raise jwt.InvalidTokenError("state purpose mismatch")
    return payload


def verify_oauth_state(state: str, provider: str) -> int:
    payload = decode_token(state)
    if payload.get("purpose") != f"oauth:{provider}":
        raise jwt.InvalidTokenError("state purpose mismatch")
    return int(payload["sub"])
