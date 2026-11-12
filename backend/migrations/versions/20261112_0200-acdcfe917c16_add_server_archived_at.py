"""add servers.archived_at

Архив серверов: владелец убирает выключенный/неиспользуемый сервер с глаз, не теряя историю
(трафик, метрики, финансы, аудит). NULL = активный сервер. Архивный сервер пропускают фоновые
циклы (мониторинг, синк, сбор метрик), участникам он не виден, расход по нему не начисляется.

Revision ID: acdcfe917c16
Revises: c7d8e9f0a1b2
Create Date: 2026-11-12 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "acdcfe917c16"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("servers", sa.Column("archived_at", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("servers", "archived_at")
