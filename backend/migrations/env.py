"""Alembic env (async). target_metadata через load_orm_metadata (foundation-kit)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy_foundation_kit import load_orm_metadata

config = context.config

MODELS_MODULES = ["vpnhub.infra.db.orm.models"]
target_metadata = load_orm_metadata(MODELS_MODULES)

# Сериализация одновременного `alembic upgrade` из нескольких инстансов (k8s multi-replica,
# rolling-деплой): транзакционный advisory-lock. Второй стартующий процесс ждёт первого и,
# получив лок, видит уже накатанную схему → run_migrations становится no-op. Лок снимается
# автоматически при завершении транзакции миграции. Только PostgreSQL (в тестах — SQLite).
_MIGRATION_LOCK_KEY = 0x76706E68  # "vpnh"


def _url() -> str:
    return (
        config.get_main_option("sqlalchemy.url")
        or os.environ.get("DATABASE_URL")
        or "postgresql+asyncpg://vpnhub:secret@localhost:5433/vpnhub"
    )


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _MIGRATION_LOCK_KEY})
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(_url(), poolclass=None)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(_run_async())
