"""add traffic_samples.online

Per-client онлайн-флаг из stats движка (xray statsUserOnline / hysteria /online). NULL для wg —
там онлайн вычисляется по свежести last_handshake на чтении.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-06 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("traffic_samples", sa.Column("online", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("traffic_samples", "online")
