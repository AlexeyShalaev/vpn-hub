"""add server_metrics_hourly rollup table

Ярусное хранение хост-метрик (CPU/RAM/диск/online) как у трафика: сырьё server_metrics (сутки) →
почасовые агрегаты server_metrics_hourly (месяцы). Заполняется rollup-джобой; бэкфилл не нужен.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-07-09 04:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a0b1c2d3e4f5"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_metrics_hourly",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("bucket", sa.BigInteger(), nullable=False),
        sa.Column("cpu_pct_avg", sa.Float(), nullable=True),
        sa.Column("cpu_pct_max", sa.Float(), nullable=True),
        sa.Column("load1_avg", sa.Float(), nullable=True),
        sa.Column("load1_max", sa.Float(), nullable=True),
        sa.Column("mem_used_avg", sa.Float(), nullable=True),
        sa.Column("mem_total", sa.BigInteger(), nullable=True),
        sa.Column("disk_used", sa.BigInteger(), nullable=True),
        sa.Column("disk_total", sa.BigInteger(), nullable=True),
        sa.Column("tcp_estab_avg", sa.Float(), nullable=True),
        sa.Column("tcp_estab_max", sa.Integer(), nullable=True),
        sa.Column("online_clients_avg", sa.Float(), nullable=True),
        sa.Column("online_clients_max", sa.Integer(), nullable=True),
        sa.Column("samples_total", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "bucket", name="server_metrics_hourly_uq"),
    )
    op.create_index(op.f("server_metrics_hourly_server_id_idx"), "server_metrics_hourly", ["server_id"], unique=False)
    op.create_index(op.f("server_metrics_hourly_bucket_idx"), "server_metrics_hourly", ["bucket"], unique=False)
    op.create_index("server_metrics_hourly_scope_idx", "server_metrics_hourly", ["server_id", "bucket"], unique=False)


def downgrade() -> None:
    op.drop_index("server_metrics_hourly_scope_idx", table_name="server_metrics_hourly")
    op.drop_index(op.f("server_metrics_hourly_bucket_idx"), table_name="server_metrics_hourly")
    op.drop_index(op.f("server_metrics_hourly_server_id_idx"), table_name="server_metrics_hourly")
    op.drop_table("server_metrics_hourly")
