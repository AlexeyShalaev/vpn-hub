"""add server provider_metadata

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-07-07 23:15:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5d6e7f8a9b0"
down_revision: str | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        col_type = postgresql.JSONB()
        default = sa.text("'{}'::jsonb")
    else:
        col_type = sa.JSON()
        default = sa.text("'{}'")

    op.add_column(
        "servers",
        sa.Column("provider_metadata", col_type, nullable=False, server_default=default),
    )
    op.alter_column("servers", "provider_metadata", server_default=None)


def downgrade() -> None:
    op.drop_column("servers", "provider_metadata")
