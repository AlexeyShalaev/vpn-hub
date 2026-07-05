"""add audit_events table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("actor_kind", sa.String(length=8), nullable=False),
        sa.Column("actor_id", sa.String(length=32), nullable=True),
        sa.Column("actor_name", sa.String(length=120), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("target_kind", sa.String(length=24), nullable=True),
        sa.Column("target_id", sa.String(length=32), nullable=True),
        sa.Column("owner_user_id", sa.String(length=32), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        # DatetimeColumnsMixin (created_at/updated_at) — те же server_default, что и в остальных таблицах
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("timezone('UTC', now())"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("timezone('UTC', now())"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("audit_events_at_idx"), "audit_events", ["at"], unique=False)
    op.create_index(op.f("audit_events_type_idx"), "audit_events", ["type"], unique=False)
    op.create_index(op.f("audit_events_actor_id_idx"), "audit_events", ["actor_id"], unique=False)
    op.create_index(op.f("audit_events_target_id_idx"), "audit_events", ["target_id"], unique=False)
    op.create_index(op.f("audit_events_owner_user_id_idx"), "audit_events", ["owner_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("audit_events_owner_user_id_idx"), table_name="audit_events")
    op.drop_index(op.f("audit_events_target_id_idx"), table_name="audit_events")
    op.drop_index(op.f("audit_events_actor_id_idx"), table_name="audit_events")
    op.drop_index(op.f("audit_events_type_idx"), table_name="audit_events")
    op.drop_index(op.f("audit_events_at_idx"), table_name="audit_events")
    op.drop_table("audit_events")
