from pydantic import BaseModel, Field



class JobUpdate(BaseModel):
    rewritten_title: str | None = Field(default=None, max_length=150)
    rewritten_caption: str | None = Field(default=None, max_length=2200)
    rewritten_tags: list[str] | None = None
    buffer_channel_id: int | None = None  # null = the account whose turn it is


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)
