"""plans that decide what each account may use; accounts can be suspended

Revision ID: 0019
Revises: 0018
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

from app.models.base import JSONType, UTCDateTime

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

FEATURES = ["podcasts", "ai_captions", "ai_hook", "background_music", "watermark", "custom_fonts", "editing_presets", "test_render"]


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=60), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("features", JSONType, nullable=False),
        sa.Column("limits", JSONType, nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    now = datetime.now(timezone.utc)
    on = lambda *keys: {key: key in keys for key in FEATURES + ["full_editing"]}  # noqa: E731
    op.bulk_insert(plans, [
        # Sized for about 30 members on one small server (1 vCPU, 4 GB): see the README.
        {"name": "Free", "description": "5-day trial: Fast mode, 3 videos a day.", "is_default": True,
         "features": on("ai_captions"),
         "limits": {"channels": 50, "videos_per_day": 3, "podcasts_per_day": 0, "buffer_keys": 1, "buffer_accounts": 3, "auto_check_minutes": 0, "trial_days": 5, "skipped_keep_hours": 8}, "created_at": now},
        {"name": "Starter", "description": "Fast mode with AI hook text, watermark and own fonts.", "is_default": False,
         "features": on("ai_captions", "ai_hook", "watermark", "custom_fonts", "test_render"),
         "limits": {"channels": 101, "videos_per_day": 8, "podcasts_per_day": 0, "buffer_keys": 1, "buffer_accounts": 3, "auto_check_minutes": 0, "trial_days": 0, "skipped_keep_hours": 12}, "created_at": now},
        {"name": "Pro", "description": "Full editing in 1080p, music and presets.", "is_default": False,
         "features": on("ai_captions", "ai_hook", "watermark", "custom_fonts", "test_render", "background_music", "editing_presets", "full_editing"),
         "limits": {"channels": 210, "videos_per_day": 15, "podcasts_per_day": 0, "buffer_keys": 3, "buffer_accounts": 9, "auto_check_minutes": 60, "trial_days": 0, "skipped_keep_hours": 24}, "created_at": now},
        {"name": "Business", "description": "Everything, with the Podcasts workspace.", "is_default": False,
         "features": on(*FEATURES, "full_editing"),
         "limits": {"channels": 315, "videos_per_day": 30, "podcasts_per_day": 3, "buffer_keys": 5, "buffer_accounts": 15, "auto_check_minutes": 30, "trial_days": 0, "skipped_keep_hours": 48}, "created_at": now},
    ])
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("plan_expires_at", UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column("suspended", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.create_index("ix_users_plan_id", ["plan_id"], unique=False)
        batch_op.create_foreign_key("fk_users_plan_id", "plans", ["plan_id"], ["id"], ondelete="SET NULL")
    # The members there are already keep everything they had: they start on Pro. New accounts get the default (Free).
    op.execute("UPDATE users SET plan_id = (SELECT id FROM plans WHERE name = 'Pro') WHERE role != 'owner'")


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_users_plan_id", type_="foreignkey")
        batch_op.drop_index("ix_users_plan_id")
        batch_op.drop_column("suspended")
        batch_op.drop_column("plan_expires_at")
        batch_op.drop_column("plan_id")
    op.drop_table("plans")
