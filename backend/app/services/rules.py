"""Pipeline rules: every rule is a row in `pipeline_settings`, read at job time, so a change applies to the next job.

Each rule has a built-in default, a global value, and an optional override per channel. A channel with no
override inherits the global value. Every change is recorded in `setting_changes` (who, when, old and new value).
"""

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, RuleChange, RuleSetting, User


@dataclass(frozen=True)
class Rule:
    kind: str  # float | int | bool | text | timezone | choice
    default: Any
    label: str
    help: str
    group: str
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()
    per_channel: bool = True


RULES: dict[str, Rule] = {
    "speed": Rule("float", 1.08, "Speed", "Video and audio are sped up together. 1.0 leaves the speed unchanged.", "Editing", 1.0, 1.5),
    "horizontal_flip": Rule("bool", True, "Horizontal flip", "Mirror the video left to right.", "Editing"),
    "keep_audio": Rule("bool", True, "Keep audio", "Keep the original audio track. Off removes the sound.", "Editing"),
    "max_duration_seconds": Rule("int", 180, "Maximum duration (seconds)", "A video up to this length (or any YouTube Short) is short-form. Anything longer is skipped as long-form.", "Detection", 1, 3600),
    "min_duration_seconds": Rule("int", 5, "Minimum duration (seconds)", "Shorter uploads are skipped.", "Detection", 0, 600),
    "videos_per_channel_per_day": Rule("int", 3, "Videos per channel per day", "Further uploads from the same channel are held as skipped.", "Detection", 1, 100),
    "approval_required": Rule("bool", True, "Require approval", "On: every video waits in the review queue. Off: videos are published straight away.", "Publishing", per_channel=False),
    "uploads_per_tiktok_account_per_day": Rule("int", 7, "Uploads per TikTok account per day", "Applies to every account that has no cap of its own.", "Publishing", 1, 100, per_channel=False),
    "publish_mode": Rule(
        "choice", "inbox", "Publish mode",
        "inbox: the video lands in the account's TikTok inbox and a person finishes the post in the app. direct: posted by the API (needs TikTok's audit).",
        "Publishing", choices=("inbox", "direct"), per_channel=False,
    ),
    "cap_reset_timezone": Rule("timezone", "Asia/Karachi", "Cap reset timezone", "Daily caps reset at midnight in this timezone.", "Publishing", per_channel=False),
    "hashtag_count": Rule("int", 8, "Hashtag count", "How many hashtags a caption gets.", "Caption", 0, 15),
    "fallback_hashtags": Rule("text", "fyp foryou viral trending shorts", "Fallback hashtags", "Used with the original title when the AI model fails.", "Caption", max=500),
    "file_retention_days": Rule("int", 7, "File retention (days)", "Days after publishing before the downloaded and rendered files are deleted.", "Storage", 1, 365),
    "poll_interval_minutes": Rule("int", 5, "Polling interval (minutes)", "How often each channel's uploads are checked, in case a push notification is missed.", "Detection", 1, 1440, per_channel=False),
}


def clean(key: str, value: Any) -> Any:
    """Validate one value and return it in its stored form. Raises ValueError with a readable message."""
    rule = RULES.get(key)
    if rule is None:
        raise ValueError(f"Unknown setting {key!r}")
    if rule.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{rule.label} must be on or off")
        return value
    if rule.kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{rule.label} must be a number")
        if rule.kind == "int":
            if int(value) != value:
                raise ValueError(f"{rule.label} must be a whole number")
            value = int(value)
        else:
            value = round(float(value), 3)
        if (rule.min is not None and value < rule.min) or (rule.max is not None and value > rule.max):
            raise ValueError(f"{rule.label} must be between {rule.min:g} and {rule.max:g}")
        return value
    if not isinstance(value, str):
        raise ValueError(f"{rule.label} must be text")
    value = value.strip()
    if rule.kind == "choice" and value not in rule.choices:
        raise ValueError(f"{rule.label} must be one of: {', '.join(rule.choices)}")
    if rule.kind == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone {value!r}") from exc
    if rule.kind == "text" and rule.max is not None and len(value) > rule.max:
        raise ValueError(f"{rule.label} must be at most {rule.max:g} characters")
    return value


