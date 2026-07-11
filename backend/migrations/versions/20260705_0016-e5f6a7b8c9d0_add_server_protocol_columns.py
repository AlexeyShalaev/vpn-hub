"""add server_protocols columns: image_version, max_clients, traffic health

Свёрнуто из трёх отдельных миграций (image_version / max_clients / traffic_collected_at+status+error),
которые по очереди добавляли колонки в одну и ту же таблицу.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("server_protocols", sa.Column("image_version", sa.String(length=48), nullable=True))
    op.add_column("server_protocols", sa.Column("max_clients", sa.Integer(), nullable=True))
    op.add_column("server_protocols", sa.Column("traffic_collected_at", sa.Float(), nullable=True))
    op.add_column("server_protocols", sa.Column("traffic_status", sa.String(length=24), nullable=True))
    op.add_column("server_protocols", sa.Column("traffic_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("server_protocols", "traffic_error")
    op.drop_column("server_protocols", "traffic_status")
    op.drop_column("server_protocols", "traffic_collected_at")
    op.drop_column("server_protocols", "max_clients")
    op.drop_column("server_protocols", "image_version")
