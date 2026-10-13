from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import JSONType, TimestampMixin, UTCDateTime, utcnow


class JobStatus:
    FETCHED = "fetched"  # detected on YouTube, waiting for the download
    DOWNLOADING = "downloading"
    RENDERING = "rendering"
    REWRITING = "rewriting"  # rendered, waiting for the caption
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"
    UPLOADING = "uploading"
    SCHEDULED = "scheduled"  # handed to Buffer, which publishes it at the time it was given
    POSTED = "posted"
    MONITORING = "monitoring"
    CLEAN = "clean"
    VIOLATED = "violated"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLIPPED = "clipped"  # a podcast whose clips were chosen; each clip then has a job of its own

    TERMINAL = {CLEAN, VIOLATED, FAILED, CANCELLED, CLIPPED}
    PROCESSING = {FETCHED, DOWNLOADING, RENDERING, REWRITING}
    PENDING = PROCESSING | {AWAITING_APPROVAL, READY, UPLOADING}
    PUBLISHED = {POSTED, MONITORING, CLEAN}


class Mode:
    """The two workspaces. Channels, TikTok accounts, videos and rules each belong to exactly one."""

    SHORTS = "shorts"  # short uploads, republished whole
    PODCASTS = "podcasts"  # long uploads, cut into short clips
    ALL = (SHORTS, PODCASTS)


class VideoStatus:
    FETCHED = "fetched"
    ACCEPTED = "accepted"
    SKIPPED = "skipped"  # held with a reason; can be processed by hand later


class SkipReason:
    LONG_FORM = "long-form"
    TOO_SHORT = "too_short"
    NOT_PODCAST = "not_a_podcast"
    CHANNEL_CAP = "skipped_channel_cap"
    ACCOUNT_CAP = "skipped_account_cap"


class CaptionStatus:
    PENDING = "pending"
    DONE = "done"
    FALLBACK = "caption_fallback"  # the model failed; the original title and default hashtags are used


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
    terms_accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

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