def _rows(db: Session, channel_id: int | None) -> dict[str, RuleSetting]:
    condition = RuleSetting.channel_id.is_(None) if channel_id is None else RuleSetting.channel_id == channel_id
    return {row.key: row for row in db.scalars(select(RuleSetting).where(condition)) if row.key in RULES}


def global_values(db: Session) -> dict[str, Any]:
    values = {key: rule.default for key, rule in RULES.items()}
    values.update({key: row.value for key, row in _rows(db, None).items()})
    return values


def channel_overrides(db: Session, channel_id: int) -> dict[str, Any]:
    return {key: row.value for key, row in _rows(db, channel_id).items() if RULES[key].per_channel}


def effective(db: Session, channel_id: int | None = None) -> dict[str, Any]:
    """The rules that apply to one channel: its overrides on top of the global values."""
    values = global_values(db)
    if channel_id is not None:
        values.update(channel_overrides(db, channel_id))
    return values


def set_values(db: Session, changes: dict[str, Any], *, channel: Channel | None = None, user: User | None = None) -> list[RuleChange]:
    """Apply changes. A value of None removes a channel override, or resets a global value to its default."""
    cleaned = {}
    for key, value in changes.items():
        rule = RULES.get(key)
        if rule is None:
            raise ValueError(f"Unknown setting {key!r}")
        if channel is not None and not rule.per_channel:
            raise ValueError(f"{rule.label} can only be set globally")
        cleaned[key] = None if value is None else clean(key, value)
    if {"min_duration_seconds", "max_duration_seconds"} & cleaned.keys():
        merged = {**effective(db, channel.id if channel else None), **{k: v for k, v in cleaned.items() if v is not None}}
        if merged["min_duration_seconds"] >= merged["max_duration_seconds"]:
            raise ValueError("Minimum duration must be lower than maximum duration")

    channel_id = channel.id if channel else None
    rows = _rows(db, channel_id)
    recorded = []
    for key, value in cleaned.items():
        row = rows.get(key)
        # For the audit trail, "no row" reads as the default (global) or as None = inherits (channel).
        old = row.value if row else (RULES[key].default if channel is None else None)
        new = value if value is not None or channel is not None else RULES[key].default
        if value is None:
            if row:
                db.delete(row)
        elif row:
            row.value, row.updated_by = value, user.id if user else None
        else:
            db.add(RuleSetting(key=key, value=value, scope="channel" if channel else "global", channel_id=channel_id, updated_by=user.id if user else None))
        if old != new:
            change = RuleChange(
                key=key, channel_id=channel_id, channel_name=channel.display_name if channel else None,
                old_value=old, new_value=new, changed_by=user.id if user else None, changed_by_email=user.email if user else None,
            )
            db.add(change)
            recorded.append(change)
    db.flush()
    return recorded


def history(db: Session, *, channel_id: int | None = None, limit: int = 50) -> list[dict]:
    stmt = select(RuleChange).order_by(RuleChange.id.desc()).limit(limit)
    if channel_id is not None:
        stmt = stmt.where(RuleChange.channel_id == channel_id)
    return [
        {
            "id": c.id, "key": c.key, "label": RULES[c.key].label if c.key in RULES else c.key,
            "channel_id": c.channel_id, "channel_name": c.channel_name, "old_value": c.old_value, "new_value": c.new_value,
            "changed_by": c.changed_by_email, "changed_at": c.changed_at,
        }
        for c in db.scalars(stmt)
    ]


def describe() -> list[dict]:
    return [
        {
            "key": key, "kind": rule.kind, "default": rule.default, "label": rule.label, "help": rule.help, "group": rule.group,
            "min": rule.min, "max": rule.max, "choices": list(rule.choices), "per_channel": rule.per_channel,
        }
        for key, rule in RULES.items()
    ]
