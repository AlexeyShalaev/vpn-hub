"""add passkeys and webauthn challenges

Ключи доступа (WebAuthn): `passkeys` — зарегистрированные учётные данные пользователя,
`webauthn_challenges` — одноразовые челленджи церемоний с коротким TTL (в БД, а не в памяти
процесса, чтобы вход работал при нескольких репликах).

Revision ID: c7d8e9f0a1b2
Revises: b1c2d3e4f5a6
Create Date: 2026-11-12 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "passkeys",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
        sa.Column("transports", sa.JSON(), nullable=False),
        sa.Column("aaguid", sa.String(length=36), nullable=False),
        sa.Column("backed_up", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("last_used_at", sa.Float(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("timezone('UTC', now())"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("timezone('UTC', now())"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("passkeys_user_id_fkey"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("passkeys_pkey")),
        sa.UniqueConstraint("credential_id", name=op.f("passkeys_credential_id_key")),
    )
    op.create_index(op.f("passkeys_user_id_idx"), "passkeys", ["user_id"], unique=False)
    op.create_table(
        "webauthn_challenges",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("challenge", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", sa.String(length=16), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("webauthn_challenges_pkey")),
    )
    op.create_index(op.f("webauthn_challenges_expires_at_idx"), "webauthn_challenges", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("webauthn_challenges_expires_at_idx"), table_name="webauthn_challenges")
    op.drop_table("webauthn_challenges")
    op.drop_index(op.f("passkeys_user_id_idx"), table_name="passkeys")
    op.drop_table("passkeys")
