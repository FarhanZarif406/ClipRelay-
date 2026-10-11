"""YouTube channels as the only source, pipeline rules with an audit trail, download/render stages

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "channels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("youtube_channel_id", sa.String(length=64), nullable=False),
        sa.Column("handle", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("default_tiktok_account_id", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ownership_confirmed_at", TS, nullable=False),
        sa.Column("monitoring_since", TS, nullable=False),
        sa.Column("ownership_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("pubsub_subscription_expires_at", TS, nullable=True),
        sa.Column("last_checked_at", TS, nullable=True),
        sa.Column("next_poll_at", TS, nullable=True),
        sa.Column("last_upload_at", TS, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["default_tiktok_account_id"], ["tiktok_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ownership_confirmed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("youtube_channel_id", name="uq_channels_youtube_channel_id"),
    )
    op.create_index("ix_channels_active", "channels", ["active"])

    op.create_table(
        "pipeline_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", JSON, nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="global"),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "channel_id", name="uq_pipeline_settings_key_channel"),
    )
    op.create_index("ix_pipeline_settings_key", "pipeline_settings", ["key"])
    op.create_index("ix_pipeline_settings_channel_id", "pipeline_settings", ["channel_id"])

    op.create_table(
        "setting_changes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=True),
        sa.Column("channel_name", sa.String(length=255), nullable=True),
        sa.Column("old_value", JSON, nullable=True),
        sa.Column("new_value", JSON, nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_by_email", sa.String(length=255), nullable=True),
        sa.Column("changed_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_setting_changes_channel_id", "setting_changes", ["channel_id"])
    op.create_index("ix_setting_changes_changed_at", "setting_changes", ["changed_at"])

    # Videos stored before this version have no channel and no rendered file, so they cannot be published.
    for table in ("violations", "job_events", "jobs", "videos"):
        op.execute(f"DELETE FROM {table}")

    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_index("ix_videos_external_id")
        batch_op.alter_column("external_id", new_column_name="youtube_video_id", existing_type=sa.String(length=64), nullable=True)
        batch_op.alter_column("storage_key", new_column_name="rendered_file_path", existing_type=sa.Text(), nullable=True)
        batch_op.add_column(sa.Column("channel_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_file_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("files_deleted_at", TS, nullable=True))
        batch_op.add_column(sa.Column("skip_reason", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("forced", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_foreign_key("fk_videos_channel_id", "channels", ["channel_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.create_index("ix_videos_channel_id", ["channel_id"], unique=False)
        # One YouTube video id is processed once, forever: repeat push notifications fail this constraint.
        batch_op.create_unique_constraint("uq_videos_youtube_video_id", ["youtube_video_id"])

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("caption_status", sa.String(length=20), nullable=False, server_default="pending"))
        batch_op.add_column(sa.Column("publish_mode", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("reject_reason", sa.Text(), nullable=True))

    with op.batch_alter_table("tiktok_accounts", schema=None) as batch_op:
        batch_op.alter_column("daily_cap", existing_type=sa.Integer(), nullable=True)
    # NULL = use the uploads_per_tiktok_account_per_day rule (7 by default) instead of the old fixed 15.
    op.execute("UPDATE tiktok_accounts SET daily_cap = NULL")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("terms_accepted_at", TS, nullable=True))


def downgrade() -> None:
    raise NotImplementedError("Videos and jobs were reset for the YouTube pipeline; restore from a backup instead.")
