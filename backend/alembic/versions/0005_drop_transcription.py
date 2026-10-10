"""drop transcription (language gate uses the caption only)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM credentials WHERE key LIKE 'transcription.%'")
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_column("transcript")


def downgrade() -> None:
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("transcript", sa.Text(), nullable=True))
