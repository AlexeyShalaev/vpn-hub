"""add server_metrics table

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-06 14:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_metrics",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("at", sa.Float(), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("load1", sa.Float(), nullable=True),
        # BigInteger: RAM/диск легко >2 ГБ (int32 overflow)
        sa.Column("mem_used", sa.BigInteger(), nullable=True),
        sa.Column("mem_total", sa.BigInteger(), nullable=True),
        sa.Column("disk_used", sa.BigInteger(), nullable=True),
        sa.Column("disk_total", sa.BigInteger(), nullable=True),
        sa.Column("tcp_estab", sa.Integer(), nullable=True),
        sa.Column("uptime_s", sa.Integer(), nullable=True),
        sa.Column("online_clients", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("server_metrics_server_id_idx"), "server_metrics", ["server_id"], unique=False)
    op.create_index(op.f("server_metrics_at_idx"), "server_metrics", ["at"], unique=False)
    op.create_index("server_metrics_scope_idx", "server_metrics", ["server_id", "at"], unique=False)


def downgrade() -> None:
    op.drop_index("server_metrics_scope_idx", table_name="server_metrics")
    op.drop_index(op.f("server_metrics_at_idx"), table_name="server_metrics")
    op.drop_index(op.f("server_metrics_server_id_idx"), table_name="server_metrics")
    op.drop_table("server_metrics")
