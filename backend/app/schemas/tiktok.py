from typing import Literal

from pydantic import BaseModel, Field

PRIVACY_LEVELS = Literal["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"]


class TikTokUpdate(BaseModel):
    daily_cap: int | None = Field(default=None, ge=1, le=100)  # null = follow the global rule
    default_privacy: PRIVACY_LEVELS | None = None
    color: Literal["violet", "blue", "orange", "pink", "green"] | None = None
