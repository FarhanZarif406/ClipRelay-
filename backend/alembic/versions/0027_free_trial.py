"""the Free Trial plan as the owner set it: 4 days, 10 videos a day, AI hook, watermark and own fonts on the first day only

Revision ID: 0027
Revises: 0026
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

FEATURES = {
    "podcasts": False, "ai_captions": True, "ai_hook": "first_day", "background_music": False, "watermark": "first_day",
    "custom_fonts": "first_day", "editing_presets": False, "test_render": False, "full_editing": False,
    "pc_editing": True, "cloud_editing": True,
}
LIMITS = {
    "channels": 50, "videos_per_day": 10, "podcasts_per_day": 0, "buffer_keys": 1, "buffer_accounts": 3,
    "cloud_videos_per_month": 3, "auto_check_minutes": 0, "trial_days": 4, "skipped_keep_hours": 8,
}


def upgrade() -> None:
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id, features, limits FROM plans WHERE name = 'Free Trial'")).first()
    if not row:
        return
    features = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
    limits = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
    features.update(FEATURES)
    limits.update(LIMITS)
    bind.execute(sa.text("UPDATE plans SET features = :f, limits = :l, description = :d WHERE id = :id"),
                 {"f": json.dumps(features), "l": json.dumps(limits), "id": row[0],
                  "d": "4-day trial: 10 videos a day in Fast mode on the member's PC, 3 cloud videos; AI hook, watermark and own fonts on the first day."})


def downgrade() -> None:
    pass  # the owner's later changes to the plan are not undone
