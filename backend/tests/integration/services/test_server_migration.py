"""Интеграционные тесты миграции сервера на новый VPS (ServerService.migrate).

Проверяем оркестрацию (in-memory SQLite): смена SSH-реквизитов, перевод установленных
протоколов в installing, пометка выданных конфигов revoked, обнуление ledger-долга и
постановка фоновой переустановки — без реального SSH (schedule_install подменяется).
"""

from __future__ import annotations

import pytest

from tests.factories.orm import (
    make_device,
    make_device_config,
    make_server,
    make_server_protocol,
    make_user,
    seed,
)
from vpnhub.core.errors import BadRequest
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import decrypt_secret
from vpnhub.services.provisioning import ProvisioningService
from vpnhub.services.servers import ServerService

pytestmark = pytest.mark.integration

NEW_IP = "198.51.100.7"


def _capture_schedule(monkeypatch) -> list[tuple[str, str, tuple[str, ...] | None]]:
    """Подменить фоновую установку: копим (server_id, vendor, proto_ids) вместо реального SSH."""
    calls: list[tuple[str, str, tuple[str, ...] | None]] = []

    def fake(self, server_id, vendor, proto_ids=None):
        calls.append((server_id, vendor, tuple(proto_ids) if proto_ids else None))

    monkeypatch.setattr(ProvisioningService, "schedule_install", fake)
    return calls


async def _seed_migratable(session_maker):
    """Сервер с установленными awg (amnezia) и openvpn + выданный конфиг с ledger-долгом."""
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia", "openvpn"))
        await make_server_protocol(
            s,
            server_id=server.id,
            proto="awg",
            vendor="amnezia",
            state="installed",
            installed=True,
            running=True,
            material_encrypted="enc-old-material",
            pending_revoke_json='["stale-client"]',
        )
        await make_server_protocol(
            s, server_id=server.id, proto="openvpn", vendor="openvpn", state="installed", installed=True, running=True
        )
        # не установленный протокол — мигрировать нечего, installing он получить не должен
        await make_server_protocol(s, server_id=server.id, proto="xray", vendor="amnezia", state="absent")
        device = await make_device(s, user_id=owner.id)
        cfg_active = await make_device_config(
            s, device_id=device.id, server_id=server.id, vpn_type="amnezia", proto="AmneziaWG", client_id="pub1"
        )
        cfg_revoked = await make_device_config(
            s,
            device_id=device.id,
            server_id=server.id,
            vpn_type="openvpn",
            proto="OpenVPN UDP",
            status="revoked",
            client_id="cn1",
        )
    return owner, server, cfg_active, cfg_revoked


async def test__migrate__updates_creds_marks_installing_and_revokes_configs(
    uow, settings, session_maker, monkeypatch
) -> None:
    """Миграция: новые реквизиты записаны, installed-протоколы → installing (переустановка в фоне),

    активные конфиги → revoked (перевыдача), ledger-долг старого хоста обнулён."""
    # Arrange
    owner, server, cfg_active, cfg_revoked = await _seed_migratable(session_maker)
    calls = _capture_schedule(monkeypatch)
    svc = ServerService(uow, settings)

    # Act
    result = await svc.migrate(
        owner.id,
        server.id,
        {"ip": NEW_IP, "sshPort": "2222", "sshUser": "deploy", "auth": "password", "secret": "newpass"},
    )

    # Assert: сводка ответа
    assert result["server"]["ip"] == NEW_IP
    assert result["reinstall"] == {"amnezia": ["awg"], "openvpn": ["openvpn"]}
    assert result["configsRevoked"] == 1  # уже revoked конфиг не считаем повторно

    # Assert: реквизиты и состояние в БД
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        assert (srv.ip, srv.ssh_port, srv.ssh_user, srv.ssh_auth) == (NEW_IP, "2222", "deploy", "password")
        assert decrypt_secret(settings.secret_key, srv.ssh_secret_encrypted) == "newpass"
        assert srv.status == "unknown"
        by_proto = {p.proto: p for p in srv.protocols}
        assert by_proto["awg"].state == "installing"
        assert by_proto["openvpn"].state == "installing"
        assert by_proto["xray"].state == "absent"  # не был установлен — не трогаем
        assert all(p.pending_revoke_json is None for p in srv.protocols)
        cfg1 = await tx.session.get(m.DeviceConfig, cfg_active.id)
        cfg2 = await tx.session.get(m.DeviceConfig, cfg_revoked.id)
        assert cfg1.status == "revoked"
        assert cfg2.status == "revoked"

    # Assert: фоновая переустановка поставлена по каждому вендору с его протоколами
    assert sorted(calls) == [(server.id, "amnezia", ("awg",)), (server.id, "openvpn", ("openvpn",))]


async def test__migrate__no_secret__keeps_existing_secret(uow, settings, session_maker, monkeypatch) -> None:
    """Пустой secret → текущий SSH-секрет сохраняется (тот же ключ подходит к новому VPS)."""
    # Arrange
    owner, server, *_ = await _seed_migratable(session_maker)
    _capture_schedule(monkeypatch)
    svc = ServerService(uow, settings)
    await svc.update(owner.id, server.id, {"secret": "oldkey"})

    # Act
    await svc.migrate(owner.id, server.id, {"ip": NEW_IP})

    # Assert
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        assert decrypt_secret(settings.secret_key, srv.ssh_secret_encrypted) == "oldkey"
        assert srv.ip == NEW_IP


async def test__migrate__invalid_ip__raises_bad_request(uow, settings, session_maker, monkeypatch) -> None:
    """Невалидный/пустой IP → BadRequest, ничего не меняется и фоновая установка не ставится."""
    # Arrange
    owner, server, *_ = await _seed_migratable(session_maker)
    calls = _capture_schedule(monkeypatch)
    svc = ServerService(uow, settings)

    # Act / Assert
    with pytest.raises(BadRequest):
        await svc.migrate(owner.id, server.id, {"ip": "not valid; rm -rf"})
    with pytest.raises(BadRequest):
        await svc.migrate(owner.id, server.id, {})
    assert calls == []
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        assert srv.ip == "203.0.113.10"  # ip из фабрики не изменился
