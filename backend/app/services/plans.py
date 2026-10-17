"""Plans: what each account may use.

An owner makes plans (Free, Pro, …), each with switches for features and numbers for limits, and gives every
account one, optionally until a date. An account without a plan, or whose plan has expired, has the default plan.
Owners themselves are never limited.
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Channel, Plan, User, utcnow

# key: (label, what it unlocks)
FEATURES: dict[str, tuple[str, str]] = {
    "podcasts": ("Podcasts workspace", "Cut long videos into short clips, in a workspace of their own."),
    "ai_captions": ("AI captions", "Titles, captions and hashtags written by the AI model. Without it the original title is used."),
    "ai_hook": ("AI hook text", "The hook line on the video written by the AI model. Without it the title is shown."),
    "background_music": ("Background music", "Music from the library under each video."),
    "watermark": ("Watermark", "The account's own logo on every video."),
    "custom_fonts": ("Own fonts", "Upload fonts for the hook text. Without it the built-in bold font is used."),
    "editing_presets": ("Editing presets", "Save several looks and give each channel its own."),
    "test_render": ("Test render", "Try the editing rules on a real video before saving."),
    "pc_editing": ("PC Helper editing", "Videos are downloaded and edited on the member's own computer by the PC Helper, free of the server's load."),
    "cloud_editing": ("Cloud editing", "When the member's PC is off or has no PC Helper, videos are edited in Google Cloud instead."),
    "full_editing": ("Full editing", "1080p, 60 fps, high-quality encoding, a rounded title box, and sharpness, grain, vignette, highlights and shadows. Without it videos are made in Fast mode: 720p, 30 fps, quick encoding."),
}
# Fast mode (without "Full editing"): the light edit a small server makes quickly.
FAST_ENCODING = {"resolution": "720x1280", "fps": 30, "preset": "superfast"}
FAST_PRESETS = ("ultrafast", "superfast", "veryfast")
HEAVY_ADJUST = {"sharpness": "Sharpness", "grain": "Grain", "vignette": "Vignette", "highlights": "Highlights", "shadows": "Shadows"}
# key: (label, help, upper bound). 0 means no limit.
LIMITS: dict[str, tuple[str, str, int]] = {
    "channels": ("Channels", "YouTube channels watched, both workspaces together.", 10000),
    "videos_per_day": ("Videos per day", "New videos taken into processing per day, in the Shorts workspace.", 100000),
    "podcasts_per_day": ("Podcasts per day", "Podcasts taken in per day, in the Podcasts workspace (each becomes several clips).", 1000),
    "buffer_keys": ("Buffer keys", "Buffer API keys the account may save (at most 10).", 10),
    "skipped_keep_hours": ("Keep skipped (hours)", "Skipped and not-processed videos are cleared from the server after this many hours. 0 = kept.", 8760),
    "trial_days": ("Trial days", "A new account on this plan works for this many days, then stops until the owner gives it a plan. 0 = no end.", 365),
    "auto_check_minutes": ("Auto-check (minutes)", "How often the account's channels are checked as a backup to push notifications. 0 = never: new videos come by push notification only.", 1440),
    "buffer_accounts": ("Buffer accounts", "Social accounts from Buffer the account may use, all its keys together. Any more in Buffer are not connected.", 1000),
}
FREE = {
    "features": {key: key in ("test_render", "pc_editing", "cloud_editing") for key in FEATURES},  # Fast mode, no extras
    "limits": {"channels": 2, "videos_per_day": 5, "buffer_keys": 1, "buffer_accounts": 3, "auto_check_minutes": 0},
}
FULL = {"features": {key: True for key in FEATURES}, "limits": {key: 0 for key in LIMITS}}


class PlanError(ValueError):
    """A plan or a plan change the owner asked for is not valid. The message is written for people."""


class PlanLimit(PermissionError):
    """The account's plan does not allow this. The message says so, for the page."""


def clean(features: dict | None, limits: dict | None) -> tuple[dict, dict]:
    """Known switches as booleans and known limits as whole numbers within bounds; anything else is dropped."""
    out_features = {key: bool((features or {}).get(key, False)) for key in FEATURES}
    out_limits = {}
    for key, (label, _help, upper) in LIMITS.items():
        value = (limits or {}).get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= upper:
            raise PlanError(f"{label} must be a whole number from 0 (no limit) to {upper}.")
        out_limits[key] = value
    return out_features, out_limits


