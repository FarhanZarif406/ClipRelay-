"""plans have a price the owner sets (shown on the plan cards); Bronze lasts 15 days

Revision ID: 0033
Revises: 0032
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None

PRICES = {"Free Trial": 0, "Bronze": 999, "Silver": 2999, "Gold": 5499, "Platinum": 8999}


def upgrade() -> None:
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("price", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("currency", sa.String(length=8), nullable=False, server_default="PKR"))
    bind = op.get_bind()
    for name, price in PRICES.items():
        bind.execute(sa.text("UPDATE plans SET price = :p WHERE name = :n"), {"p": price, "n": name})
    row = bind.execute(sa.text("SELECT id, limits FROM plans WHERE name = 'Bronze'")).first()
    if row:
        limits = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
        limits["trial_days"] = 15
        bind.execute(sa.text("UPDATE plans SET limits = :l, description = :d WHERE id = :id"),
                     {"l": json.dumps(limits), "id": row[0],
                      "d": "15 days: 13 videos a day in Fast mode, 30 cloud videos, AI hook text, watermark, own fonts and test render."})


def downgrade() -> None:
    with op.batch_alter_table("plans", schema=None) as batch_op:
        batch_op.drop_column("currency")
        batch_op.drop_column("price")
