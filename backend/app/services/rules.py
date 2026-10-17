"""Pipeline rules: every rule is a row in `pipeline_settings`, read at job time, so a change applies to the next job.

Each rule has a built-in default, a global value, and an optional override per channel. A channel with no
override inherits the global value. Every change is recorded in `setting_changes` (who, when, old and new value).
"""

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, Mode, RuleChange, RuleSetting, User, Video


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
    "max_duration_seconds": Rule("int", 180, "Maximum duration (seconds)", "A video up to this length (or any YouTube Short) is short-form. Anything longer is skipped as long-form.", "Detection", 1, 3600),
    "min_duration_seconds": Rule("int", 5, "Minimum duration (seconds)", "Shorter uploads are skipped.", "Detection", 0, 600),
    "videos_per_channel_per_day": Rule("int", 3, "Videos per channel per day", "Further uploads from the same channel are held under Not Processed.", "Detection", 1, 100),
    "daily_limit_mode": Rule("choice", "match accounts", "Daily limit", '"Match accounts": the daily limits of your switched-on Buffer accounts added up. "Manual": the number below. Once it is used up, new uploads are recorded under Not Processed instead of being edited.', "Detection", choices=("match accounts", "manual"), per_channel=False),
    "daily_limit": Rule("int", 15, "Daily limit (manual)", "Videos taken into processing per day, across all channels, when the daily limit is manual or no Buffer account is switched on.", "Detection", 1, 10000, per_channel=False),
    "approval_required": Rule("bool", True, "Require approval", "On: every video waits in the review queue. Off: videos are published straight away.", "Publishing", per_channel=False),
    "cap_reset_timezone": Rule("timezone", "Asia/Karachi", "Timezone", "The day (for daily limits and reports) starts at midnight in this timezone.", "Publishing", per_channel=False),
    "hashtag_count": Rule("int", 8, "Hashtag count", "How many hashtags a caption gets.", "Caption", 0, 15),
    "fallback_hashtags": Rule("text", "fyp foryou viral trending shorts", "Fallback hashtags", "Used with the original title when the AI model fails.", "Caption", max=500),
    "file_retention_days": Rule("int", 1, "File retention (days)", "Days after publishing before the edited file is deleted (the original goes as soon as the edit is made). At most 3, so the server's disk never fills.", "Storage", 1, 3),
    "poll_interval_minutes": Rule("int", 5, "Polling interval (minutes)", "How often each channel's uploads are checked, in case a push notification is missed.", "Detection", 1, 1440, per_channel=False),
}

# The edit itself (shape, speed, sound, text, watermark) is not a rule: it is the editing look (app.services.looks).
# The Podcasts workspace has its own rules. They are stored under a "podcast." prefix, so the two
# workspaces never share a value. A few plumbing settings (timezone, publish mode, polling, retention)
# are not repeated: Podcasts reads them from the Shorts rules above.
PODCAST_PREFIX = "podcast."
MAX_RETENTION_DAYS = 3  # an older, longer value saved before this limit counts as 3
SHARED_WITH_PODCASTS = ("cap_reset_timezone", "poll_interval_minutes", "file_retention_days")
PODCAST_RULES: dict[str, Rule] = {
    "clips_per_video": Rule("int", 3, "Clips per podcast", "How many short clips are cut from each podcast.", "Clips", 1, 10),
    "clip_min_seconds": Rule("int", 30, "Shortest clip (seconds)", "A clip is never shorter than this.", "Clips", 10, 300),
    "clip_max_seconds": Rule("int", 60, "Longest clip (seconds)", "A clip is never longer than this.", "Clips", 15, 600),
    "min_source_duration_seconds": Rule("int", 300, "Shortest podcast (seconds)", "Uploads shorter than this are not podcasts and are skipped.", "Detection", 60, 14400),
    "videos_per_channel_per_day": Rule("int", 2, "Podcasts per channel per day", "Further podcasts from the same channel are held under Not Processed.", "Detection", 1, 50),
    "daily_limit_mode": Rule("choice", "match accounts", "Daily limit", '"Match accounts": the daily limits of your switched-on Buffer accounts added up, divided by the clips per podcast. "Manual": the number below. Once it is used up, new podcasts are recorded under Not Processed instead of being cut.', "Detection", choices=("match accounts", "manual"), per_channel=False),
    "daily_limit": Rule("int", 5, "Daily limit (manual)", "Podcasts taken into processing per day, across all channels, when the daily limit is manual or no Buffer account is switched on.", "Detection", 1, 1000, per_channel=False),
    "approval_required": Rule("bool", True, "Require approval", "On: every clip waits in the review queue. Off: clips are published straight away.", "Publishing", per_channel=False),
    "hashtag_count": Rule("int", 8, "Hashtag count", "How many hashtags a caption gets.", "Caption", 0, 15),
    "fallback_hashtags": Rule("text", "podcast clips fyp foryou viral", "Fallback hashtags", "Used with the clip title when the AI model fails.", "Caption", max=500),
}