def default_plan(db: Session) -> Plan | None:
    return db.scalar(select(Plan).where(Plan.is_default.is_(True)).order_by(Plan.id)) or db.scalar(select(Plan).order_by(Plan.id))


def expired(user: User, now: datetime | None = None) -> bool:
    return bool(user.plan_expires_at and user.plan_expires_at <= (now or utcnow()))


def plan_of(db: Session, user: User) -> Plan | None:
    """The account's own plan (also once it has ended: see `blocked`), else the default."""
    if user.plan_id:
        plan = db.get(Plan, user.plan_id)
        if plan:
            return plan
    return default_plan(db)


def blocked(db: Session, user_id: int | None) -> str | None:
    """Why an account may not work right now ("suspended" or "expired"), or None when it may.

    An account whose plan (a free trial or a paid plan) has ended can still sign in and look around, but nothing is
    detected, downloaded, edited or published for it until the owner gives it a plan again.
    """
    user = _user(db, user_id)
    if user is None or user.is_owner:
        return None
    if user.suspended or not user.is_active:
        return "suspended"
    return "expired" if user.plan_id and expired(user) else None


def bigger_by(db: Session, user: User, key: str) -> list[dict]:
    """The plans that allow more of one limit than the account's own, smallest first: [{"name", "value"}]. 0 counts as no limit."""
    current = effective(db, user)
    if current["owner"]:
        return []
    mine = current["limits"].get(key, 0)
    if not mine:
        return []  # already unlimited
    rows = [(p.name, int(p.limits.get(key) or 0)) for p in db.scalars(select(Plan)).all()]
    bigger = [(name, value) for name, value in rows if name != current["plan"] and (value == 0 or value > mine)]
    return [{"name": name, "value": value} for name, value in sorted(bigger, key=lambda r: r[1] or 10**9)]


def upgrade_map(db: Session) -> dict[str, str]:
    """For each feature, the smallest plan that includes it (fewest videos a day first), to show next to a locked option."""
    rows = sorted(db.scalars(select(Plan)).all(), key=lambda p: (int(p.limits.get("videos_per_day") or 0) or 10**9, p.id))
    out: dict[str, str] = {}
    for key in FEATURES:
        plan = next((p for p in rows if p.features.get(key)), None)
        if plan:
            out[key] = plan.name
    return out


def start_trial(db: Session, user: User) -> None:
    """A new account on a plan with trial days (or on the default plan, when that has them) gets its end date."""
    plan = db.get(Plan, user.plan_id) if user.plan_id else default_plan(db)
    days = int((plan.limits or {}).get("trial_days") or 0) if plan else 0
    if plan and days and user.plan_expires_at is None:
        from datetime import timedelta

        user.plan_id = plan.id
        user.plan_expires_at = utcnow() + timedelta(days=days)


def effective(db: Session, user: User | None) -> dict:
    """{"plan", "owner", "features", "limits", "expires_at", "expired"} for an account. Owners have everything."""
    if user is None or user.is_owner:
        return {"plan": "Owner", "owner": True, **FULL, "expires_at": None, "expired": False}
    plan = plan_of(db, user)
    features, limits = (plan.features, plan.limits) if plan else (FULL["features"], FULL["limits"])
    return {
        "plan": plan.name if plan else "No plan", "owner": False,
        "features": {key: bool(features.get(key, False)) for key in FEATURES},
        "limits": {key: int(limits.get(key, 0) or 0) for key in LIMITS},
        "expires_at": user.plan_expires_at if user.plan_id else None, "expired": expired(user) if user.plan_id else False,
    }


def _user(db: Session, user_id: int | None) -> User | None:
    return db.get(User, user_id) if user_id else None


def allows(db: Session, user_id: int | None, feature: str) -> bool:
    """Whether the account's plan has this feature switched on. Videos with no owner are not limited."""
    return effective(db, _user(db, user_id))["features"].get(feature, False)


def limit(db: Session, user_id: int | None, key: str) -> int:
    """The plan's number for this limit; 0 means no limit."""
    return effective(db, _user(db, user_id))["limits"].get(key, 0)


