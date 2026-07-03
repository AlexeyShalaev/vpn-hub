"""Dishka DI: провайдеры по слоям (APP-scope) + фабрика контейнера."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy_foundation_kit import AsyncSessionManager

from vpnhub.api.config import Settings, get_settings
from vpnhub.infra.db.engine import build_session_manager
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.infra.uow import Uow, build_uow
from vpnhub.services.admin import AdminService
from vpnhub.services.auth import AuthService
from vpnhub.services.backups import BackupService
from vpnhub.services.configs import ConfigService
from vpnhub.services.devices import DeviceService
from vpnhub.services.groups import GroupService
from vpnhub.services.me import MeService
from vpnhub.services.pools import PoolService
from vpnhub.services.server_access import ServerAccessService
from vpnhub.services.servers import ServerService
from vpnhub.services.sync import SyncService


class AppProvider(Provider):
    scope = Scope.APP

    @provide
    def settings(self) -> Settings:
        return get_settings()

    @provide
    async def session_manager(self, settings: Settings) -> AsyncIterator[AsyncSessionManager]:
        sm = build_session_manager(settings)
        yield sm
        await sm.aclose()

    @provide
    def uow(self, sm: AsyncSessionManager) -> Uow:
        maker: Any = sm.session_maker
        if not isinstance(maker, async_sessionmaker) and callable(maker):
            maker = maker()
        return build_uow(maker)

    provider_store = provide(ProviderStore)
    auth = provide(AuthService)
    servers = provide(ServerService)
    server_access = provide(ServerAccessService)
    pools = provide(PoolService)
    groups = provide(GroupService)
    devices = provide(DeviceService)
    configs = provide(ConfigService)
    me = provide(MeService)
    admin = provide(AdminService)
    backups = provide(BackupService)
    sync = provide(SyncService)


def build_container() -> AsyncContainer:
    return make_async_container(AppProvider())
