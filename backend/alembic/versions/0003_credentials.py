"""credential store + instagram reconnect flag

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unverified"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )
    with op.batch_alter_table("instagram_sources") as batch:
        batch.add_column(sa.Column("needs_reconnect", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("instagram_sources") as batch:
        batch.drop_column("needs_reconnect")
    op.drop_table("credentials")