def auto_check_minutes(db: Session, user_id: int | None, rule_minutes: int) -> int | None:
    """How often an account's channels are checked as a backup to push notifications; None: never (push only).

    Owners, and accounts when no plans exist, use their polling rule. A plan's number is a floor: the rule can only
    make the checks rarer, never more frequent than the plan allows.
    """
    current = effective(db, _user(db, user_id))
    if current["owner"] or current["plan"] == "No plan":
        return rule_minutes
    minutes = current["limits"].get("auto_check_minutes", 0)
    return max(minutes, rule_minutes) if minutes else None


def require(db: Session, user: User, feature: str) -> None:
    if not effective(db, user)["features"].get(feature, False):
        raise PlanLimit(f"{FEATURES[feature][0]} is not part of your plan. Ask the owner to upgrade it.")


def check_channels(db: Session, user: User) -> None:
    most = limit(db, user.id, "channels")
    if most and (db.scalar(select(func.count(Channel.id)).where(Channel.user_id == user.id)) or 0) >= most:
        raise PlanLimit(f"Your plan allows {most} channel{'s' if most != 1 else ''}. Remove one, or ask the owner to upgrade your plan.")


def paid_parts(look: dict, features: dict) -> list[str]:
    """What in a look the account's plan does not include, by name. Empty when it may be saved."""
    out: list[str] = []
    hook, enc, adjust = look.get("hook") or {}, look.get("encoding") or {}, look.get("adjust") or {}
    if not features.get("full_editing"):
        if enc.get("resolution") != FAST_ENCODING["resolution"]:
            out.append("1080p resolution")
        if int(enc.get("fps") or 30) > 30:
            out.append(f"{enc.get('fps')} fps")
        if enc.get("preset") not in FAST_PRESETS:
            out.append(f"High-quality encoding ({enc.get('preset')})")
        box = hook.get("box") or {}
        if hook.get("enabled") and box.get("enabled") and (box.get("radius") or 0) > 0:
            out.append("Rounded title box")
        out += [label for key, label in HEAVY_ADJUST.items() if adjust.get(key)]
    if (look.get("music") or {}).get("enabled") and not features.get("background_music"):
        out.append("Background music")
    if (look.get("watermark") or {}).get("enabled") and not features.get("watermark"):
        out.append("Watermark")
    if hook.get("enabled") and str(hook.get("font", "")).startswith("custom:") and not features.get("custom_fonts"):
        out.append("Own fonts")
    if hook.get("enabled") and hook.get("source") == "ai" and not features.get("ai_hook"):
        out.append("AI hook text")
    return out


def check_look(db: Session, user: User, look: dict) -> None:
    """Refuse to save a look that uses what the plan does not include. Trying it out in the page is always allowed."""
    parts = paid_parts(look, effective(db, user)["features"])
    if parts:
        raise PlanLimit(f"These are for paid members: {', '.join(parts)}. Switch them off to save, or ask the owner to upgrade your plan.")


def fast_view(look: dict) -> dict:
    """A look as the editor first shows it to an account in Fast mode: its encoding and title box within the plan."""
    look = {section: dict(value) if isinstance(value, dict) else value for section, value in look.items()}
    look["encoding"] = {**look.get("encoding", {}), **FAST_ENCODING}
    if isinstance(look.get("hook"), dict) and isinstance(look["hook"].get("box"), dict):
        look["hook"] = {**look["hook"], "box": {**look["hook"]["box"], "radius": 0}}
    return look


def light_look(look: dict) -> dict:
    """The look a Fast-mode video is made with: 720p, at most 30 fps, quick encoding, a square title box, no heavy filters."""
    look = fast_view(look)
    look["encoding"]["fps"] = min(int((look.get("encoding") or {}).get("fps") or 30), 30)
    look["adjust"] = {**(look.get("adjust") or {}), **{key: 0 for key in HEAVY_ADJUST}}
    return look


def view(plan: Plan, accounts: int = 0) -> dict:
    return {
        "id": plan.id, "name": plan.name, "description": plan.description, "is_default": plan.is_default,
        "features": {key: bool(plan.features.get(key, False)) for key in FEATURES},
        "limits": {key: int(plan.limits.get(key, 0) or 0) for key in LIMITS}, "accounts": accounts,
    }


def definitions() -> dict:
    return {
        "features": [{"key": key, "label": label, "help": help_} for key, (label, help_) in FEATURES.items()],
        "limits": [{"key": key, "label": label, "help": help_, "max": upper} for key, (label, help_, upper) in LIMITS.items()],
    }
