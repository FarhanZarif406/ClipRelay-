from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, OwnerUser
from app.models import User
from app.schemas import RoleIn, UserCreate, UserOut
from app.security import hash_password
from app.services import activity

router = APIRouter(prefix="/users", tags=["users"])


def _owner_count(db) -> int:
    return db.scalar(select(func.count(User.id)).where(User.role == "owner", User.is_active.is_(True))) or 0


@router.get("", response_model=list[UserOut])
def list_users(db: DB, _: CurrentUser):
    return db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: DB, me: OwnerUser):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), name=body.name, workspace_name=me.workspace_name, role="member")
    db.add(user)
    activity.record(db, "Auth", f"{me.email} added team member {user.email}", event="user_created")
    db.commit()
    return user


@router.patch("/{user_id}/role", response_model=UserOut)
def set_role(user_id: int, body: RoleIn, db: DB, me: OwnerUser):
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(404, "User not found")
    if user.role == "owner" and body.role != "owner" and _owner_count(db) <= 1:
        raise HTTPException(400, "A workspace needs at least one owner — promote someone else first")
    if user.role != body.role:
        user.role = body.role
        activity.record(db, "Auth", f"{me.email} made {user.email} {'an owner' if body.role == 'owner' else 'a member'}", event="role_changed")
    db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: int, db: DB, me: OwnerUser):
    if user_id == me.id:
        raise HTTPException(400, "You cannot remove yourself")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.role == "owner" and _owner_count(db) <= 1:
        raise HTTPException(400, "You cannot remove the last owner")
    user.is_active = False
    activity.record(db, "Auth", f"{me.email} removed team member {user.email}", event="user_removed")
    db.commit()
