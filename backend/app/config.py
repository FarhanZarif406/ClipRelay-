from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # Core
    app_name: str = "ClipRelay"
    environment: Literal["development", "production", "test"] = "development"
    secret_key: str = "change-me"
    encryption_key: str = ""  # Fernet key (base64, 32 bytes). Generate with: python -m app.cli gen-key
    access_token_expire_minutes: int = 60 * 12
    allow_registration: bool = False
    public_base_url: str = "http://localhost:8000"  # backend URL reachable by OAuth providers
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"

    # Infra
    database_url: str = "postgresql+psycopg://cliprelay:cliprelay@localhost:5432/cliprelay"
    redis_url: str = "redis://localhost:6379/0"


    # YouTube
    youtube_api_key: str = ""  # optional: YouTube Data API key; without it lookups use the public pages and yt-dlp
    video_source_adapter: str = "yt_dlp"  # how original files are obtained (see app/services/sources.py)

    # LLM
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    llm_model: str = "claude-sonnet-5-5"
    llm_api_key: str = ""
    llm_base_url: str = ""  # optional; for OpenAI-compatible providers
    llm_max_tokens: int = 600

    # Optional email alerts (can also be set in Settings → Notifications)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = ""
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_path: str = "./data/media"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""

    # Media
    ffmpeg_path: str = "ffmpeg"
    font_file: str = ""  # a bold .ttf for hook text; without one a system bold font is looked for
    # How many videos are edited at the same time on the whole server; more wait for a free place, while downloads carry on.
    max_renders: int = 3
    render_threads: int = 1  # encoder threads per edit, so a few edits share a small server's processor fairly
    # Where members download the PC Helper (for example the files of a GitHub release); shown on the PC Helper page.
    helper_download_windows: str = ""
    helper_download_mac: str = ""

    # Limits from the design

    # Scheduler
    scheduler_tick_seconds: int = 30
    # Run the scheduler and the pipeline inside the API process instead of Celery (no Redis needed). For local use.
    inline_worker: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
