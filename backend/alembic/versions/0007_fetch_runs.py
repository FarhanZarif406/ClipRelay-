"""run summaries for batches of source checks

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fetch_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accounts_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("videos_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accounts_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accounts_paused", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stopped_reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fetch_runs_started_at", "fetch_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_fetch_runs_started_at", table_name="fetch_runs")
    op.drop_table("fetch_runs")
