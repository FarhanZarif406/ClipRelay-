from pydantic import BaseModel, Field, field_validator


class PolicyIn(BaseModel):
    tiktok_app_audited: bool | None = None


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
