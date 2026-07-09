"""add traffic_peer_state (последний кумулятив per клиент)

Дельты трафика считались от последнего сырого сэмпла (скан истории на каждый тик); после purge
сэмплов простаивавшего клиента следующая дельта = полный кумулятив (ложный всплеск трафика).
Таблица состояния чинит оба дефекта: O(1)-чтение и устойчивость к ретеншну. Бэкфилл — из
последних сэмплов (`vpnhub.infra.db.backfills.backfill_traffic_peer_state`).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-07-09 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from vpnhub.infra.db.backfills import backfill_traffic_peer_state

revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traffic_peer_state",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("server_id", sa.String(length=32), nullable=False),
        sa.Column("proto", sa.String(length=24), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("device_config_id", sa.String(length=32), nullable=True),
        sa.Column("ext_name", sa.String(length=128), nullable=True),
        sa.Column("rx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("tx_bytes", sa.BigInteger(), nullable=False),
        sa.Column("rx_speed", sa.Float(), nullable=False),
        sa.Column("tx_speed", sa.Float(), nullable=False),
        sa.Column("last_at", sa.Float(), nullable=False),
        sa.Column("last_handshake", sa.Float(), nullable=True),
        sa.Column("online", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_id", "proto", "client_id", name="traffic_peer_state_uq"),
    )
    op.create_index(op.f("traffic_peer_state_server_id_idx"), "traffic_peer_state", ["server_id"], unique=False)
    backfill_traffic_peer_state(op.get_bind())


def downgrade() -> None:
    op.drop_index(op.f("traffic_peer_state_server_id_idx"), table_name="traffic_peer_state")
    op.drop_table("traffic_peer_state")
