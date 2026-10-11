"""push subscription status on channels; drop language columns; one "long-form" skip reason

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pubsub_requested_at", TS, nullable=True))
        batch_op.add_column(sa.Column("pubsub_error", sa.Text(), nullable=True))
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_column("detected_language")
        batch_op.drop_column("language_confidence")
    op.execute("UPDATE videos SET skip_reason = 'long-form' WHERE skip_reason IN ('too_long', 'not_a_short')")
    # Rules and schedule settings that no longer exist.
    op.execute("DELETE FROM pipeline_settings WHERE key IN ('shorts_only', 'caption_prompt')")
    op.execute("DELETE FROM pipeline_settings WHERE key = 'approval_required' AND channel_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("language_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("detected_language", sa.String(length=32), nullable=True))
    with op.batch_alter_table("channels", schema=None) as batch_op:
        batch_op.drop_column("pubsub_error")
        batch_op.drop_column("pubsub_requested_at")
