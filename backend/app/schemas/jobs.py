from pydantic import BaseModel, Field

from app.schemas.sources import PRIVACY_LEVELS


class JobUpdate(BaseModel):
    rewritten_title: str | None = Field(default=None, max_length=150)
    rewritten_caption: str | None = Field(default=None, max_length=2200)
    rewritten_tags: list[str] | None = None
    privacy_level: PRIVACY_LEVELS | None = None
    tiktok_account_id: int | None = None
