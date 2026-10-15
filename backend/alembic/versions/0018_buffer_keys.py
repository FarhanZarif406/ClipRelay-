"""up to ten Buffer keys per member, and accounts that take turns

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

from app.models.base import UTCDateTime

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "buffer_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(length=60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("saved_at", UTCDateTime(), nullable=False),
        sa.Column("synced_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_buffer_keys_user_id", "buffer_keys", ["user_id"])
    # The key a member saved before becomes their Key 1.
    op.execute("INSERT INTO buffer_keys (user_id, label, position, api_key_enc, organization_id, saved_at, synced_at, error) "
               "SELECT user_id, 'Key 1', 1, api_key_enc, organization_id, saved_at, synced_at, error FROM buffer_accounts")
    with op.batch_alter_table("buffer_channels", schema=None) as batch_op:
        batch_op.add_column(sa.Column("key_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("last_picked_at", UTCDateTime(), nullable=True))
        batch_op.create_index("ix_buffer_channels_key_id", ["key_id"], unique=False)
        batch_op.create_foreign_key("fk_buffer_channels_key_id", "buffer_keys", ["key_id"], ["id"], ondelete="CASCADE")
    op.execute("UPDATE buffer_channels SET key_id = (SELECT id FROM buffer_keys WHERE buffer_keys.user_id = buffer_channels.user_id)")
    # An account's turn starts from the last clip it was given.
    op.execute("UPDATE buffer_channels SET last_picked_at = (SELECT MAX(created_at) FROM buffer_log WHERE buffer_log.buffer_channel_id = buffer_channels.id)")
    op.drop_table("buffer_accounts")


def downgrade() -> None:
    op.create_table(
        "buffer_accounts",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=True),
        sa.Column("saved_at", UTCDateTime(), nullable=False),
        sa.Column("synced_at", UTCDateTime(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    # Only one key fits the old table: each member keeps their first, and the accounts of the others go.
    op.execute("INSERT INTO buffer_accounts (user_id, api_key_enc, organization_id, saved_at, synced_at, error) "
               "SELECT user_id, api_key_enc, organization_id, saved_at, synced_at, error FROM buffer_keys "
               "WHERE id IN (SELECT MIN(id) FROM buffer_keys GROUP BY user_id)")
    op.execute("DELETE FROM buffer_channels WHERE key_id IS NOT NULL AND key_id NOT IN (SELECT MIN(id) FROM buffer_keys GROUP BY user_id)")
    with op.batch_alter_table("buffer_channels", schema=None) as batch_op:
        batch_op.drop_constraint("fk_buffer_channels_key_id", type_="foreignkey")
        batch_op.drop_index("ix_buffer_channels_key_id")
        batch_op.drop_column("last_picked_at")
        batch_op.drop_column("key_id")
    op.drop_index("ix_buffer_keys_user_id", table_name="buffer_keys")
    op.drop_table("buffer_keys")
