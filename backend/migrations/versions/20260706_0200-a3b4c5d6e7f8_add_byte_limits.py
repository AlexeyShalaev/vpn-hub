"""add byte limits: server quota, per-user byte overrides, traffic_usage accumulator

Этап 3a системы лимитов. Байт-бюджеты per (user, server) за биллинг-период + квота трафика
самого сервера (тарифа). Учёт — накопитель `traffic_usage`, переживающий purge сырых сэмплов.
NULL везде = без лимита. Период сбрасывается по `servers.billing_day` (NULL → 1-е число месяца).

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-07-06 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("bandwidth_quota_bytes", sa.BigInteger(), nullable=True))
    op.add_column("servers", sa.Column("billing_day", sa.Integer(), nullable=True))
    op.add_column("groups", sa.Column("max_bytes", sa.BigInteger(), nullable=True))
    op.add_column("group_members", sa.Column("max_bytes", sa.BigInteger(), nullable=True))
    op.create_table(
        "traffic_usage",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("period_start", sa.Float(), nullable=False),
        sa.Column("rx_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tx_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float(), nullable=False, server_default="0"),
        sa.UniqueConstraint("server_id", "user_id", "period_start", name="traffic_usage_uq"),
    )
    op.create_index("traffic_usage_server_id_idx", "traffic_usage", ["server_id"])
    op.create_index("traffic_usage_user_id_idx", "traffic_usage", ["user_id"])
    op.create_index("traffic_usage_scope_idx", "traffic_usage", ["server_id", "user_id", "period_start"])


def downgrade() -> None:
    op.drop_index("traffic_usage_scope_idx", table_name="traffic_usage")
    op.drop_index("traffic_usage_user_id_idx", table_name="traffic_usage")
    op.drop_index("traffic_usage_server_id_idx", table_name="traffic_usage")
    op.drop_table("traffic_usage")
    op.drop_column("group_members", "max_bytes")
    op.drop_column("groups", "max_bytes")
    op.drop_column("servers", "billing_day")
    op.drop_column("servers", "bandwidth_quota_bytes")
