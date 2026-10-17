"""every member has their own AI models and YouTube Data API key

Revision ID: 0020
Revises: 0019
"""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The AI models there are already belong to the owners (no member): they keep using them.
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_llm_providers_user_id", ["user_id"], unique=False)
        batch_op.create_foreign_key("fk_llm_providers_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("youtube_api_key_enc", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("DELETE FROM llm_providers WHERE user_id IS NOT NULL")  # members' own models have nowhere to go
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("youtube_api_key_enc")
    with op.batch_alter_table("llm_providers", schema=None) as batch_op:
        batch_op.drop_constraint("fk_llm_providers_user_id", type_="foreignkey")
        batch_op.drop_index("ix_llm_providers_user_id")
        batch_op.drop_column("user_id")
