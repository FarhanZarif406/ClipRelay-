from pydantic import BaseModel, Field, field_validator

HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class PolicyIn(BaseModel):
    automations_paused: bool | None = None
    name: str | None = Field(default=None, max_length=120)
    active_window_start: str | None = Field(default=None, pattern=HHMM)
    active_window_end: str | None = Field(default=None, pattern=HHMM)
    active_days: list[int] | None = None
    max_duration_sec: int | None = Field(default=None, ge=5, le=60)
    language_gate_enabled: bool | None = None
    allowed_languages: list[str] | None = None
    hourly_cap: int | None = Field(default=None, ge=1, le=60)
    random_delay_min_minutes: int | None = Field(default=None, ge=0, le=240)
    random_delay_max_minutes: int | None = Field(default=None, ge=0, le=240)
    timezone: str | None = None
    unique_video_per_account: bool | None = None
    default_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    max_videos_per_run: int | None = Field(default=None, ge=1, le=100)

    @field_validator("active_days")
    @classmethod
    def _days(cls, v):
        if v is not None and any(d not in range(7) for d in v):
            raise ValueError("days must be 0-6 (Monday=0)")
        return sorted(set(v)) if v is not None else v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown timezone {v!r}") from exc
        return v

    @field_validator("allowed_languages")
    @classmethod
    def _langs(cls, v):
        return [x.strip().lower() for x in v if x.strip()] if v is not None else v


class AuditIn(BaseModel):
    check_hours: list[float] | None = None
    auto_remove: bool | None = None
    notifications_enabled: bool | None = None

    @field_validator("check_hours")
    @classmethod
    def _hours(cls, v):
        if v is None:
            return v
        hours = sorted({float(h) for h in v})
        if not hours or hours[0] <= 0 or hours[-1] > 72 or len(hours) > 12:
            raise ValueError("provide 1-12 check times between 0 and 72 hours")
        return hours


class NotificationsIn(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=255)
    notify_violations: bool | None = None
    notify_failures: bool | None = None
    notify_tokens: bool | None = None
