"""add group/member device-limit overrides

Этап 2 системы лимитов: лимит числа устройств на пользователя.
Иерархия: глобальный дефолт (DB setting `default_devices_per_user`, дефолт 5)
→ override группы (`groups.max_devices`) → персональный override участника
(`group_members.max_devices`). Эффективный лимит = max по активным членствам
(доступ аддитивный). NULL = наследовать уровень выше.

Revision ID: f2a3b4c5d6e7
Revises: a7b8c9d0e1f2
Create Date: 2026-07-06 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("max_devices", sa.Integer(), nullable=True))
    op.add_column("group_members", sa.Column("max_devices", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("group_members", "max_devices")
    op.drop_column("groups", "max_devices")
