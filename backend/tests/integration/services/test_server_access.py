"""Интеграционные тесты ServerAccessService (без SSH/провижининга).

Покрываем чистые (in-БД) методы: overview, vpn_advanced, rename_client, а также
guard'ы у SSH-методов (external_clients/revoke_client), которые падают на проверке
владельца/наличия конфига РАНЬШЕ любого SSH — для этого хватает чужого owner_id.
"""

from __future__ import annotations

import json

import pytest

from tests.factories.orm import (
    add_member,
    grant_group_server,
    make_device,
    make_group,
    make_pool,
    make_server,
    make_user,
    seed,
)
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import encrypt_secret
from vpnhub.services.server_access import ServerAccessService

pytestmark = pytest.mark.integration


@pytest.fixture
def svc(uow, settings) -> ServerAccessService:
    """Сервис-под-тестом с общими uow/settings."""
    return ServerAccessService(uow, settings)


# --------------------------------------------------------------------------- overview


async def test__overview__foreign_server__raises_notfound(svc, session_maker):
    """overview чужого сервера → NotFound (owner_id не совпадает с владельцем)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001")
        stranger = await make_user(s, phone="+79001110002")
        srv = await make_server(s, owner_id=stranger.id, name="Чужой")
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.overview(owner.id, srv.id)
    assert exc.value.http_status == 404


async def test__overview__server_in_pool__lists_pool(svc, session_maker):
    """overview показывает пулы, в состав которых входит сервер."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110010")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        pool = await make_pool(s, owner_id=owner.id, name="Мой пул", server_ids=(srv.id,))
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result["pools"] == [{"id": pool.id, "name": "Мой пул"}]


async def test__overview__group_with_direct_access__reports_group_and_vpns(svc, session_maker):
    """overview показывает группу с прямым доступом, источник 'напрямую' и список vpn."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110020")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        group = await make_group(s, owner_id=owner.id, name="Семья", token="grp-direct")
        await grant_group_server(s, group_id=group.id, server_id=srv.id, vpn_type="amnezia")
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result["groups"] == [{"id": group.id, "name": "Семья", "via": "напрямую", "vpns": ["amnezia"]}]


async def test__overview__group_access_via_pool__reports_pool_source(svc, session_maker):
    """overview показывает группу, получившую доступ через пул: via='пул <имя>'."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110025")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        pool = await make_pool(s, owner_id=owner.id, name="Домашний", server_ids=(srv.id,))
        group = await make_group(s, owner_id=owner.id, name="Друзья", token="grp-pool")
        s.add(m.GroupPoolAccess(group_id=group.id, pool_id=pool.id))
        await s.flush()
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert len(result["groups"]) == 1
    assert result["groups"][0]["via"] == "пул Домашний"
    assert result["groups"][0]["vpns"] == []  # доступ через пул, не напрямую → vpns пуст


async def test__overview__group_without_access__excluded(svc, session_maker):
    """Группа без доступа к серверу (ни через пул, ни напрямую) в overview не попадает."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110030")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        other = await make_server(s, owner_id=owner.id, name="other", ip="203.0.113.99")
        group = await make_group(s, owner_id=owner.id, name="Без доступа", token="grp-none")
        # доступ выдан к ДРУГОМУ серверу
        await grant_group_server(s, group_id=group.id, server_id=other.id, vpn_type="amnezia")
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result["groups"] == []


async def test__overview__active_member_with_access__listed_as_user(svc, session_maker):
    """Активный участник группы с доступом попадает в users с hasAccess=True и именем группы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110040")
        member = await make_user(s, phone="+79001110041", name="Пётр")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        group = await make_group(s, owner_id=owner.id, name="Семья", token="grp-mem")
        await grant_group_server(s, group_id=group.id, server_id=srv.id, vpn_type="amnezia")
        await add_member(s, group_id=group.id, user_id=member.id, display_name="Пётр", status="active")
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert len(result["users"]) == 1
    u = result["users"][0]
    assert u["userId"] == member.id
    assert u["name"] == "Пётр"
    assert u["hasAccess"] is True
    assert u["groups"] == ["Семья"]
    assert u["configs"] == []


