"""Unit of Work — транзакция, экспонирующая репозитории (на sqlalchemy-foundation-kit)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy_foundation_kit import AsyncSQLAlchemyUnitOfWork

from vpnhub.infra.repositories import (
    AdminRepo,
    AuditRepo,
    DeviceRepo,
    GroupRepo,
    PoolRepo,
    ServerRepo,
    SessionRepo,
    SettingRepo,
    UserRepo,
)


class UowTransaction:
    """Одна транзакция: сессия + ленивые (но дешёвые) репозитории."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.admins = AdminRepo(session)
        self.users = UserRepo(session)
        self.sessions = SessionRepo(session)
        self.servers = ServerRepo(session)
        self.pools = PoolRepo(session)
        self.groups = GroupRepo(session)
        self.devices = DeviceRepo(session)
        self.settings = SettingRepo(session)
        self.audit = AuditRepo(session)


Uow = AsyncSQLAlchemyUnitOfWork[UowTransaction]


def build_uow(session_maker: async_sessionmaker[AsyncSession]) -> Uow:
    return AsyncSQLAlchemyUnitOfWork(session_maker, UowTransaction)
