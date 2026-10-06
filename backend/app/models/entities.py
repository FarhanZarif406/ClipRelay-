from datetime import datetime
from typing import Any

from sqlalchemy import false as sa_false
from sqlalchemy import Boolean, Column, Float, ForeignKey, Index, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JSONType, TimestampMixin, UTCDateTime, utcnow


class JobStatus:
    FETCHED = "fetched"
    REWRITING = "rewriting"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    UPLOADING = "uploading"
    POSTED = "posted"
    MONITORING = "monitoring"
    CLEAN = "clean"
    VIOLATED = "violated"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = {CLEAN, VIOLATED, FAILED, CANCELLED}
    PENDING = {FETCHED, REWRITING, AWAITING_APPROVAL, READY, UPLOADING}
    PUBLISHED = {POSTED, MONITORING, CLEAN}


class VideoStatus:
    FETCHED = "fetched"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class TikTokStatus:
    ACTIVE = "active"
    EXPIRING = "expiring"
    EXPIRED = "expired"
    REVOKED = "revoked"


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    workspace_name: Mapped[str] = mapped_column(String(120), default="My Workspace")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")  # owner | member

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"


class Credential(Base):
    """Third-party credentials editable from Settings (values Fernet-encrypted). Falls back to .env when absent."""

    __tablename__ = "credentials"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value_enc: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="unverified")  # unverified | valid | invalid
    last_error: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class AppSetting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


source_tiktok_links = Table(
    "source_tiktok_links",
    Base.metadata,
    Column("source_id", ForeignKey("instagram_sources.id", ondelete="CASCADE"), primary_key=True),
    Column("tiktok_account_id", ForeignKey("tiktok_accounts.id", ondelete="CASCADE"), primary_key=True),
)


class InstagramSource(Base, TimestampMixin):
    __tablename__ = "instagram_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    ig_user_id: Mapped[str] = mapped_column(String(64), unique=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    profile_picture_url: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(16), default="violet")
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    token_refreshed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_run_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    approval_mode: Mapped[str] = mapped_column(String(16), default="auto")  # auto | manual
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"))
    videos_found: Mapped[int] = mapped_column(Integer, default=0)
    needs_reconnect: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())

    tiktok_accounts: Mapped[list["TikTokAccount"]] = relationship(
        secondary=source_tiktok_links, back_populates="sources", lazy="selectin"
    )
    prompt_template: Mapped["PromptTemplate | None"] = relationship(lazy="joined")


class TikTokAccount(Base, TimestampMixin):
    __tablename__ = "tiktok_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    open_id: Mapped[str] = mapped_column(String(128), unique=True)
    username: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(16), default="blue")
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    refresh_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scopes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=TikTokStatus.ACTIVE)
    daily_cap: Mapped[int] = mapped_column(Integer, default=15)
    default_privacy: Mapped[str] = mapped_column(String(40), default="PUBLIC_TO_EVERYONE")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    sources: Mapped[list[InstagramSource]] = relationship(
        secondary=source_tiktok_links, back_populates="tiktok_accounts", lazy="selectin"
    )


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(255), default="")
    niche: Mapped[str] = mapped_column(String(80), default="")
    title_prompt: Mapped[str] = mapped_column(Text, default="")
    caption_prompt: Mapped[str] = mapped_column(Text, default="")
    hashtags_prompt: Mapped[str] = mapped_column(Text, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_provider_id: Mapped[int | None] = mapped_column(ForeignKey("llm_providers.id", ondelete="SET NULL"))


class LLMProvider(Base, TimestampMixin):
    """An AI model connection (API key encrypted). One is the workspace default; templates may pick another."""

    __tablename__ = "llm_providers"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(24))  # anthropic | openai | gemini | openrouter | groq | mistral | custom
    api_key_enc: Mapped[str] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200))
    max_tokens: Mapped[int] = mapped_column(Integer, default=600)
    temperature: Mapped[float | None] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="unverified")  # unverified | valid | invalid
    last_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PromptTemplateVersion(Base):
    __tablename__ = "prompt_template_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Video(Base):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("source_id", "ig_media_id", name="uq_video_source_media"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("instagram_sources.id", ondelete="CASCADE"), index=True)
    ig_media_id: Mapped[str] = mapped_column(String(64))
    permalink: Mapped[str | None] = mapped_column(Text)
    media_url: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    original_title: Mapped[str] = mapped_column(Text, default="")
    original_caption: Mapped[str] = mapped_column(Text, default="")
    original_tags: Mapped[list] = mapped_column(JSONType, default=list)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    transcript: Mapped[str | None] = mapped_column(Text)
    detected_language: Mapped[str | None] = mapped_column(String(32))
    language_confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default=VideoStatus.FETCHED, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    source: Mapped[InstagramSource] = relationship(lazy="joined")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("video_id", "tiktok_account_id", name="uq_job_video_account"),
        Index("ix_jobs_status_next_check", "status", "next_check_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    tiktok_account_id: Mapped[int | None] = mapped_column(ForeignKey("tiktok_accounts.id", ondelete="SET NULL"), index=True)
    prompt_template_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_templates.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(24), default=JobStatus.FETCHED, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    rewritten_title: Mapped[str | None] = mapped_column(Text)
    rewritten_caption: Mapped[str | None] = mapped_column(Text)
    rewritten_tags: Mapped[list] = mapped_column(JSONType, default=list)
    privacy_level: Mapped[str | None] = mapped_column(String(40))
    tiktok_publish_id: Mapped[str | None] = mapped_column(String(128))
    tiktok_post_id: Mapped[str | None] = mapped_column(String(128))
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    monitor_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    violation_reason: Mapped[str | None] = mapped_column(Text)

    video: Mapped[Video] = relationship(lazy="joined")
    tiktok_account: Mapped[TikTokAccount | None] = relationship(lazy="joined")
    events: Mapped[list["JobEvent"]] = relationship(
        lazy="selectin", order_by="JobEvent.id", cascade="all, delete-orphan"
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Violation(Base):
    __tablename__ = "violations"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    tiktok_account_id: Mapped[int | None] = mapped_column(ForeignKey("tiktok_accounts.id", ondelete="SET NULL"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONType)
    removal_status: Mapped[str] = mapped_column(String(32), default="pending")  # removed | removed_by_tiktok | manual_required | disabled
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)

    job: Mapped[Job] = relationship(lazy="joined")
    tiktok_account: Mapped[TikTokAccount | None] = relationship(lazy="joined")


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(16), default="info", index=True)
    service: Mapped[str] = mapped_column(String(40), index=True)
    event: Mapped[str] = mapped_column(String(60), default="")
    message: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(40))
    job_id: Mapped[int | None] = mapped_column(Integer, index=True)
    payload: Mapped[dict | None] = mapped_column(JSONType)
