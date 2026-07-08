"""DI-контейнер: сервисы, используемые FastAPI-роутами, должны резолвиться."""

from __future__ import annotations

from vpnhub.api.config import get_settings
from vpnhub.infra.di import build_container
from vpnhub.services.finance import FinanceService


async def test__container__provides_finance_service(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://vpnhub:secret@localhost:5433/vpnhub")
    get_settings.cache_clear()
    container = build_container()
    try:
        assert isinstance(await container.get(FinanceService), FinanceService)
    finally:
        await container.close()
        get_settings.cache_clear()
