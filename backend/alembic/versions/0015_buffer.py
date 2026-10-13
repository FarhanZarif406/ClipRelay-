"""publish through Buffer: each member's key and accounts, and the posts handed over

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import JSONType, UTCDateTime

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buffer_accounts",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("saved_at", UTCDateTime(), nullable=False),
        sa.Column("synced_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "buffer_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="shorts"),
        sa.Column("buffer_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("service", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("avatar", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("times", JSONType, nullable=False),
        sa.Column("time_zone", sa.String(length=60), nullable=True),
        sa.Column("start_date", sa.String(length=10), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "mode", "buffer_id", name="uq_buffer_channel_user_mode"),
    )
    op.create_index("ix_buffer_channels_user_id", "buffer_channels", ["user_id"])
    op.create_table(
        "buffer_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("buffer_channel_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("post_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("due_at", UTCDateTime(), nullable=True),
        sa.Column("done_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_buffer_log_channel", "buffer_log", ["buffer_channel_id"])
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("buffer_channel_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("buffer_post_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("buffer_due_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("buffer_checked_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("buffer_link", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("share_token", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_jobs_buffer_channel_id", ["buffer_channel_id"], unique=False)
        batch_op.create_index("ix_jobs_share_token", ["share_token"], unique=True)
        batch_op.create_foreign_key("fk_jobs_buffer_channel_id", "buffer_channels", ["buffer_channel_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_jobs_buffer_channel_id", type_="foreignkey")
        batch_op.drop_index("ix_jobs_share_token")
        batch_op.drop_index("ix_jobs_buffer_channel_id")
        for column in ("share_token", "buffer_link", "buffer_checked_at", "buffer_due_at", "buffer_post_id", "buffer_channel_id"):
            batch_op.drop_column(column)
    op.drop_index("ix_buffer_log_channel", table_name="buffer_log")
    op.drop_table("buffer_log")
    op.drop_index("ix_buffer_channels_user_id", table_name="buffer_channels")
    op.drop_table("buffer_channels")
    op.drop_table("buffer_accounts")