async def test__overview__inactive_member__not_listed(svc, session_maker):
    """Неактивный (invited) участник группы с доступом НЕ попадает в users."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110050")
        member = await make_user(s, phone="+79001110051", name="Гость")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        group = await make_group(s, owner_id=owner.id, name="Семья", token="grp-inv")
        await grant_group_server(s, group_id=group.id, server_id=srv.id, vpn_type="amnezia")
        await add_member(s, group_id=group.id, user_id=member.id, display_name="Гость", status="invited")
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result["users"] == []


async def test__overview__user_with_config__reports_config_details(svc, session_maker):
    """overview отдаёт выданные конфиги пользователя на сервере с деталями устройства/протокола."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110060")
        member = await make_user(s, phone="+79001110061", name="Анна")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        device = await make_device(s, user_id=member.id, name="iPhone Анны", platform="ios")
        s.add(
            m.DeviceConfig(
                device_id=device.id,
                server_id=srv.id,
                vpn_type="amnezia",
                proto="awg",
                status="active",
                client_name="Анна-AWG",
            )
        )
        await s.flush()
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert len(result["users"]) == 1
    u = result["users"][0]
    assert u["userId"] == member.id
    assert u["hasAccess"] is False  # доступа через группу нет, только выданный конфиг
    assert len(u["configs"]) == 1
    cfg = u["configs"][0]
    assert cfg["device"] == "iPhone Анны"
    assert cfg["platform"] == "ios"
    assert cfg["proto"] == "awg"
    assert cfg["vpnType"] == "amnezia"
    assert cfg["clientName"] == "Анна-AWG"
    assert cfg["status"] == "active"


async def test__overview__config_on_other_server__excluded(svc, session_maker):
    """Конфиги, выданные на другом сервере, в overview текущего сервера не попадают."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110070")
        member = await make_user(s, phone="+79001110071", name="Влад")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        other = await make_server(s, owner_id=owner.id, name="other", ip="203.0.113.77")
        device = await make_device(s, user_id=member.id, name="ПК", platform="windows")
        s.add(m.DeviceConfig(device_id=device.id, server_id=other.id, vpn_type="amnezia", proto="awg"))
        await s.flush()
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result["users"] == []


async def test__overview__no_usage__returns_empty_sections(svc, session_maker):
    """Сервер без пулов/групп/конфигов → пустые pools/groups/users."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110080")
        srv = await make_server(s, owner_id=owner.id, name="srv")
    # Act
    result = await svc.overview(owner.id, srv.id)
    # Assert
    assert result == {"pools": [], "groups": [], "users": []}


# --------------------------------------------------------------------------- vpn_advanced


async def test__vpn_advanced__foreign_server__raises_notfound(svc, session_maker):
    """vpn_advanced чужого сервера → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110100")
        stranger = await make_user(s, phone="+79001110101")
        srv = await make_server(s, owner_id=stranger.id, name="Чужой")
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    assert exc.value.http_status == 404


async def test__vpn_advanced__returns_vendor_protocols__with_label(svc, session_maker):
    """vpn_advanced отдаёт протоколы запрошенного вендора с человекочитаемым label из spec."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110110")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        s.add(
            m.ServerProtocol(
                server_id=srv.id,
                vendor="amnezia",
                proto="awg",
                container="amnezia-awg2",
                port="55424",
                state="installed",
                installed=True,
                running=True,
            )
        )
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    assert result["vendor"] == "amnezia"
    assert len(result["protocols"]) == 1
    proto = result["protocols"][0]
    assert proto["proto"] == "awg"
    assert proto["label"] == "AmneziaWG"  # spec_by_id('awg').label
    assert proto["container"] == "amnezia-awg2"
    assert proto["installed"] is True
    assert proto["running"] is True


