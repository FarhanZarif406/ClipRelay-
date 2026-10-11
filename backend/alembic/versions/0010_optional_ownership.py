"""adding a channel no longer needs an ownership confirmation

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.alter_column("ownership_confirmed_at", existing_type=TS, nullable=True)
        batch_op.alter_column("ownership_confirmed_by", new_column_name="added_by", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE channels SET ownership_confirmed_at = created_at WHERE ownership_confirmed_at IS NULL")
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.alter_column("added_by", new_column_name="ownership_confirmed_by", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("ownership_confirmed_at", existing_type=TS, nullable=False)
