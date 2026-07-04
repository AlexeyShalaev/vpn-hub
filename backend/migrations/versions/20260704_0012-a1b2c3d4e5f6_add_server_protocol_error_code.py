"""add server_protocols.error_code

Revision ID: a1b2c3d4e5f6
Revises: ae99804150d1
Create Date: 2026-07-04 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "ae99804150d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("server_protocols", sa.Column("error_code", sa.String(length=48), nullable=True))


def downgrade() -> None:
    op.drop_column("server_protocols", "error_code")
