from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.models import User
from app.schemas import UserCreate, UserOut
from app.security import hash_password
from app.services import activity

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: DB, _: CurrentUser):
    return db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DB, me: CurrentUser):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), name=body.name, workspace_name=me.workspace_name)
    db.add(user)
    activity.record(db, "Auth", f"{me.email} added team member {user.email}", event="user_created")
    db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: DB, me: CurrentUser):
    if user_id == me.id:
        raise HTTPException(400, "You cannot remove yourself")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = False
    activity.record(db, "Auth", f"{me.email} removed team member {user.email}", event="user_removed")
    db.commit()
