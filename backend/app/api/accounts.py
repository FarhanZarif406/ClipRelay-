"""The owner's panel: every account, its plan, and the plans themselves. Owners only, except "my plan"."""

import re
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, OwnerUser, Workspace
from app.integrations.buffer import BufferError
from app.models import Channel, Job, Mode, Plan, User, Video
from app.integrations import youtube
from app.security import decrypt, encrypt, hash_password
from app.services import activity, buffer, plans
from app.services.pipeline import cap_day_start
from app.services.rules import global_values

router = APIRouter(tags=["accounts"])
YOUTUBE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")


class AccountIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)
    plan_id: int | None = None  # None: the default plan
    plan_expires_at: datetime | None = None


class AccountChange(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    plan_id: int | None = None
    plan_expires_at: datetime | None = None
    suspended: bool | None = None


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=500)
    features: dict = Field(default_factory=dict)
    limits: dict = Field(default_factory=dict)
    is_default: bool = False


class KeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=60)


# ---------------------------------------------------------------- my plan (every account)

@router.get("/plan")
def my_plan(db: DB, user: CurrentUser):
    """What this account's plan allows, so the page can show what is locked."""
    return {**plans.effective(db, user), "definitions": plans.definitions(), "blocked": plans.blocked(db, user.id), "upgrade": plans.upgrade_map(db)}


# ---------------------------------------------------------------- accounts

def _account(db, account_id: int) -> User:
    user = db.get(User, account_id)
    if not user or not user.is_active:
        raise HTTPException(404, "Account not found")
    return user


def _view(db, user: User) -> dict:
    effective = plans.effective(db, user)
    since = cap_day_start(global_values(db, user_id=user.id).get("cap_reset_timezone") or "UTC")
    return {
        "id": user.id, "email": user.email, "name": user.name, "role": user.role, "suspended": user.suspended, "created_at": user.created_at,
        "plan_id": user.plan_id, "plan": effective["plan"], "plan_expires_at": user.plan_expires_at, "plan_expired": effective["expired"],
        "channels": db.scalar(select(func.count(Channel.id)).where(Channel.user_id == user.id)) or 0,
        "videos_today": db.scalar(select(func.count(Job.id)).join(Video, Job.video_id == Video.id).where(Video.user_id == user.id, Video.parent_id.is_(None), Job.created_at >= since)) or 0,
        "buffer_keys": len(buffer.keys(db, user.id)),
    }


def _plan_or_404(db, plan_id: int | None) -> None:
    if plan_id is not None and not db.get(Plan, plan_id):
        raise HTTPException(404, "Plan not found")


@router.get("/accounts")
def list_accounts(db: DB, _: OwnerUser):
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.role.desc(), User.id)).all()
    return [_view(db, user) for user in users]


@router.post("/accounts", status_code=201)
def create_account(body: AccountIn, db: DB, me: OwnerUser):
    if db.scalar(select(User).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(409, "This email already has an account")
    _plan_or_404(db, body.plan_id)
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), name=body.name, workspace_name=body.name or "My Workspace",
                role="member", plan_id=body.plan_id, plan_expires_at=body.plan_expires_at)
    db.add(user)
    db.flush()
    plans.start_trial(db, user)  # a free trial's end date, when the plan has trial days
    activity.record(db, "Accounts", f"{me.email} created the account {user.email} ({plans.effective(db, user)['plan']})", event="account_created")
    db.commit()
    return _view(db, user)


@router.patch("/accounts/{account_id}")
def change_account(account_id: int, body: AccountChange, db: DB, me: OwnerUser):
    user = _account(db, account_id)
    sent = body.model_fields_set
    if "suspended" in sent and body.suspended is not None:
        if user.id == me.id:
            raise HTTPException(400, "You cannot suspend your own account")
        user.suspended = body.suspended
        activity.record(db, "Accounts", f"{me.email} {'suspended' if body.suspended else 'reactivated'} {user.email}", event="account_suspended" if body.suspended else "account_reactivated")
    if "plan_id" in sent:
        _plan_or_404(db, body.plan_id)
        user.plan_id = body.plan_id
    if "plan_expires_at" in sent:
        user.plan_expires_at = body.plan_expires_at  # None: no end date
    if "plan_id" in sent or "plan_expires_at" in sent:
        activity.record(db, "Accounts", f"{me.email} set {user.email} to {plans.effective(db, user)['plan']}" + (f" until {user.plan_expires_at:%d %b %Y}" if user.plan_expires_at else ""), event="account_plan")
    if body.name is not None:
        user.name = body.name
    if body.password:
        user.password_hash = hash_password(body.password)
        activity.record(db, "Accounts", f"{me.email} set a new password for {user.email}", event="account_password")
    db.commit()
    return _view(db, user)


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: int, db: DB, me: OwnerUser):
    user = _account(db, account_id)
    if user.id == me.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.is_owner:
        raise HTTPException(400, "Make this owner a member first, then delete the account")
    user.is_active = False
    for channel in db.scalars(select(Channel).where(Channel.user_id == user.id)):
        channel.active = False  # nobody watches channels for an account that is gone
    activity.record(db, "Accounts", f"{me.email} deleted the account {user.email}", event="account_deleted")
    db.commit()


# ---------------------------------------------------------------- an account's Buffer keys, set by the owner for them

@router.get("/accounts/{account_id}/buffer")
def account_buffer(account_id: int, db: DB, _: OwnerUser, mode: Workspace = Mode.SHORTS):
    return buffer.status(db, _account(db, account_id).id, mode)


