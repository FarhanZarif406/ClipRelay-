"""the Gold plan as the owner set it: 30 days, 36 videos and 3 podcasts a day, 230 cloud videos, auto-check every 30 minutes

Revision ID: 0031
Revises: 0030
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

FEATURES = {
    "podcasts": True, "ai_captions": True, "ai_hook": True, "background_music": True, "watermark": True,
    "custom_fonts": True, "editing_presets": True, "test_render": True, "full_editing": True,
    "pc_editing": True, "cloud_editing": True,
}
LIMITS = {
    "videos_per_day": 36, "podcasts_per_day": 3, "buffer_keys": 3, "buffer_accounts": 9,
    "cloud_videos_per_month": 230, "auto_check_minutes": 30, "trial_days": 30, "skipped_keep_hours": 48,
}  # channels stay as they were (315)


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, features, limits FROM plans WHERE name = 'Gold'")).first()
    if not row:
        return
    features = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    limits = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    features.update(FEATURES)
    limits.update(LIMITS)
    bind.execute(sa.text("UPDATE plans SET features = :f, limits = :l, description = :d WHERE id = :id"),
                 {"f": json.dumps(features), "l": json.dumps(limits), "id": row[0],
                  "d": "30 days: 36 videos and 3 podcasts a day, full 1080p editing, 230 cloud videos, everything included, auto-check every 30 minutes."})


def downgrade() -> None:
    pass  # the owner's later changes to the plan are not undone
