"""sources are plain usernames fetched through the Instaloader service

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM credentials WHERE key LIKE 'instagram.%'")
    with op.batch_alter_table("instagram_sources", schema=None) as batch_op:
        batch_op.alter_column("ig_user_id", existing_type=sa.String(length=64), nullable=True)
        batch_op.add_column(sa.Column("last_run_started_at", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("likes", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_column("likes")
    with op.batch_alter_table("instagram_sources", schema=None) as batch_op:
        batch_op.drop_column("last_run_started_at")
