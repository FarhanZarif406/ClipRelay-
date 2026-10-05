from typing import Literal

from pydantic import BaseModel, Field

PRIVACY_LEVELS = Literal["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]


class SourceUpdate(BaseModel):
    is_active: bool | None = None
    refresh_interval_minutes: int | None = Field(default=None, ge=5, le=7 * 24 * 60)
    approval_mode: Literal["auto", "manual"] | None = None
    prompt_template_id: int | None = None
    clear_prompt_template: bool = False
    tiktok_account_ids: list[int] | None = None


class BulkAddIn(BaseModel):
    entries: list[str] = Field(min_length=1, max_length=30)


class BulkUpdateIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=1000)
    action: Literal["pause", "resume", "delete", "assign"]
    tiktok_account_ids: list[int] | None = None


class TikTokUpdate(BaseModel):
    daily_cap: int | None = Field(default=None, ge=1, le=100)
    default_privacy: PRIVACY_LEVELS | None = None
    color: Literal["violet", "blue", "orange", "pink", "green"] | None = None
