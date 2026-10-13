"""Podcasts workspace: a mode on channels, TikTok accounts and videos; clips point at their podcast

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("channels", "tiktok_accounts", "videos"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("mode", sa.String(length=16), nullable=False, server_default="shorts"))
            batch_op.create_index(f"ix_{table}_mode", ["mode"], unique=False)
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("clip_start", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("clip_end", sa.Float(), nullable=True))
        batch_op.create_index("ix_videos_parent_id", ["parent_id"], unique=False)
        batch_op.create_foreign_key("fk_videos_parent_id", "videos", ["parent_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_constraint("fk_videos_parent_id", type_="foreignkey")
        batch_op.drop_index("ix_videos_parent_id")
        batch_op.drop_column("clip_end")
        batch_op.drop_column("clip_start")
        batch_op.drop_column("parent_id")
    for table in ("videos", "tiktok_accounts", "channels"):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_mode")
            batch_op.drop_column("mode")
