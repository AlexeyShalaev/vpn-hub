"""add server_protocols.max_clients

Мягкий (панельный) лимит числа конфигов-клиентов на протоколе сервера, задаётся владельцем.
NULL = без лимита. Это не физический потолок (у AmneziaWG адресов /24 растёт намеренно) —
выдача сверх лимита блокируется в services/configs. Занятость = active configs + external.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-06 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("server_protocols", sa.Column("max_clients", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("server_protocols", "max_clients")