async def test__vpn_advanced__other_vendor_protocols__filtered_out(svc, session_maker):
    """vpn_advanced отдаёт только протоколы запрошенного вендора, чужие отфильтрованы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110115")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        s.add(m.ServerProtocol(server_id=srv.id, vendor="amnezia", proto="awg", installed=True))
        s.add(m.ServerProtocol(server_id=srv.id, vendor="openvpn", proto="openvpn", installed=True))
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    assert [p["proto"] for p in result["protocols"]] == ["awg"]


async def test__vpn_advanced__encrypted_material__exposes_only_public_keys(svc, settings, session_maker):
    """Приватный материал наружу не отдаётся: в keys только публичные ключи (без private/psk)."""
    # Arrange
    material = {
        "server_public_key": "PUB-SERVER-KEY",
        "xray_public_key": "PUB-XRAY-KEY",
        "server_private_key": "SECRET-PRIVATE",
        "psk": "SECRET-PSK",
    }
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110120")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        s.add(
            m.ServerProtocol(
                server_id=srv.id,
                vendor="amnezia",
                proto="awg",
                installed=True,
                running=True,
                material_encrypted=encrypt_secret(settings.secret_key, json.dumps(material)),
            )
        )
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    keys = result["protocols"][0]["keys"]
    assert keys == {"server_public_key": "PUB-SERVER-KEY", "xray_public_key": "PUB-XRAY-KEY"}
    assert "server_private_key" not in keys
    assert "psk" not in keys


async def test__vpn_advanced__params_json__parsed_into_params(svc, session_maker):
    """params_json протокола разбирается в объект params."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110125")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        s.add(
            m.ServerProtocol(
                server_id=srv.id, vendor="amnezia", proto="awg", params_json=json.dumps({"Jc": 5, "H1": "1"})
            )
        )
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    assert result["protocols"][0]["params"] == {"Jc": 5, "H1": "1"}


async def test__vpn_advanced__client_config__reported_with_public_id(svc, session_maker):
    """vpn_advanced отдаёт клиентов вендора; clientId — публичный ключ (не приватный секрет)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110130")
        member = await make_user(s, phone="+79001110131", name="Мария")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        device = await make_device(s, user_id=member.id, name="Ноут", platform="mac")
        s.add(
            m.DeviceConfig(
                device_id=device.id,
                server_id=srv.id,
                vpn_type="amnezia",
                proto="awg",
                status="active",
                client_name="Мария-AWG",
                client_ip="10.8.0.5",
                client_public_key="CLIENT-PUBKEY",
                client_secret_encrypted="ENCRYPTED-PRIV",
            )
        )
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    assert len(result["clients"]) == 1
    client = result["clients"][0]
    assert client["clientName"] == "Мария-AWG"
    assert client["user"] == "Мария"
    assert client["device"] == "Ноут"
    assert client["proto"] == "awg"
    assert client["clientIp"] == "10.8.0.5"
    assert client["clientId"] == "CLIENT-PUBKEY"
    assert client["status"] == "active"
    # приватный секрет клиента не должен утекать: ни ключом, ни значением ни в одном поле
    assert "client_secret_encrypted" not in client
    assert not any("secret" in k.lower() for k in client)
    assert "ENCRYPTED-PRIV" not in json.dumps(client, ensure_ascii=False)


async def test__vpn_advanced__client_of_other_vendor__filtered_out(svc, session_maker):
    """Клиенты другого вендора на том же сервере не попадают в выборку vpn_advanced."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110135")
        member = await make_user(s, phone="+79001110136", name="Олег")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        device = await make_device(s, user_id=member.id, name="Телефон", platform="android")
        s.add(m.DeviceConfig(device_id=device.id, server_id=srv.id, vpn_type="openvpn", proto="openvpn"))
        await s.flush()
    # Act
    result = await svc.vpn_advanced(owner.id, srv.id, "amnezia")
    # Assert
    assert result["clients"] == []


# --------------------------------------------------------------------------- rename_client


