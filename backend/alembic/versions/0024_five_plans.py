"""five plans: Free Trial, Bronze, Silver, Gold, Platinum (limits are set later by the owner)

Revision ID: 0024
Revises: 0023
"""
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

RENAMES = [("Free", "Free Trial"), ("Starter", "Bronze"), ("Pro", "Silver"), ("Business", "Gold")]


def upgrade() -> None:
    bind = op.get_bind()
    for old, new in RENAMES:  # only the plans still carrying their first name; one the owner renamed is left alone
        taken = bind.execute(sa.text("SELECT 1 FROM plans WHERE name = :new"), {"new": new}).first()
        if not taken:
            bind.execute(sa.text("UPDATE plans SET name = :new WHERE name = :old"), {"new": new, "old": old})
    if bind.execute(sa.text("SELECT 1 FROM plans WHERE name = 'Platinum'")).first():
        return
    gold = bind.execute(sa.text("SELECT features, limits FROM plans WHERE name = 'Gold'")).first()
    features, limits = (gold if gold else ("{}", "{}"))
    features = features if isinstance(features, str) else json.dumps(features)
    limits = limits if isinstance(limits, str) else json.dumps(limits)
    bind.execute(
        sa.text("INSERT INTO plans (name, description, is_default, features, limits, created_at) VALUES ('Platinum', :description, :no, :features, :limits, :now)"),
        {"description": "The biggest plan. Its limits are set by the owner.", "no": False, "features": features, "limits": limits,
         "now": datetime.now(timezone.utc).replace(tzinfo=None)},
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("UPDATE users SET plan_id = NULL WHERE plan_id IN (SELECT id FROM plans WHERE name = 'Platinum')"))
    bind.execute(sa.text("DELETE FROM plans WHERE name = 'Platinum'"))
    for old, new in RENAMES:
        bind.execute(sa.text("UPDATE plans SET name = :old WHERE name = :new"), {"new": new, "old": old})
