"""Инфраструктура интеграционных тестов: UoW поверх in-memory SQLite.

Модели портируемы (String/Text/Integer/Boolean/float), поэтому сервисы можно гонять
на SQLite без Postgres и Docker. Единственная несовместимость — server_default
`timezone('UTC', now())` из DatetimeColumnsMixin: регистрируем SQLite-функцию-заглушку
`timezone(tz, ts) -> ts` на каждом соединении.

Движок — функционального скоупа: свежая чистая БД на каждый тест (полная изоляция).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from sqlalchemy_foundation_kit import BaseTable

from vpnhub.infra.uow import Uow, build_uow


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """In-memory SQLite (одно соединение через StaticPool), схема создаётся с нуля."""
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    @event.listens_for(eng.sync_engine, "connect")
    def _register_pg_shims(dbapi_conn, _record) -> None:
        # PG server_default: timezone('UTC', now()); в SQLite такой функции нет.
        dbapi_conn.create_function("timezone", 2, lambda _tz, ts: ts)

    async with eng.begin() as conn:
        await conn.run_sync(BaseTable.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий; expire_on_commit=False — атрибуты доступны после commit."""
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def uow(session_maker: async_sessionmaker[AsyncSession]) -> Uow:
    """Unit of Work, который получают сервисы (та же БД, что и у сидов)."""
    return build_uow(session_maker)
