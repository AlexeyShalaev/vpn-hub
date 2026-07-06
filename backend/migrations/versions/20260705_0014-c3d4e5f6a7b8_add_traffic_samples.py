"""add traffic_samples table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-05 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traffic_samples",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("proto", sa.String(length=24), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("device_config_id", sa.String(length=32), nullable=True),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("rx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("tx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("rx_delta", sa.BigInteger(), nullable=False),
        sa.Column("tx_delta", sa.BigInteger(), nullable=False),
        sa.Column("last_handshake", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("traffic_samples_server_id_idx"), "traffic_samples", ["server_id"], unique=False)
    op.create_index(op.f("traffic_samples_at_idx"), "traffic_samples", ["at"], unique=False)
    op.create_index("traffic_samples_scope_idx", "traffic_samples", ["server_id", "proto", "client_id"], unique=False)


def downgrade() -> None:
    op.drop_index("traffic_samples_scope_idx", table_name="traffic_samples")
    op.drop_index(op.f("traffic_samples_at_idx"), table_name="traffic_samples")
    op.drop_index(op.f("traffic_samples_server_id_idx"), table_name="traffic_samples")
    op.drop_table("traffic_samples")
