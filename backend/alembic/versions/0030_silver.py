"""the Silver plan as the owner set it: 30 days, 20 videos a day, 70 cloud videos, full 1080p editing, hourly auto-check

Revision ID: 0030
Revises: 0029
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

FEATURES = {
    "podcasts": False, "ai_captions": True, "ai_hook": True, "background_music": True, "watermark": True,
    "custom_fonts": True, "editing_presets": True, "test_render": True, "full_editing": True,
    "pc_editing": True, "cloud_editing": True,
}
LIMITS = {
    "videos_per_day": 20, "podcasts_per_day": 0, "buffer_keys": 2, "buffer_accounts": 6,
    "cloud_videos_per_month": 70, "auto_check_minutes": 60, "trial_days": 30, "skipped_keep_hours": 24,
}  # channels stay as they were (210)


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, features, limits FROM plans WHERE name = 'Silver'")).first()
    if not row:
        return
    features = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    limits = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    features.update(FEATURES)
    limits.update(LIMITS)
    bind.execute(sa.text("UPDATE plans SET features = :f, limits = :l, description = :d WHERE id = :id"),
                 {"f": json.dumps(features), "l": json.dumps(limits), "id": row[0],
                  "d": "30 days: 20 videos a day in full 1080p editing, 70 cloud videos, music, presets and test render, hourly auto-check."})


def downgrade() -> None:
    pass  # the owner's later changes to the plan are not undone