def registry(mode: str = Mode.SHORTS) -> dict[str, Rule]:
    return PODCAST_RULES if mode == Mode.PODCASTS else RULES


def _stored(key: str, mode: str) -> str:
    return PODCAST_PREFIX + key if mode == Mode.PODCASTS else key


def clean(key: str, value: Any, mode: str = Mode.SHORTS) -> Any:
    """Validate one value and return it in its stored form. Raises ValueError with a readable message."""
    rule = registry(mode).get(key)
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


def _rows(db: Session, channel_id: int | None, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict[str, RuleSetting]:
    """Stored rows of one workspace, by rule key (without the storage prefix).

    Global rows belong to one member (`user_id`); a channel's overrides belong to the channel.
    """
    if channel_id is None:
        condition = RuleSetting.channel_id.is_(None) & (RuleSetting.user_id == user_id)  # `== None` renders IS NULL
    else:
        condition = RuleSetting.channel_id == channel_id
    known = registry(mode)
    out = {}
    for row in db.scalars(select(RuleSetting).where(condition)):
        podcast = row.key.startswith(PODCAST_PREFIX)
        key = row.key[len(PODCAST_PREFIX):] if podcast else row.key
        if podcast == (mode == Mode.PODCASTS) and key in known:
            out[key] = row
    return out


def global_values(db: Session, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict[str, Any]:
    """One member's own rules. A member who has changed nothing has the built-in defaults."""
    values = {key: rule.default for key, rule in RULES.items()}
    values.update({key: row.value for key, row in _rows(db, None, Mode.SHORTS, user_id).items()})
    if mode == Mode.PODCASTS:
        shared = {key: values[key] for key in SHARED_WITH_PODCASTS}
        values = {**shared, **{key: rule.default for key, rule in PODCAST_RULES.items()}}
        values.update({key: row.value for key, row in _rows(db, None, mode, user_id).items()})
    return _within_bounds(values, mode)


def _within_bounds(values: dict[str, Any], mode: str) -> dict[str, Any]:
    """A number saved before its rule's range was narrowed (file retention went from 365 days to 3) counts as the nearest allowed value."""
    for key, rule in {**RULES, **registry(mode)}.items():
        value = values.get(key)
        if rule.kind in ("int", "float") and isinstance(value, (int, float)) and not isinstance(value, bool):
            if rule.max is not None and value > rule.max:
                values[key] = type(value)(rule.max)
            elif rule.min is not None and value < rule.min:
                values[key] = type(value)(rule.min)
    return values


def channel_overrides(db: Session, channel_id: int, mode: str = Mode.SHORTS) -> dict[str, Any]:
    known = registry(mode)
    return _within_bounds({key: row.value for key, row in _rows(db, channel_id, mode).items() if known[key].per_channel}, mode)


def effective(db: Session, channel_id: int | None = None, mode: str = Mode.SHORTS, user_id: int | None = None) -> dict[str, Any]:
    """The rules that apply to one channel: its overrides on top of its member's own values."""
    values = global_values(db, mode, user_id)
    if channel_id is not None:
        values.update(channel_overrides(db, channel_id, mode))
    return values


def for_video(db: Session, video: Video) -> dict[str, Any]:
    """The rules that apply to one video: those of its workspace and its channel."""
    return effective(db, video.channel_id, video.mode, video.user_id)


def set_values(db: Session, changes: dict[str, Any], *, channel: Channel | None = None, user: User | None = None, mode: str | None = None) -> list[RuleChange]:
    """Apply changes to `user`'s own rules (or to one of their channels).

    A value of None removes a channel override, or resets a global value to its default.
    """
    mode = mode or (channel.mode if channel else Mode.SHORTS)
    owner = channel.user_id if channel else (user.id if user else None)
    known = registry(mode)
    cleaned = {}
    for key, value in changes.items():
        rule = known.get(key)
        if rule is None:
            raise ValueError(f"Unknown setting {key!r}")
        if channel is not None and not rule.per_channel:
            raise ValueError(f"{rule.label} can only be set globally")
        cleaned[key] = None if value is None else clean(key, value, mode)
    merged = {**effective(db, channel.id if channel else None, mode, owner), **{k: v for k, v in cleaned.items() if v is not None}}
    if {"min_duration_seconds", "max_duration_seconds"} & cleaned.keys() and merged["min_duration_seconds"] >= merged["max_duration_seconds"]:
        raise ValueError("Minimum duration must be lower than maximum duration")
    if {"clip_min_seconds", "clip_max_seconds"} & cleaned.keys() and merged["clip_min_seconds"] > merged["clip_max_seconds"]:
        raise ValueError("The shortest clip cannot be longer than the longest clip")

    channel_id = channel.id if channel else None
    rows = _rows(db, channel_id, mode, owner)
    recorded = []
    for key, value in cleaned.items():
        row = rows.get(key)
        # For the audit trail, "no row" reads as the default (global) or as None = inherits (channel).
        old = row.value if row else (known[key].default if channel is None else None)
        new = value if value is not None or channel is not None else known[key].default
        if value is None:
            if row:
                db.delete(row)
        elif row:
            row.value, row.updated_by = value, user.id if user else None
        else:
            db.add(RuleSetting(key=_stored(key, mode), value=value, scope="channel" if channel else "global", channel_id=channel_id, user_id=owner, updated_by=user.id if user else None))
        if old != new:
            change = RuleChange(
                key=_stored(key, mode), channel_id=channel_id, channel_name=channel.display_name if channel else None, user_id=owner,
                old_value=old, new_value=new, changed_by=user.id if user else None, changed_by_email=user.email if user else None,
            )
            db.add(change)
            recorded.append(change)
    db.flush()
    return recorded


def history(db: Session, *, channel_id: int | None = None, limit: int = 50, mode: str = Mode.SHORTS, user_id: int | None = None) -> list[dict]:
    stmt = select(RuleChange).where(RuleChange.user_id == user_id).order_by(RuleChange.id.desc()).limit(limit)
    podcast = RuleChange.key.startswith(PODCAST_PREFIX)
    stmt = stmt.where(podcast if mode == Mode.PODCASTS else ~podcast)
    if channel_id is not None:
        stmt = stmt.where(RuleChange.channel_id == channel_id)
    known = registry(mode)
    out = []
    for c in db.scalars(stmt):
        key = c.key.removeprefix(PODCAST_PREFIX)
        out.append({
            "id": c.id, "key": key, "label": known[key].label if key in known else key,
            "channel_id": c.channel_id, "channel_name": c.channel_name, "old_value": c.old_value, "new_value": c.new_value,
            "changed_by": c.changed_by_email, "changed_at": c.changed_at,
        })
    return out


def describe(mode: str = Mode.SHORTS) -> list[dict]:
    return [
        {
            "key": key, "kind": rule.kind, "default": rule.default, "label": rule.label, "help": rule.help, "group": rule.group,
            "min": rule.min, "max": rule.max, "choices": list(rule.choices), "per_channel": rule.per_channel,
        }
        for key, rule in registry(mode).items()
    ]
