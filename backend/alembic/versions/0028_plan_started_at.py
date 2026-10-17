"""each account remembers when its current plan began (a plan's "first day only" switches count from it)

Revision ID: 0028
Revises: 0027
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import UTCDateTime

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_started_at", UTCDateTime(), nullable=True))
    op.execute("UPDATE users SET plan_started_at = created_at")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("plan_started_at")
