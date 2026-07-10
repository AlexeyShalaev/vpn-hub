"""add traffic_hourly / traffic_daily rollup tables

Ярусное хранение трафика: сырьё traffic_samples (дни) → traffic_hourly (недели/месяцы) →
traffic_daily (годы). Свежее читается из сырья, старое — из агрегатов (на порядки меньше строк
и диска). Заполняются фоновой rollup-джобой (services/traffic_rollup); бэкфилл не нужен — первый
прогон джобы сроллапит всё имеющееся сырьё.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-07-09 03:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("traffic_hourly", "traffic_daily")


def _create(table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("proto", sa.String(length=24), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("device_config_id", sa.String(length=32), nullable=True),
        sa.Column("ext_name", sa.String(length=128), nullable=True),
        sa.Column("bucket", sa.BigInteger(), nullable=False),
        sa.Column("rx", sa.BigInteger(), nullable=False),
        sa.Column("tx", sa.BigInteger(), nullable=False),
        sa.Column("samples_total", sa.Integer(), nullable=False),
        sa.Column("samples_online", sa.Integer(), nullable=False),
        sa.Column("last_handshake", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "proto", "client_id", "bucket", name=f"{table}_uq"),
    )
    op.create_index(op.f(f"{table}_server_id_idx"), table, ["server_id"], unique=False)
    op.create_index(op.f(f"{table}_bucket_idx"), table, ["bucket"], unique=False)
    op.create_index(f"{table}_scope_idx", table, ["server_id", "proto", "client_id", "bucket"], unique=False)


def upgrade() -> None:
    for table in _TABLES:
        _create(table)


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"{table}_scope_idx", table_name=table)
        op.drop_index(op.f(f"{table}_bucket_idx"), table_name=table)
        op.drop_index(op.f(f"{table}_server_id_idx"), table_name=table)
        op.drop_table(table)
