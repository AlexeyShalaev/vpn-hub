"""Интеграционные тесты ProvisioningService: проверка сервера, пометка и ошибка установки.

SSH-слой подменяется фейком (реальные контейнеры не нужны): проверяем оркестрацию и запись
в БД, а не эмуляцию сервера — крипто/сборка конфигов покрыты в test_provisioning_pure.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

import vpnhub.services.provisioning as prov_mod
from tests.factories.orm import make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.ssh import SshError
from vpnhub.services.provisioning import ProvisioningService

pytestmark = pytest.mark.integration

VENDOR = pc.VENDOR_AMNEZIA
PROTO_ID = pc.VENDOR_PROTOS[VENDOR][0]


class _NoopSsh:
    """Успешное SSH-подключение без реальных операций."""

    def __init__(self, creds, *, connect_timeout=20.0):
        self.creds = creds

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _RaisingSsh:
    """SSH, падающий на подключении (сервер недоступен / установка провалилась)."""

    def __init__(self, creds, *, connect_timeout=20.0):
        pass

    async def __aenter__(self):
        raise SshError("boom")

    async def __aexit__(self, *exc):
        return False


async def _fetch_server(uow, server_id):
    async with uow.query() as tx:
        return await tx.servers.get(server_id)


async def _fetch_sp(uow, server_id, proto_id):
    async with uow.query() as tx:
        res = await tx.session.execute(
            select(m.ServerProtocol).where(m.ServerProtocol.server_id == server_id, m.ServerProtocol.proto == proto_id)
        )
        return res.scalar_one_or_none()


# ---- check_server --------------------------------------------------------


async def test__check_server__ssh_ok__returns_online_with_containers(uow, settings, session_maker, monkeypatch):
    """SSH отвечает + docker ps вернул контейнеры → (online, latency, {container: port})."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    monkeypatch.setattr(prov_mod, "SshClient", _NoopSsh)

    async def _fake_containers(_ssh):
        return {"amnezia-awg": "51820"}

    monkeypatch.setattr(prov_mod, "already_installed_containers", _fake_containers)
    svc = ProvisioningService(uow, settings)
    server = await _fetch_server(uow, server.id)

    # Act
    online, latency, running = await svc.check_server(server)

    # Assert
    assert online is True
    assert running == {"amnezia-awg": "51820"}
    assert latency is not None and latency >= 0


async def test__check_server__ssh_fails__returns_offline(uow, settings, session_maker, monkeypatch):
    """SSH недоступен → (False, None, {})."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    monkeypatch.setattr(prov_mod, "SshClient", _RaisingSsh)
    svc = ProvisioningService(uow, settings)
    server = await _fetch_server(uow, server.id)

    # Act
    online, latency, running = await svc.check_server(server)

    # Assert
    assert online is False
    assert latency is None
    assert running == {}


# ---- mark_installing -----------------------------------------------------


async def test__mark_installing__creates_protocols_in_installing_state(uow, settings, session_maker):
    """mark_installing создаёт протоколы вендора и переводит их в state='installing'."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    svc = ProvisioningService(uow, settings)

    # Act
    async with uow.transaction() as tx:
        await svc.mark_installing(tx, server.id, VENDOR)

    # Assert
    server2 = await _fetch_server(uow, server.id)
    protos = [p for p in server2.protocols if p.vendor == VENDOR]
    assert len(protos) == len(pc.VENDOR_PROTOS[VENDOR])
    assert all(p.state == "installing" and not p.installed and not p.running for p in protos)


# ---- install error path --------------------------------------------------


async def test__install_one__ssh_failure__marks_protocol_error(uow, settings, session_maker, monkeypatch):
    """Сбой SSH при установке → протокол переходит в state='error' с текстом (не зависает в installing)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    monkeypatch.setattr(prov_mod, "SshClient", _RaisingSsh)
    svc = ProvisioningService(uow, settings)
    server = await _fetch_server(uow, server.id)
    creds = svc.creds(server)

    # Act
    await svc._install_one(server.id, PROTO_ID, creds, server.ip, server.name)

    # Assert
    sp = await _fetch_sp(uow, server.id, PROTO_ID)
    assert sp is not None
    assert sp.state == "error"
    assert sp.error
    assert not sp.installed and not sp.running
