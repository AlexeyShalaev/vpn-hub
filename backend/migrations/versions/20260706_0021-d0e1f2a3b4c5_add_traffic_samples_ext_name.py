"""add traffic_samples.ext_name

Имя клиента из Amnezia clientsTable (clientName). Нужно, чтобы показывать имя external-клиента
(заведённого мимо панели — без нашего DeviceConfig). Для нон-external имя берётся из device_config.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-06 17:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("traffic_samples", sa.Column("ext_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("traffic_samples", "ext_name")
