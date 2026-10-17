"""each video remembers when it was edited, for the PC Helper's monthly figures (logs are kept only 60 days)

Revision ID: 0025
Revises: 0024
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import UTCDateTime

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("edited_at", UTCDateTime(), nullable=True))
        batch_op.create_index("ix_jobs_edited_at", ["edited_at"], unique=False)
    # Videos edited before this: their last change is the closest date there is.
    op.execute(
        "UPDATE jobs SET edited_at = updated_at WHERE video_id IN "
        "(SELECT id FROM videos WHERE rendered_file_path IS NOT NULL OR files_deleted_at IS NOT NULL) OR posted_at IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index("ix_jobs_edited_at")
        batch_op.drop_column("edited_at")
