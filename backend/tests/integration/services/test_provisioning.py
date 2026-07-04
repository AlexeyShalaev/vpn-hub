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
from vpnhub.infra.provisioning.ssh import SshError, SshResult
from vpnhub.services.provisioning import ProvisioningService

pytestmark = pytest.mark.integration

VENDOR = pc.VENDOR_AMNEZIA
PROTO_ID = pc.VENDOR_PROTOS[VENDOR][0]


class _NoopSsh:
    """Успешное SSH-подключение; .run() возвращает пустой успешный результат (docker start/stop и т.п.)."""

    def __init__(self, creds, *, connect_timeout=20.0):
        self.creds = creds

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def run(self, _cmd):
        return SshResult(stdout="", stderr="", exit_status=0)


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


async def test__mark_installing__subset__marks_only_selected_protocols(uow, settings, session_maker):
    """mark_installing с подмножеством protos помечает installing только выбранные, остальных не создаёт."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
    svc = ProvisioningService(uow, settings)

    # Act — ставим только xray
    async with uow.transaction() as tx:
        await svc.mark_installing(tx, server.id, VENDOR, ["xray"])

    # Assert — создан ровно один ServerProtocol (xray, installing), другие протоколы не заведены
    server2 = await _fetch_server(uow, server.id)
    protos = [p for p in server2.protocols if p.vendor == VENDOR]
    assert [p.proto for p in protos] == ["xray"]
    assert protos[0].state == "installing"


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


# ---- remove_protocol (пер-протокольное удаление + отзыв конфигов) ---------


async def test__remove_protocol__marks_absent_and_revokes_only_its_configs(uow, settings, session_maker, monkeypatch):
    """remove_protocol(xray): контейнер снесён, конфиги Xray удалены, конфиги другого протокола целы."""
    # Arrange
    from tests.factories.orm import make_device, make_device_config, make_server_protocol
    from vpnhub.services.servers import ServerService

    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray",
            vendor="amnezia",
            container="amnezia-xray",
            state="installed",
            installed=True,
            running=True,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
        )
        dev = await make_device(s, user_id=owner.id)
        # конфиги хранятся по label протокола: Xray и AmneziaWG
        await make_device_config(
            s, device_id=dev.id, server_id=server.id, vpn_type="amnezia", proto="Xray", client_id="c1"
        )
        await make_device_config(
            s, device_id=dev.id, server_id=server.id, vpn_type="amnezia", proto="AmneziaWG", client_id="c2"
        )

    monkeypatch.setattr(prov_mod, "SshClient", _NoopSsh)

    async def _noop_remove(_ssh, _vars):
        return None

    monkeypatch.setattr(prov_mod, "remove_container", _noop_remove)
    svc = ServerService(uow, settings)

    # Act
    await svc.remove_protocol(owner.id, server.id, "xray")

    # Assert — xray absent, awg не тронут
    sp_xray = await _fetch_sp(uow, server.id, "xray")
    sp_awg = await _fetch_sp(uow, server.id, "awg")
    assert sp_xray is not None and sp_xray.state == "absent" and not sp_xray.installed
    assert sp_awg is not None and sp_awg.state == "installed" and sp_awg.installed
    # конфиги: отозван только Xray-конфиг, AmneziaWG цел
    async with uow.query() as tx:
        rows = (
            (await tx.session.execute(select(m.DeviceConfig).where(m.DeviceConfig.server_id == server.id)))
            .scalars()
            .all()
        )
    assert {r.proto for r in rows} == {"AmneziaWG"}


async def test__protocol_op__stop_then_start__flips_only_that_protocol_running(
    uow, settings, session_maker, monkeypatch
):
    """protocol_op(stop|start) одного протокола меняет только его sp.running, не трогая соседний."""
    # Arrange
    from tests.factories.orm import make_server_protocol
    from vpnhub.services.servers import ServerService

    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, status="online")
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="xray",
            vendor="amnezia",
            container="amnezia-xray",
            state="installed",
            installed=True,
            running=True,
        )
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            container="amnezia-awg2",
            state="installed",
            installed=True,
            running=True,
        )
    monkeypatch.setattr(prov_mod, "SshClient", _NoopSsh)
    svc = ServerService(uow, settings)

    # Act — останавливаем только xray
    await svc.protocol_op(owner.id, server.id, "xray", "stop")

    # Assert — xray остановлен, awg работает; state обоих остаётся installed
    sp_xray = await _fetch_sp(uow, server.id, "xray")
    sp_awg = await _fetch_sp(uow, server.id, "awg")
    assert sp_xray.installed and not sp_xray.running and sp_xray.state == "installed"
    assert sp_awg.installed and sp_awg.running

    # Act — снова запускаем xray
    await svc.protocol_op(owner.id, server.id, "xray", "start")

    # Assert — xray снова работает
    sp_xray = await _fetch_sp(uow, server.id, "xray")
    assert sp_xray.installed and sp_xray.running
