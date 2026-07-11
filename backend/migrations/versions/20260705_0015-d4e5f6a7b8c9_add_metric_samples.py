"""add metric_samples table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_samples",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("labels", sa.String(length=160), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("metric_samples_name_idx"), "metric_samples", ["name"], unique=False)
    op.create_index(op.f("metric_samples_at_idx"), "metric_samples", ["at"], unique=False)
    op.create_index("metric_samples_scope_idx", "metric_samples", ["name", "at"], unique=False)


def downgrade() -> None:
    op.drop_index("metric_samples_scope_idx", table_name="metric_samples")
    op.drop_index(op.f("metric_samples_at_idx"), table_name="metric_samples")
    op.drop_index(op.f("metric_samples_name_idx"), table_name="metric_samples")
    op.drop_table("metric_samples")
