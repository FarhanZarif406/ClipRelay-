from pydantic import BaseModel, Field


class NotificationsIn(BaseModel):
    webhook_url: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=255)
    notify_failures: bool | None = None
    notify_tokens: bool | None = None
