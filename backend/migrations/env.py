"""Alembic env (async). target_metadata через load_orm_metadata (foundation-kit)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy_foundation_kit import AsyncCConnection, load_orm_metadata

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


def _run(connection, target_schema: str | None = None) -> None:
    # target_schema задаётся, когда миграции гоняет alembic-gauntlet в изолированной схеме:
    # unqualified DDL и таблица версий уходят в неё, а не в public.
    if target_schema:
        connection.execute(text(f'SET search_path TO "{target_schema}"'))
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema=target_schema,
    )
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _MIGRATION_LOCK_KEY})
        context.run_migrations()


async def _run_async() -> None:
    url = _url()
    # За PgBouncer в transaction-режиме миграционному движку нужна та же pgbouncer-safe
    # настройка, что и у приложения: AsyncCConnection выдаёт UUID-имена prepared statements.
    # Без неё asyncpg именует их счётчиком (``__asyncpg_stmt_1__``), и на переиспользуемом
    # бэкенде они сталкиваются → DuplicatePreparedStatementError уже на version-чеке.
    # connect_args специфичны для asyncpg — применяем только к нему (в тестах SQLite).
    connect_args: dict[str, object] = {}
    if url.startswith("postgresql+asyncpg"):
        connect_args = {
            "connection_class": AsyncCConnection,
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }
    engine = create_async_engine(url, poolclass=None, connect_args=connect_args)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    # Драйвится извне (alembic-gauntlet / тесты миграций) через инъекцию sync-соединения в
    # `config.attributes` — используем его напрямую (мы уже внутри event loop, свой создавать нельзя).
    # Обычный `alembic upgrade` соединения не даёт → идём асинхронным путём приложения.
    injected = config.attributes.get("connection")
    if injected is not None:
        _run(injected, config.attributes.get("target_schema"))
    else:
        asyncio.run(_run_async())


if context.is_offline_mode():
    run_offline()
else:
    run_online()
