"""Интеграционные тесты DeviceService (list / create / delete + ledger долга на снятие)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import vpnhub.services.provisioning as prov_mod
from tests.factories.orm import make_device, make_server, make_user, seed
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.services.devices import DeviceService
from vpnhub.services.sync_logic import parse_pending

pytestmark = pytest.mark.integration


@pytest.fixture
def no_revoke(monkeypatch):
    """Замокать ProvisioningService.revoke_on_servers и собирать переданные refs."""
    calls: list[list[tuple[str, str, str]]] = []

    async def fake_revoke(self, refs):
        calls.append(list(refs))

    monkeypatch.setattr(prov_mod.ProvisioningService, "revoke_on_servers", fake_revoke)
    return calls


async def test__list__user_devices__returns_device_to_dict_shape(uow, settings, session_maker):
    """list() возвращает устройства юзера в форме device_to_dict вместе с их конфигами."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
        srv = await make_server(s, owner_id=user.id)
        dev = await make_device(s, user_id=user.id, name="iPhone", platform="ios")
        s.add(
            m.DeviceConfig(
                device_id=dev.id,
                server_id=srv.id,
                vpn_type="amnezia",
                proto="AmneziaWG",
                status="active",
                client_id="PUB",
            )
        )
    svc = DeviceService(uow, settings)

    # Act
    result = await svc.list(user.id)

    # Assert
    assert len(result) == 1
    d = result[0]
    assert d == {
        "id": dev.id,
        "name": "iPhone",
        "platform": "ios",
        "configs": [{"serverId": srv.id, "type": "amnezia", "proto": "AmneziaWG", "status": "active"}],
    }


async def test__list__other_users_devices__not_returned(uow, settings, session_maker):
    """list() отдаёт только устройства запрошенного юзера, чужие не попадают."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        other = await make_user(s, phone="+79005556677")
        await make_device(s, user_id=other.id, name="Чужой телефон")
    svc = DeviceService(uow, settings)

    # Act
    result = await svc.list(owner.id)

    # Assert
    assert result == []


async def test__create__empty_name__raises_bad_request(uow, settings, session_maker):
    """create() с пустым именем → BadRequest (код BAD_REQUEST, http 400)."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
    svc = DeviceService(uow, settings)

    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.create(user.id, "", "ios")
    assert exc.value.code == "BAD_REQUEST"
    assert exc.value.http_status == 400


async def test__create__valid_name__returns_persisted_device_dict(uow, settings, session_maker):
    """create() с именем создаёт устройство и возвращает его dict; запись реально в БД."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
    svc = DeviceService(uow, settings)

    # Act
    created = await svc.create(user.id, "MacBook", "mac")

    # Assert
    assert created["name"] == "MacBook"
    assert created["platform"] == "mac"
    assert created["configs"] == []
    async with session_maker() as check:
        row = await check.get(m.Device, created["id"])
    assert row is not None
    assert row.user_id == user.id


async def test__create__blank_platform__defaults_to_ios(uow, settings, session_maker):
    """create() с пустой платформой → platform по умолчанию 'ios'."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
    svc = DeviceService(uow, settings)

    # Act
    created = await svc.create(user.id, "Планшет", "")

    # Assert
    assert created["platform"] == "ios"


async def test__delete__foreign_device__raises_not_found(uow, settings, session_maker, no_revoke):
    """delete() чужого устройства → NotFound; устройство остаётся, revoke не зовётся."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        other = await make_user(s, phone="+79005556677")
        dev = await make_device(s, user_id=other.id)
    svc = DeviceService(uow, settings)

    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.delete(owner.id, dev.id)
    assert exc.value.http_status == 404
    async with session_maker() as check:
        assert await check.get(m.Device, dev.id) is not None
    assert no_revoke == []


async def test__delete__missing_device__raises_not_found(uow, settings, session_maker, no_revoke):
    """delete() несуществующего устройства → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
    svc = DeviceService(uow, settings)

    # Act / Assert
    with pytest.raises(NotFound):
        await svc.delete(owner.id, "no-such-device-id")
    assert no_revoke == []


async def test__delete__own_device__removes_device_and_cascades_configs(uow, settings, session_maker, no_revoke):
    """delete() своего устройства удаляет Device и каскадом его DeviceConfig."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
        srv = await make_server(s, owner_id=user.id)
        dev = await make_device(s, user_id=user.id)
        cfg = m.DeviceConfig(
            device_id=dev.id,
            server_id=srv.id,
            vpn_type="amnezia",
            proto="AmneziaWG",
            status="active",
            client_id="PUB",
        )
        s.add(cfg)
        await s.flush()
        cfg_id = cfg.id
    svc = DeviceService(uow, settings)

    # Act
    await svc.delete(user.id, dev.id)

    # Assert
    async with session_maker() as check:
        assert await check.get(m.Device, dev.id) is None
        assert await check.get(m.DeviceConfig, cfg_id) is None


async def test__delete__provisioned_config__enqueues_ledger_and_calls_revoke(uow, settings, session_maker, no_revoke):
    """delete() с провижининг-конфигом: пишет client_id в ledger ServerProtocol и зовёт revoke с ref."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
        srv = await make_server(s, owner_id=user.id)
        sid = srv.id
        dev = await make_device(s, user_id=user.id)
        s.add(
            m.DeviceConfig(
                device_id=dev.id,
                server_id=sid,
                vpn_type="amnezia",
                proto="AmneziaWG",  # лейбл; _enqueue_revoke резолвит его в spec.id "awg"
                status="active",
                client_id="PUB",
            )
        )
        # proto="awg" — это spec.id (то, что вернёт spec_by_label("AmneziaWG"))
        s.add(m.ServerProtocol(server_id=sid, vendor="amnezia", proto="awg"))
    assert pc.spec_by_label("AmneziaWG").id == "awg"  # предпосылка мэппинга лейбл→id
    svc = DeviceService(uow, settings)

    # Act
    await svc.delete(user.id, dev.id)

    # Assert
    async with session_maker() as check:
        sp = (
            await check.execute(
                select(m.ServerProtocol).where(m.ServerProtocol.server_id == sid, m.ServerProtocol.proto == "awg")
            )
        ).scalar_one()
        assert "PUB" in parse_pending(sp.pending_revoke_json)
    assert no_revoke == [[(sid, "AmneziaWG", "PUB")]]
