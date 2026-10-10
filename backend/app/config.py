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

    # Instagram (Instagram API with Instagram Login)
    instagram_app_id: str = ""
    instagram_app_secret: str = ""
    instagram_api_version: str = "v21.0"
    instagram_scopes: str = "instagram_business_basic"

    # TikTok (Login Kit + Content Posting API)
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_scopes: str = "user.info.basic,video.publish,video.list"

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
    ffprobe_path: str = "ffprobe"
    ffmpeg_path: str = "ffmpeg"
    max_video_duration_sec: float = 60.0

    # Limits from the design
    max_tiktok_accounts: int = 20
    max_instagram_sources: int = 7000
    monthly_job_quota: int = 1000

    # Scheduler
    scheduler_tick_seconds: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
