"""every member has their own channels, TikTok accounts, videos and rules

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

OWNED = ("channels", "tiktok_accounts", "videos", "pipeline_settings", "setting_changes")


def upgrade() -> None:
    for table in OWNED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch_op.create_index(f"ix_{table}_user_id", ["user_id"], unique=False)
            batch_op.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL")
    with op.batch_alter_table("activity_logs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_activity_logs_user_id", ["user_id"], unique=False)
    with op.batch_alter_table("pipeline_settings", schema=None) as batch_op:
        batch_op.drop_constraint("uq_pipeline_settings_key_channel", type_="unique")
        batch_op.create_unique_constraint("uq_pipeline_settings_key_channel_user", ["key", "channel_id", "user_id"])
    # Everything that exists so far was set up by the workspace's first owner: it becomes theirs.
    first_owner = "(SELECT id FROM users WHERE role = 'owner' ORDER BY id LIMIT 1)"
    for table in OWNED:
        op.execute(f"UPDATE {table} SET user_id = {first_owner}")


def downgrade() -> None:
    with op.batch_alter_table("pipeline_settings", schema=None) as batch_op:
        batch_op.drop_constraint("uq_pipeline_settings_key_channel_user", type_="unique")
        batch_op.create_unique_constraint("uq_pipeline_settings_key_channel", ["key", "channel_id"])
    with op.batch_alter_table("activity_logs", schema=None) as batch_op:
        batch_op.drop_index("ix_activity_logs_user_id")
        batch_op.drop_column("user_id")
    for table in OWNED:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch_op.drop_index(f"ix_{table}_user_id")
            batch_op.drop_column("user_id")
