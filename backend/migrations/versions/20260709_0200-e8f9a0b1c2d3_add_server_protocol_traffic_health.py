"""add server_protocols traffic health fields

Сбор трафика переехал в monitor-тик и теперь хранит статус per-протокол (ok / stats_disabled /
container_down / unreachable / error) + время последнего успешного сбора. UI показывает честный
диагноз вместо общей фразы «нет данных».

Revision ID: e8f9a0b1c2d3
Revises: d6e7f8a9b0c1
Create Date: 2026-07-09 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("server_protocols", sa.Column("traffic_collected_at", sa.Float(), nullable=True))
    op.add_column("server_protocols", sa.Column("traffic_status", sa.String(length=24), nullable=True))
    op.add_column("server_protocols", sa.Column("traffic_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("server_protocols", "traffic_error")
    op.drop_column("server_protocols", "traffic_status")
    op.drop_column("server_protocols", "traffic_collected_at")
