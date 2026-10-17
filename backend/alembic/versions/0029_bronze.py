"""the Bronze plan as the owner set it: 20 days, 13 videos a day, 30 cloud videos over the 20 days, Fast mode

Revision ID: 0029
Revises: 0028
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

FEATURES = {
    "podcasts": False, "ai_captions": True, "ai_hook": True, "background_music": False, "watermark": True,
    "custom_fonts": True, "editing_presets": False, "test_render": True, "full_editing": False,
    "pc_editing": True, "cloud_editing": True,
}
LIMITS = {
    "videos_per_day": 13, "podcasts_per_day": 0, "buffer_keys": 1, "buffer_accounts": 3,
    "cloud_videos_per_month": 30, "auto_check_minutes": 0, "trial_days": 20, "skipped_keep_hours": 12,
}  # channels stay as they were (101)


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, features, limits FROM plans WHERE name = 'Bronze'")).first()
    if not row:
        return
    features = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    limits = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    features.update(FEATURES)
    limits.update(LIMITS)
    bind.execute(sa.text("UPDATE plans SET features = :f, limits = :l, description = :d WHERE id = :id"),
                 {"f": json.dumps(features), "l": json.dumps(limits), "id": row[0],
                  "d": "20 days: 13 videos a day in Fast mode, 30 cloud videos, AI hook text, watermark, own fonts and test render."})


def downgrade() -> None:
    pass  # the owner's later changes to the plan are not undone