@pytest.fixture
async def rename_ctx(session_maker):
    """Владелец + сервер + устройство + активный конфиг на сервере (для rename/guard-тестов)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110200")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        device = await make_device(s, user_id=owner.id, name="iPhone", platform="ios")
        cfg = m.DeviceConfig(
            device_id=device.id, server_id=srv.id, vpn_type="amnezia", proto="awg", client_name="Старое"
        )
        s.add(cfg)
        await s.flush()
        owner_id, srv_id, cfg_id = owner.id, srv.id, cfg.id
    return {"owner_id": owner_id, "srv_id": srv_id, "cfg_id": cfg_id}


@pytest.mark.parametrize("bad_name", ["", "   ", None])
async def test__rename_client__blank_name__raises_badrequest(svc, rename_ctx, bad_name):
    """Пустое/пробельное/None имя конфига → BadRequest, имя не меняется."""
    # Arrange
    ctx = rename_ctx
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.rename_client(ctx["owner_id"], ctx["srv_id"], ctx["cfg_id"], bad_name)
    assert exc.value.http_status == 400


async def test__rename_client__foreign_server__raises_notfound(svc, rename_ctx, session_maker):
    """rename_client для чужого сервера → NotFound (падает на проверке владельца)."""
    # Arrange
    ctx = rename_ctx
    async with seed(session_maker) as s:
        stranger = await make_user(s, phone="+79001110210")
        stranger_id = stranger.id
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.rename_client(stranger_id, ctx["srv_id"], ctx["cfg_id"], "Новое")
    assert exc.value.http_status == 404


async def test__rename_client__missing_config__raises_notfound(svc, rename_ctx):
    """rename_client несуществующего конфига (свой сервер) → NotFound."""
    # Arrange
    ctx = rename_ctx
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.rename_client(ctx["owner_id"], ctx["srv_id"], "no-such-config", "Новое")
    assert exc.value.http_status == 404


async def test__rename_client__config_on_other_server__raises_notfound(svc, rename_ctx, session_maker):
    """Конфиг существует, но привязан к другому серверу → NotFound (server_id не совпал)."""
    # Arrange
    ctx = rename_ctx
    async with seed(session_maker) as s:
        other = await make_server(s, owner_id=ctx["owner_id"], name="other", ip="203.0.113.55")
        other_id = other.id
    # Act / Assert — сервер свой, но конфиг лежит на srv_id, а мы просим на other_id
    with pytest.raises(NotFound):
        await svc.rename_client(ctx["owner_id"], other_id, ctx["cfg_id"], "Новое")


async def test__rename_client__valid__updates_name_and_returns_ok(svc, rename_ctx, session_maker):
    """Валидное имя → client_name реально меняется в БД, возвращается {'ok': True}."""
    # Arrange
    ctx = rename_ctx
    # Act
    result = await svc.rename_client(ctx["owner_id"], ctx["srv_id"], ctx["cfg_id"], "  Новое имя  ")
    # Assert
    assert result == {"ok": True}
    async with session_maker() as s:
        cfg = await s.get(m.DeviceConfig, ctx["cfg_id"])
        assert cfg.client_name == "Новое имя"  # обрезаются пробелы


# ------------------------------------------------ guard'ы SSH-методов (без доведения до SSH)


async def test__revoke_client__foreign_server__raises_notfound(svc, rename_ctx, session_maker):
    """revoke_client чужого сервера падает на _owned (NotFound) РАНЬШЕ любого SSH."""
    # Arrange
    ctx = rename_ctx
    async with seed(session_maker) as s:
        stranger = await make_user(s, phone="+79001110220")
        stranger_id = stranger.id
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.revoke_client(stranger_id, ctx["srv_id"], ctx["cfg_id"])
    assert exc.value.http_status == 404


async def test__revoke_client__missing_config__raises_notfound(svc, rename_ctx):
    """revoke_client несуществующего конфига (свой сервер) → NotFound до SSH."""
    # Arrange
    ctx = rename_ctx
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.revoke_client(ctx["owner_id"], ctx["srv_id"], "no-such-config")


async def test__external_clients__foreign_server__raises_notfound(svc, rename_ctx, session_maker):
    """external_clients чужого сервера падает на _owned (NotFound) РАНЬШЕ SSH."""
    # Arrange
    ctx = rename_ctx
    async with seed(session_maker) as s:
        stranger = await make_user(s, phone="+79001110230")
        stranger_id = stranger.id
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.external_clients(stranger_id, ctx["srv_id"], "amnezia")
    assert exc.value.http_status == 404
