"""add server_prices (финансовый учёт: сегменты истории цены сервера)

Цена сервера меняется во времени → храним историю сегментов (effective_from/to). Расход считается
accrual по сегментам (цена × длительность/период), валюты раздельно. amount_micros = цена × 1e6.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-07 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "server_prices",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("amount_micros", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("period", sa.String(length=8), nullable=False),
        sa.Column("anchor_day", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Float(), nullable=False),
        sa.Column("effective_to", sa.Float(), nullable=True),
    )
    op.create_index("server_prices_server_id_idx", "server_prices", ["server_id"])
    op.create_index("server_prices_scope_idx", "server_prices", ["server_id", "effective_from"])


def downgrade() -> None:
    op.drop_index("server_prices_scope_idx", table_name="server_prices")
    op.drop_index("server_prices_server_id_idx", table_name="server_prices")
    op.drop_table("server_prices")
