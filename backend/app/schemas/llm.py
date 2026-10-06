from typing import Literal

from pydantic import BaseModel, Field, model_validator

ProviderName = Literal["anthropic", "openai", "gemini", "openrouter", "groq", "mistral", "custom"]


class ValidateProviderIn(BaseModel):
    provider: ProviderName
    api_key: str = ""
    base_url: str | None = None
    provider_id: int | None = None  # reuse the stored key when editing


class ProviderIn(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    provider: ProviderName
    api_key: str = Field(min_length=1)
    base_url: str | None = Field(default=None, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    max_tokens: int = Field(default=600, ge=16, le=32000)
    temperature: float | None = Field(default=None, ge=0, le=2)

    @model_validator(mode="after")
    def _custom_needs_base(self):
        if self.provider == "custom" and not (self.base_url or "").strip():
            raise ValueError("A base URL is required for custom providers")
        return self


class ProviderUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    provider: ProviderName | None = None
    api_key: str | None = None  # blank / missing = keep the stored key
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, min_length=1, max_length=200)
    max_tokens: int | None = Field(default=None, ge=16, le=32000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    clear_temperature: bool = False
