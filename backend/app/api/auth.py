from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, hash_password, verify_password
from app.services import activity

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: DB):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return TokenOut(access_token=create_access_token(str(user.id)), user=UserOut.model_validate(user))


@router.get("/setup")
def setup_state(db: DB):
    """Lets the login page offer 'create the first account' on a fresh install."""
    has_users = bool(db.scalar(select(func.count(User.id))))
    return {"has_users": has_users, "registration_open": not has_users or get_settings().allow_registration}


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, db: DB):
    has_users = bool(db.scalar(select(func.count(User.id))))
    if has_users and not get_settings().allow_registration:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Registration is closed — ask an existing member to invite you")
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), name=body.name, workspace_name=body.workspace_name)
    db.add(user)
    db.flush()
    activity.record(db, "Auth", f"User {user.email} registered", event="user_registered")
    db.commit()
    return TokenOut(access_token=create_access_token(str(user.id)), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return user