@router.post("/accounts/{account_id}/buffer/keys")
def account_add_key(account_id: int, body: KeyIn, db: DB, me: OwnerUser, mode: Workspace = Mode.SHORTS):
    user = _account(db, account_id)
    try:
        item = buffer.add_key(db, user.id, body.api_key.strip(), body.label)
    except BufferError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    activity.record(db, "Accounts", f"{me.email} added a Buffer key ({item.label}) for {user.email}", event="buffer_key_saved", user_id=user.id)
    db.commit()
    return buffer.status(db, user.id, mode)


@router.delete("/accounts/{account_id}/buffer/keys/{key_id}")
def account_remove_key(account_id: int, key_id: int, db: DB, me: OwnerUser, mode: Workspace = Mode.SHORTS):
    user = _account(db, account_id)
    item = next((k for k in buffer.keys(db, user.id) if k.id == key_id), None)
    if not item:
        raise HTTPException(404, "No such Buffer key")
    label = item.label
    buffer.remove_key(db, item)
    activity.record(db, "Accounts", f"{me.email} removed the Buffer key {label} of {user.email}", event="buffer_key_removed", user_id=user.id)
    db.commit()
    return buffer.status(db, user.id, mode)


# ---------------------------------------------------------------- plans

def _counts(db) -> dict[int, int]:
    return dict(db.execute(select(User.plan_id, func.count(User.id)).where(User.is_active.is_(True), User.role != "owner").group_by(User.plan_id)).all())


@router.get("/plans")
def list_plans(db: DB, _: OwnerUser):
    counts = _counts(db)
    default = plans.default_plan(db)
    rows = sorted(db.scalars(select(Plan)).all(), key=plans.tier_order)  # Free Trial, Bronze, Silver, Gold, Platinum
    # Accounts without a plan of their own are on the default one.
    return {"plans": [plans.view(p, counts.get(p.id, 0) + (counts.get(None, 0) if default and p.id == default.id else 0)) for p in rows], **plans.definitions()}


def _save_plan(db, plan: Plan, body: PlanIn) -> None:
    name = body.name.strip()
    if db.scalar(select(Plan.id).where(func.lower(Plan.name) == name.lower(), Plan.id != (plan.id or 0))):
        raise HTTPException(409, f"A plan called “{name}” already exists")
    try:
        plan.features, plan.limits = plans.clean(body.features, body.limits)
    except plans.PlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    plan.name, plan.description = name, body.description.strip()
    if body.is_default:
        for other in db.scalars(select(Plan).where(Plan.is_default.is_(True))):
            other.is_default = False
        plan.is_default = True


@router.post("/plans", status_code=201)
def create_plan(body: PlanIn, db: DB, me: OwnerUser):
    plan = Plan(name="", description="", features={}, limits={})
    _save_plan(db, plan, body)
    db.add(plan)
    activity.record(db, "Accounts", f"{me.email} created the plan {plan.name}", event="plan_created")
    db.commit()
    return list_plans(db, me)


@router.put("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanIn, db: DB, me: OwnerUser):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.is_default and not body.is_default:
        raise HTTPException(400, "Make another plan the default first")
    _save_plan(db, plan, body)
    activity.record(db, "Accounts", f"{me.email} changed the plan {plan.name}", event="plan_changed")
    db.commit()
    return list_plans(db, me)


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: int, db: DB, me: OwnerUser):
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    if plan.is_default:
        raise HTTPException(400, "The default plan cannot be deleted. Make another plan the default first")
    for user in db.scalars(select(User).where(User.plan_id == plan.id)):
        user.plan_id = None  # its accounts move to the default plan
    db.delete(plan)
    activity.record(db, "Accounts", f"{me.email} deleted the plan {plan.name}", event="plan_deleted")
    db.commit()
    return list_plans(db, me)


# ---------------------------------------------------------------- a member's own YouTube Data API key

class YouTubeKeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)


def _key_holder(db, user: User, for_user: int | None) -> User:
    """The account whose YouTube key a request is about: one's own, or (owners only) another account's."""
    if for_user is None or for_user == user.id:
        return user
    if not user.is_owner:
        raise HTTPException(403, "Only owners can manage another account's keys")
    return _account(db, for_user)


def _youtube_key_view(target: User) -> dict:
    key = (decrypt(target.youtube_api_key_enc) or "") if target.youtube_api_key_enc else ""
    # Owners use the shared key on the Integrations page; this one is for members.
    return {"has_key": bool(key), "key_last4": key[-4:] if len(key) > 8 else "", "shared": target.is_owner}


@router.get("/my-keys/youtube")
def my_youtube_key(db: DB, user: CurrentUser, for_user: int | None = None):
    return _youtube_key_view(_key_holder(db, user, for_user))


@router.put("/my-keys/youtube")
def save_my_youtube_key(body: YouTubeKeyIn, db: DB, user: CurrentUser, for_user: int | None = None):
    target = _key_holder(db, user, for_user)
    key = body.api_key.strip()
    if not YOUTUBE_KEY_RE.match(key):
        raise HTTPException(422, "That does not look like a YouTube Data API key.")
    checked = youtube.test_key(key)
    if not checked["ok"]:
        raise HTTPException(400, f"Google did not accept the key: {checked['message']}")
    target.youtube_api_key_enc = encrypt(key)
    activity.record(db, "Settings", f"{user.email} saved a YouTube Data API key" + (f" for {target.email}" if target.id != user.id else ""), event="credentials_saved", user_id=target.id)
    db.commit()
    return _youtube_key_view(target)


@router.delete("/my-keys/youtube")
def remove_my_youtube_key(db: DB, user: CurrentUser, for_user: int | None = None):
    target = _key_holder(db, user, for_user)
    target.youtube_api_key_enc = None
    activity.record(db, "Settings", f"{user.email} removed a YouTube Data API key" + (f" of {target.email}" if target.id != user.id else ""), event="credentials_removed", user_id=target.id)
    db.commit()
    return _youtube_key_view(target)