class RuleSetting(Base):
    """One pipeline rule (speed, flip, caps, …). `channel_id` NULL is the global default, otherwise a channel override."""

    __tablename__ = "pipeline_settings"
    __table_args__ = (UniqueConstraint("key", "channel_id", "user_id", name="uq_pipeline_settings_key_channel_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[Any] = mapped_column(JSONType)
    scope: Mapped[str] = mapped_column(String(16), default="global")  # global | channel
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # the member this belongs to
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class RuleChange(Base):
    """Audit trail: who changed which rule, from what to what, and when."""

    __tablename__ = "setting_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80))
    channel_id: Mapped[int | None] = mapped_column(Integer, index=True)
    channel_name: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # the member this belongs to
    old_value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONType, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_by_email: Mapped[str | None] = mapped_column(String(255))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class TikTokAccount(Base, TimestampMixin):
    __tablename__ = "tiktok_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    open_id: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # the member this belongs to
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
    daily_cap: Mapped[int | None] = mapped_column(Integer)  # NULL = use the uploads_per_tiktok_account_per_day rule
    default_privacy: Mapped[str] = mapped_column(String(40), default="PUBLIC_TO_EVERYONE")
    mode: Mapped[str] = mapped_column(String(16), default=Mode.SHORTS, server_default=Mode.SHORTS, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


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


class Channel(Base, TimestampMixin):
    """A monitored YouTube channel."""

    __tablename__ = "channels"
    id: Mapped[int] = mapped_column(primary_key=True)
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # the member this belongs to
    mode: Mapped[str] = mapped_column(String(16), default=Mode.SHORTS, server_default=Mode.SHORTS, index=True)
    handle: Mapped[str | None] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    default_tiktok_account_id: Mapped[int | None] = mapped_column(ForeignKey("tiktok_accounts.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    ownership_confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # only set when an operator ticked a confirmation
    monitoring_since: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)  # only uploads after this are republished
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    pubsub_subscription_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    pubsub_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime())  # asked the hub; waiting for it to verify
    pubsub_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_poll_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_upload_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_error: Mapped[str | None] = mapped_column(Text)

    default_tiktok_account: Mapped[TikTokAccount | None] = relationship(lazy="joined")


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)  # the member this belongs to
    # Unique on purpose: YouTube notifies again whenever a title or description is edited, and the
    # constraint makes every repeat harmless — the insert fails and no second job is ever created.
    youtube_video_id: Mapped[str | None] = mapped_column(String(64), unique=True)
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
    source_file_path: Mapped[str | None] = mapped_column(Text)  # storage key of the downloaded original
    rendered_file_path: Mapped[str | None] = mapped_column(Text)  # storage key of the edited file sent to TikTok
    files_deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=VideoStatus.FETCHED, index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(40))  # SkipReason code
    rejection_reason: Mapped[str | None] = mapped_column(Text)  # the same reason, written out for people
    forced: Mapped[bool] = mapped_column(Boolean, default=False)  # "Process anyway": duration and cap checks are bypassed
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)  # discovered at

    mode: Mapped[str] = mapped_column(String(16), default=Mode.SHORTS, server_default=Mode.SHORTS, index=True)
    # A podcast clip is a video of its own (one clip = one TikTok post) that points at the podcast it was cut from.
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    clip_start: Mapped[float | None] = mapped_column(Float)
    clip_end: Mapped[float | None] = mapped_column(Float)

    channel: Mapped[Channel | None] = relationship(lazy="joined")
    parent: Mapped["Video | None"] = relationship(remote_side="Video.id", lazy="joined")

    @property
    def is_podcast_source(self) -> bool:
        """A whole podcast (not one of its clips): it is analysed and split, never published itself."""
        return self.mode == Mode.PODCASTS and self.parent_id is None


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
    caption_status: Mapped[str] = mapped_column(String(20), default=CaptionStatus.PENDING)
    publish_mode: Mapped[str | None] = mapped_column(String(16))  # inbox | direct, set when the upload starts
    reject_reason: Mapped[str | None] = mapped_column(Text)
    privacy_level: Mapped[str | None] = mapped_column(String(40))
    tiktok_publish_id: Mapped[str | None] = mapped_column(String(128))
    tiktok_post_id: Mapped[str | None] = mapped_column(String(128))
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    monitor_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[int | None] = mapped_column(Integer)  # 0–100 while downloading or rendering; shown on Live Status
    error: Mapped[str | None] = mapped_column(Text)
    violation_reason: Mapped[str | None] = mapped_column(Text)
    # Publishing through Buffer: the account it goes to, Buffer's post, and when Buffer was asked to publish it.
    buffer_channel_id: Mapped[int | None] = mapped_column(ForeignKey("buffer_channels.id", ondelete="SET NULL"), index=True)
    buffer_post_id: Mapped[str | None] = mapped_column(String(64))
    buffer_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    buffer_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    buffer_link: Mapped[str | None] = mapped_column(Text)  # the published post, as Buffer reports it
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)  # the private link Buffer fetches the clip from

    video: Mapped[Video] = relationship(lazy="joined")
    tiktok_account: Mapped[TikTokAccount | None] = relationship(lazy="joined")
    buffer_channel: Mapped["BufferChannel | None"] = relationship(lazy="joined")
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
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)  # the member it concerns; NULL = the whole workspace
    payload: Mapped[dict | None] = mapped_column(JSONType)


class BufferAccount(Base):
    """A member's own Buffer API key (Fernet-encrypted). Having one means their clips go out through Buffer."""

    __tablename__ = "buffer_accounts"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    api_key_enc: Mapped[str] = mapped_column(Text)
    organization_id: Mapped[str | None] = mapped_column(String(64))
    saved_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)


class BufferChannel(Base):
    """A social account the member connected in Buffer, as one workspace schedules it."""

    __tablename__ = "buffer_channels"
    __table_args__ = (UniqueConstraint("user_id", "mode", "buffer_id", name="uq_buffer_channel_user_mode"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16), default=Mode.SHORTS, server_default=Mode.SHORTS)
    buffer_id: Mapped[str] = mapped_column(String(64))  # Buffer's own channel ID
    name: Mapped[str] = mapped_column(String(255))
    service: Mapped[str] = mapped_column(String(40), default="")  # tiktok, instagram, youtube, …
    avatar: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # whether clips may be sent to it
    daily_limit: Mapped[int] = mapped_column(Integer, default=3)
    times: Mapped[list] = mapped_column(JSONType, default=list)  # "HH:MM", on the account's clock
    time_zone: Mapped[str | None] = mapped_column(String(60))  # the account's own; NULL uses the member's
    start_date: Mapped[str | None] = mapped_column(String(10))  # first day a clip may go out; NULL starts at once
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BufferLog(Base):
    """Every clip handed to Buffer and what became of it. Kept apart from the jobs, so an account's totals stay true."""

    __tablename__ = "buffer_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    buffer_channel_id: Mapped[int] = mapped_column(Integer, index=True)
    job_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text, default="")
    post_id: Mapped[str | None] = mapped_column(String(64))  # Buffer's post; NULL when Buffer never accepted it
    state: Mapped[str] = mapped_column(String(16))  # scheduled | published | failed
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
