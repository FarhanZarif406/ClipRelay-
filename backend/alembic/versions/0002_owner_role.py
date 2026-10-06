"""owner role

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("role", sa.String(length=16), nullable=False, server_default="member"))
    # The earliest-created user becomes the workspace owner.
    op.execute(
        "UPDATE users SET role = 'owner' WHERE id = (SELECT id FROM users ORDER BY created_at, id LIMIT 1)"
    )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("role")
