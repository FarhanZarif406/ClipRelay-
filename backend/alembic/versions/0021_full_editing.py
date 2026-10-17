"""plans get a "Full editing" switch; without it videos are made in Fast mode

Revision ID: 0021
Revises: 0020
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _rewrite(change) -> None:
    bind = op.get_bind()
    for plan_id, features in bind.execute(sa.text("SELECT id, features FROM plans")).all():
        value = features if isinstance(features, dict) else json.loads(features or "{}")
        change(value)
        bind.execute(sa.text("UPDATE plans SET features = :features WHERE id = :id"), {"features": json.dumps(value), "id": plan_id})


def upgrade() -> None:
    # A plan that already allowed the other editing extras (as Pro did) keeps full editing; the rest get Fast mode.
    _rewrite(lambda value: value.setdefault("full_editing", bool(value.get("editing_presets"))))


def downgrade() -> None:
    _rewrite(lambda value: value.pop("full_editing", None))
