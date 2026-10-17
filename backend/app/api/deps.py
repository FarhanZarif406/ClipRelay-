from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import decode_token

bearer = HTTPBearer(auto_error=False)
SUSPENDED = "Your account is suspended. Contact the owner."

DB = Annotated[Session, Depends(get_db)]


def user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_token(token)
        if payload.get("purpose"):
            raise jwt.InvalidTokenError("not an access token")
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        user = None
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    if user.suspended and not user.is_owner:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, SUSPENDED, headers={"WWW-Authenticate": "Bearer"})
    return user


def current_user(request: Request, db: DB, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    user = user_from_token(db, credentials.credentials)
    # The Podcasts workspace is a plan feature: every request of the Podcasts window carries ?mode=podcasts.
    if request.query_params.get("mode") == "podcasts" and not user.is_owner:
        from app.services import plans

        if not plans.effective(db, user)["features"]["podcasts"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "The Podcasts workspace is not part of your plan. Ask the owner to upgrade it.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owner_user(user: CurrentUser) -> User:
    if not user.is_owner:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only workspace owners can do this")
    return user


OwnerUser = Annotated[User, Depends(owner_user)]

# The Podcasts window adds ?mode=podcasts to every request; without it a request is about Shorts.
Workspace = Annotated[str, Query(alias="mode", pattern="^(shorts|podcasts)$")]
