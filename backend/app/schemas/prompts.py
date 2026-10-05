from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=255)
    niche: str = Field(default="", max_length=80)
    title_prompt: str = ""
    caption_prompt: str = ""
    hashtags_prompt: str = ""
    is_enabled: bool = True


class PromptOut(PromptIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_default: bool
    created_at: datetime
    updated_at: datetime


class PromptTestIn(BaseModel):
    title_prompt: str = ""
    caption_prompt: str = ""
    hashtags_prompt: str = ""
    niche: str = ""
    title: str = ""
    caption: str = Field(default="", max_length=5000)
    tags: list[str] = []


class PromptTestOut(BaseModel):
    title: str
    caption: str
    tags: list[str]
