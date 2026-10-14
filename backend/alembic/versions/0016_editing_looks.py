"""editing looks and presets, each member's library of music, fonts and watermark, a channel's preset

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import JSONType, UTCDateTime

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editing_looks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="shorts"),
        sa.Column("name", sa.String(length=60), nullable=True),
        sa.Column("look", JSONType, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_editing_looks_user_id", "editing_looks", ["user_id"])
    op.create_table(
        "library_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("ext", sa.String(length=8), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("uses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_library_files_user_id", "library_files", ["user_id"])
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preset_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_channels_preset_id", "editing_looks", ["preset_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.drop_constraint("fk_channels_preset_id", type_="foreignkey")
        batch_op.drop_column("preset_id")
    op.drop_index("ix_library_files_user_id", table_name="library_files")
    op.drop_table("library_files")
    op.drop_index("ix_editing_looks_user_id", table_name="editing_looks")
    op.drop_table("editing_looks")
