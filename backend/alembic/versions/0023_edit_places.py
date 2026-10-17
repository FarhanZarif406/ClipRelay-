"""videos are edited on the member's own PC (PC Helper) first, else in Google Cloud Run

Revision ID: 0023
Revises: 0022
"""
import json

import sqlalchemy as sa
from alembic import op

from app.models.base import JSONType, UTCDateTime

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def _rewrite(change) -> None:
    bind = op.get_bind()
    for plan_id, features in bind.execute(sa.text("SELECT id, features FROM plans")).all():
        value = features if isinstance(features, dict) else json.loads(features or "{}")
        change(value)
        bind.execute(sa.text("UPDATE plans SET features = :features WHERE id = :id"), {"features": json.dumps(value), "id": plan_id})


def upgrade() -> None:
    op.create_table(
        "editor_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("version", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_editor_devices_user_id", "editor_devices", ["user_id"])
    op.create_index("ix_editor_devices_token_hash", "editor_devices", ["token_hash"], unique=True)
    op.create_table(
        "editor_pairings",
        sa.Column("code_hash", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
    )
    op.create_index("ix_editor_pairings_user_id", "editor_pairings", ["user_id"])
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("edit_place", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("editor_device_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("edit_spec", JSONType, nullable=True))
        batch_op.add_column(sa.Column("edit_token_hash", sa.String(length=64), nullable=True))
        batch_op.create_index("ix_jobs_editor_device_id", ["editor_device_id"], unique=False)
        batch_op.create_foreign_key("fk_jobs_editor_device_id", "editor_devices", ["editor_device_id"], ["id"], ondelete="SET NULL")
    # Every plan may use both for now; the owner decides per plan later (Accounts → Plans).
    _rewrite(lambda value: value.update(pc_editing=True, cloud_editing=True))


def downgrade() -> None:
    _rewrite(lambda value: [value.pop(key, None) for key in ("pc_editing", "cloud_editing")])
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_jobs_editor_device_id", type_="foreignkey")
        batch_op.drop_index("ix_jobs_editor_device_id")
        for column in ("edit_token_hash", "edit_spec", "editor_device_id", "edit_place"):
            batch_op.drop_column(column)
    op.drop_table("editor_pairings")
    op.drop_table("editor_devices")
