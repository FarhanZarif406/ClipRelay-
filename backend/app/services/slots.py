"""Posting times: when the next clip can go out on a publishing account.

An account has times of day ("HH:MM", on its own clock), a daily limit and, optionally, a first day.
"""

import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEAD = timedelta(minutes=10)  # never closer to now than this, so the service has time to fetch the video
HORIZON_DAYS = 60  # how far ahead a free time is looked for
MAX_TIMES = 24


def is_day(value) -> bool:
    """Whether a value is a real calendar day written as "2026-10-20"."""
    if not isinstance(value, str) or not DAY_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def clean_times(times) -> list[str]:
    """Valid "HH:MM" only, no repeats, earliest first."""
    if not isinstance(times, list):
        return []
    return sorted({t for t in times if isinstance(t, str) and TIME_RE.match(t)})


def day_of(instant: datetime, zone: str) -> date:
    return instant.astimezone(ZoneInfo(zone)).date()


def zoned_instant(day: date, clock: str, zone: str) -> datetime:
    """The instant at which the clock in `zone` shows `day` and `clock`."""
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)


def next_slot(times: list[str], daily_limit: int, start_date: str | None, taken: list[datetime], now: datetime, zone: str) -> datetime | None:
    """The earliest of the account's times that is far enough ahead, not already given out, and on a day with room.

    `taken` holds the times already given out on the account. None when the account has no times, or nothing
    is free in the next two months.
    """
    times = clean_times(times)
    if not times or daily_limit < 1:
        return None
    per_day: dict[date, int] = {}
    for instant in taken:
        per_day[day_of(instant, zone)] = per_day.get(day_of(instant, zone), 0) + 1
    first = day_of(now, zone)
    if is_day(start_date) and date.fromisoformat(start_date) > first:
        first = date.fromisoformat(start_date)  # a start date still to come: the search begins on that day
    for offset in range(HORIZON_DAYS + 1):
        day = first + timedelta(days=offset)
        if per_day.get(day, 0) >= daily_limit:
            continue
        for clock in times:
            slot = zoned_instant(day, clock, zone)
            if slot < now + LEAD:
                continue
            if any(abs((instant - slot).total_seconds()) < 60 for instant in taken):
                continue  # two posts never share a time
            return slot
    return None


def taken_today(taken: list[datetime], now: datetime, zone: str) -> int:
    today = day_of(now, zone)
    return sum(1 for instant in taken if day_of(instant, zone) == today)
