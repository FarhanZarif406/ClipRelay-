"""The daily limit: how many new uploads a member's workspace takes into processing in one day.

By default it matches the Buffer accounts: the daily limits of the switched-on accounts added up (10 accounts
posting 7 a day take 70 videos). A podcast becomes several clips, so in Podcasts that sum is divided by the clips
cut from each podcast. With no account switched on, or set by hand, the member's own number applies.

Once the day's limit is used up, new uploads are still detected and recorded but not downloaded or edited: they
are held as "not processed" with the reason, and can be processed by hand. The count starts again at midnight in
the member's timezone.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BufferChannel, Job, Mode, SkipReason, Video
from app.services import plans, rules
from app.services.pipeline import cap_day_start

# Skips of a video that was fine to use but came over a limit; the rest (too long, too short, …) are filters.
LIMIT_REASONS = (SkipReason.DAILY_LIMIT, SkipReason.CHANNEL_CAP, SkipReason.ACCOUNT_CAP)
AUTO = "match accounts"


def used_today(db: Session, user_id: int | None, mode: str, zone: str) -> int:
    """Uploads that entered processing today: each one has its job, made the moment it was taken."""
    since = cap_day_start(zone)
    return db.scalar(
        select(func.count(Job.id)).join(Video, Job.video_id == Video.id).where(
            Video.user_id == user_id, Video.mode == mode, Video.parent_id.is_(None), Job.created_at >= since,
        )
    ) or 0


def status(db: Session, user_id: int | None, mode: str) -> dict:
    """Today's limit, how much of it is used, and where the number comes from."""
    values = rules.global_values(db, mode, user_id)
    zone = values["cap_reset_timezone"]
    accounts = list(db.scalars(select(BufferChannel).where(BufferChannel.user_id == user_id, BufferChannel.mode == mode, BufferChannel.enabled.is_(True), BufferChannel.key_id.is_not(None)))) if user_id else []
    posts = sum(max(0, c.daily_limit) for c in accounts)
    automatic = values["daily_limit_mode"] == AUTO and posts > 0
    if automatic:
        limit = max(1, posts // max(1, int(values["clips_per_video"]))) if mode == Mode.PODCASTS else posts
    else:
        limit = int(values["daily_limit"])
    capped = plans.limit(db, user_id, "podcasts_per_day" if mode == Mode.PODCASTS else "videos_per_day")  # the plan caps it, whatever the rule says
    by_plan = bool(capped and capped < limit)
    if by_plan:
        limit = capped
    used = used_today(db, user_id, mode, zone)
    return {
        "limit": limit, "used": used, "remaining": max(0, limit - used), "reached": used >= limit,
        "source": "plan" if by_plan else "accounts" if automatic else "manual", "accounts": len(accounts), "account_posts": posts,
        "set_to_match": values["daily_limit_mode"] == AUTO, "time_zone": zone, "resets_at": cap_day_start(zone) + timedelta(days=1),
    }


def check(db: Session, user_id: int | None, mode: str) -> tuple[str, str] | None:
    """The skip for a new upload when today's limit is used up, else None."""
    today = status(db, user_id, mode)
    if not today["reached"]:
        return None
    where = {"accounts": f"from your {today['accounts']} Buffer account{'s' if today['accounts'] != 1 else ''}", "plan": "your plan's limit"}.get(today["source"], "set by hand")
    noun = "podcasts" if mode == Mode.PODCASTS else "videos"
    return SkipReason.DAILY_LIMIT, f"Daily limit reached: {today['used']} of {today['limit']} {noun} already taken today ({where})"
