"""Интеграция: ProvisioningService публикует realtime-сигнал при смене state протокола.

SSH-слой подменяется фейком (как в test_provisioning): проверяем, что на терминальном переходе
установки (installing → error) в шину прилетает ≥1 события `server` с id сервера.
"""

from __future__ import annotations

import asyncio

import pytest

import vpnhub.services.provisioning as prov_mod
from tests.factories.orm import make_server, make_user, seed
from vpnhub.infra.events import TOPIC_SERVER, EventBus
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.ssh import SshError
from vpnhub.services.provisioning import ProvisioningService

pytestmark = pytest.mark.integration

VENDOR = pc.VENDOR_AMNEZIA
PROTO_ID = pc.VENDOR_PROTOS[VENDOR][0]


class _RaisingSsh:
    def __init__(self, creds, *, connect_timeout=20.0):
        pass

    async def __aenter__(self):
        raise SshError("boom")

    async def __aexit__(self, *exc):
        return False


async def _drain(bus: EventBus, sub, count: int, timeout: float = 1.0) -> list:
    """Считать `count` событий из подписки (с таймаутом на случай, если публикации не было)."""
    out = []
    for _ in range(count):
        out.append(await asyncio.wait_for(sub.__anext__(), timeout=timeout))
    return out


async def test__install_one__error__publishes_server_event(uow, settings, session_maker, monkeypatch):
    """Сбой установки (installing → error) публикует событие `server` с id сервера."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    monkeypatch.setattr(prov_mod, "SshClient", _RaisingSsh)

    bus = EventBus()
    svc = ProvisioningService(uow, settings, bus=bus)
    async with uow.query() as tx:
        server = await tx.servers.get(server.id)
    creds = svc.creds(server)

    sub = bus.subscribe()
    getter = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)  # зарегистрировать подписку до публикации

    # Act
    await svc._install_one(server.id, PROTO_ID, creds, server.ip, server.name)

    # Assert
    event = await asyncio.wait_for(getter, timeout=1.0)
    assert event.topic == TOPIC_SERVER
    assert event.entity_id == server.id
    await sub.aclose()


async def test__provisioning_service__default_bus_is_module_singleton(uow, settings):
    """Без явного bus сервис берёт модульный синглтон — publisher и SSE-subscriber делят шину."""
    from vpnhub.infra.events import get_event_bus

    svc = ProvisioningService(uow, settings)
    assert svc.bus is get_event_bus()
