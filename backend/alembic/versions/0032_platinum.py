"""the Platinum plan as the owner set it: 30 days, 60 videos and 8 podcasts a day, 500 cloud videos, auto-check every 15 minutes

Revision ID: 0032
Revises: 0031
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

FEATURES = {
    "podcasts": True, "ai_captions": True, "ai_hook": True, "background_music": True, "watermark": True,
    "custom_fonts": True, "editing_presets": True, "test_render": True, "full_editing": True,
    "pc_editing": True, "cloud_editing": True,
}
LIMITS = {
    "videos_per_day": 60, "podcasts_per_day": 8, "buffer_keys": 5, "buffer_accounts": 15,
    "cloud_videos_per_month": 500, "auto_check_minutes": 15, "trial_days": 30, "skipped_keep_hours": 72,
}  # channels stay as they were


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, features, limits FROM plans WHERE name = 'Platinum'")).first()
    if not row:
        return
    features = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    limits = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    features.update(FEATURES)
    limits.update(LIMITS)
    bind.execute(sa.text("UPDATE plans SET features = :f, limits = :l, description = :d WHERE id = :id"),
                 {"f": json.dumps(features), "l": json.dumps(limits), "id": row[0],
                  "d": "30 days: 60 videos and 8 podcasts a day, full 1080p editing, 500 cloud videos, everything included, auto-check every 15 minutes."})


def downgrade() -> None:
    pass  # the owner's later changes to the plan are not undone
