"""the owner can change any switch or limit for one account, on top of its plan

Revision ID: 0026
Revises: 0025
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import JSONType

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("custom_features", JSONType, nullable=True))
        batch_op.add_column(sa.Column("custom_limits", JSONType, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("custom_limits")
        batch_op.drop_column("custom_features")
