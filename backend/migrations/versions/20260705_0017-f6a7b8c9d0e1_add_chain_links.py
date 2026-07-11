"""add chain_links (multihop entry -> exit)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-05 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chain_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner_user_id", sa.String(length=32), nullable=False),
        sa.Column("entry_server_id", sa.String(length=32), nullable=False),
        sa.Column("exit_server_id", sa.String(length=32), nullable=False),
        sa.Column("proto", sa.String(length=24), nullable=False),
        sa.Column("exit_client_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("timezone('UTC', now())"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["entry_server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exit_server_id"], ["servers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_server_id", "proto", name="chain_links_uq"),
    )
    op.create_index("chain_links_owner_user_id_idx", "chain_links", ["owner_user_id"])
    op.create_index("chain_links_entry_server_id_idx", "chain_links", ["entry_server_id"])
    op.create_index("chain_links_exit_server_id_idx", "chain_links", ["exit_server_id"])


def downgrade() -> None:
    op.drop_index("chain_links_exit_server_id_idx", table_name="chain_links")
    op.drop_index("chain_links_entry_server_id_idx", table_name="chain_links")
    op.drop_index("chain_links_owner_user_id_idx", table_name="chain_links")
    op.drop_table("chain_links")
