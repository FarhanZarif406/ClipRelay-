"""remove Instagram: sources, fetch runs and the videos/jobs that came from them

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every stored video came from an Instagram source, so the videos and their jobs go with the sources.
    for table in ("violations", "job_events", "jobs", "videos"):
        op.execute(f"DELETE FROM {table}")
    op.execute("DELETE FROM activity_logs WHERE service = 'Instagram'")

    op.drop_index("ix_fetch_runs_started_at", table_name="fetch_runs")
    op.drop_table("fetch_runs")
    op.drop_table("source_tiktok_links")

    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.drop_index("ix_videos_source_id")
        batch_op.drop_column("source_id")  # its foreign key and unique constraint go with it
        batch_op.drop_column("likes")
        batch_op.alter_column("ig_media_id", new_column_name="external_id", existing_type=sa.String(length=64), nullable=True)
    with op.batch_alter_table("videos", schema=None) as batch_op:
        batch_op.create_index("ix_videos_external_id", ["external_id"], unique=False)

    op.drop_table("instagram_sources")


def downgrade() -> None:
    raise NotImplementedError("The Instagram tables and their data were removed; restore from a backup instead.")
