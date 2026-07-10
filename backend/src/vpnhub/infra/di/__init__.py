"""Dishka DI: провайдеры по слоям (APP-scope) + фабрика контейнера."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy_foundation_kit import AsyncSessionManager

from vpnhub.api.config import Settings, get_settings
from vpnhub.infra.db.engine import build_session_manager
from vpnhub.infra.events import EventBus, get_event_bus
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.infra.uow import Uow, build_uow
from vpnhub.services.admin import AdminService
from vpnhub.services.audit import AuditService
from vpnhub.services.auth import AuthService
from vpnhub.services.backups import BackupService
from vpnhub.services.configs import ConfigService
from vpnhub.services.devices import DeviceService
from vpnhub.services.finance import FinanceService
from vpnhub.services.groups import GroupService
from vpnhub.services.hostmetrics import HostMetricsService
from vpnhub.services.me import MeService
from vpnhub.services.metrics import MetricsService
from vpnhub.services.multihop import ChainService
from vpnhub.services.pools import PoolService
from vpnhub.services.server_access import ServerAccessService
from vpnhub.services.servers import ServerService
from vpnhub.services.sync import SyncService
from vpnhub.services.traffic import TrafficService
from vpnhub.services.traffic_rollup import TrafficRollupService


class AppProvider(Provider):
    scope = Scope.APP

    @provide
    def settings(self) -> Settings:
        return get_settings()

    @provide
    def event_bus(self) -> EventBus:
        # Модульный синглтон: publisher-ы (сервисы, часть которых создаётся ad-hoc без DI)
        # и subscriber (SSE-эндпоинт через DI) обязаны видеть ОДИН инстанс шины.
        return get_event_bus()

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

    # Сервисы с realtime-шиной: Optional-параметр Dishka не резолвит, поэтому явные фабрики
    # (ad-hoc-конструкции (uow, settings) берут тот же синглтон через дефолт bus=None).
    @provide
    def servers(self, uow: Uow, settings: Settings, bus: EventBus) -> ServerService:
        return ServerService(uow, settings, bus)

    @provide
    def sync(self, uow: Uow, settings: Settings, bus: EventBus) -> SyncService:
        return SyncService(uow, settings, bus)

    provider_store = provide(ProviderStore)
    auth = provide(AuthService)
    server_access = provide(ServerAccessService)
    pools = provide(PoolService)
    groups = provide(GroupService)
    devices = provide(DeviceService)
    configs = provide(ConfigService)
    me = provide(MeService)
    admin = provide(AdminService)
    backups = provide(BackupService)
    audit = provide(AuditService)
    finance = provide(FinanceService)
    traffic = provide(TrafficService)
    traffic_rollup = provide(TrafficRollupService)
    host_metrics = provide(HostMetricsService)
    metrics = provide(MetricsService)
    chains = provide(ChainService)


def build_container() -> AsyncContainer:
    return make_async_container(AppProvider())
