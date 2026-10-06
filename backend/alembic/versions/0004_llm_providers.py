"""multiple LLM providers + per-template model

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unverified"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prompt_templates") as batch:
        batch.add_column(sa.Column("llm_provider_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_prompt_templates_llm_provider", "llm_providers", ["llm_provider_id"], ["id"], ondelete="SET NULL")

    # Seed the default provider from .env so existing installs keep working with the same model.
    from datetime import datetime, timezone

    from app.config import get_settings

    s = get_settings()
    if s.llm_api_key and s.encryption_key:
        from app.security import encrypt

        now = datetime.now(timezone.utc)
        providers = sa.table(
            "llm_providers",
            sa.column("label"), sa.column("provider"), sa.column("api_key_enc"), sa.column("base_url"), sa.column("model"),
            sa.column("max_tokens"), sa.column("is_default"), sa.column("status"), sa.column("created_at"), sa.column("updated_at"),
        )
        op.bulk_insert(providers, [{
            "label": f"{s.llm_provider.capitalize()} (from .env)", "provider": s.llm_provider, "api_key_enc": encrypt(s.llm_api_key),
            "base_url": s.llm_base_url or None, "model": s.llm_model, "max_tokens": s.llm_max_tokens, "is_default": True,
            "status": "unverified", "created_at": now, "updated_at": now,
        }])


def downgrade() -> None:
    with op.batch_alter_table("prompt_templates") as batch:
        batch.drop_constraint("fk_prompt_templates_llm_provider", type_="foreignkey")
        batch.drop_column("llm_provider_id")
    op.drop_table("llm_providers")
