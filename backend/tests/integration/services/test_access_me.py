"""Интеграционные тесты расчёта эффективного доступа и «Доступно мне».

Покрываются:
- `effective_access(tx, user_id)` — объединение доступа из пулов и точечных грантов,
  фильтрация по installed VPN, отсечение пустых серверов, отсутствие групп;
- `MeService.available(user_id)` — форма и сортировка выдачи, порядок vpns, пропуск
  сервера из access, которого нет в БД.
"""

from __future__ import annotations

import pytest

from tests.factories.orm import (
    add_member,
    grant_group_pool,
    grant_group_server,
    make_group,
    make_pool,
    make_server,
    make_user,
    seed,
)
from vpnhub.services.access import effective_access
from vpnhub.services.me import MeService

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- #
# effective_access                                                            #
# --------------------------------------------------------------------------- #


async def test__effective_access__server_in_group_pool__grants_all_installed_vpns(uow, session_maker):
    """Сервер в пуле группы → участнику доступны ВСЕ installed VPN этого сервера."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        server = await make_server(s, owner_id=user.id, installed_vpns=("amnezia", "openvpn"))
        pool = await make_pool(s, owner_id=user.id, server_ids=(server.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        uid, sid, gname = user.id, server.id, group.name

    # Act
    async with uow.query() as tx:
        access, from_group = await effective_access(tx, uid)

    # Assert
    assert access == {sid: {"amnezia", "openvpn"}}
    assert from_group[sid] == gname


async def test__effective_access__pointwise_grant__intersects_with_installed(uow, session_maker):
    """Точечный грант на 2 типа при 1 installed → доступ = пересечение (только installed)."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        # installed только amnezia, а гранты — на amnezia и openvpn
        server = await make_server(s, owner_id=user.id, installed_vpns=("amnezia",))
        await grant_group_server(s, group_id=group.id, server_id=server.id, vpn_type="amnezia")
        await grant_group_server(s, group_id=group.id, server_id=server.id, vpn_type="openvpn")
        uid, sid = user.id, server.id

    # Act
    async with uow.query() as tx:
        access, _ = await effective_access(tx, uid)

    # Assert
    assert access == {sid: {"amnezia"}}


async def test__effective_access__server_without_installed_vpns__excluded(uow, session_maker):
    """Сервер без installed VPN даёт пустое множество → отсекается из результата."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        server = await make_server(s, owner_id=user.id, installed_vpns=())
        pool = await make_pool(s, owner_id=user.id, server_ids=(server.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        uid = user.id

    # Act
    async with uow.query() as tx:
        access, _ = await effective_access(tx, uid)

    # Assert
    assert access == {}


async def test__effective_access__pointwise_grant_of_uninstalled_type__excluded(uow, session_maker):
    """Точечный грант только на НЕ installed тип → пустое пересечение → сервер отсекается."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        server = await make_server(s, owner_id=user.id, installed_vpns=("amnezia",))
        await grant_group_server(s, group_id=group.id, server_id=server.id, vpn_type="openvpn")
        uid = user.id

    # Act
    async with uow.query() as tx:
        access, _ = await effective_access(tx, uid)

    # Assert
    assert access == {}


async def test__effective_access__user_without_groups__returns_empty(uow, session_maker):
    """Пользователь не состоит ни в одной активной группе → доступа нет."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        # сервер существует, но нет ни групп, ни членства
        await make_server(s, owner_id=user.id, installed_vpns=("amnezia",))
        uid = user.id

    # Act
    async with uow.query() as tx:
        access, from_group = await effective_access(tx, uid)

    # Assert
    assert access == {}
    assert from_group == {}


async def test__effective_access__pool_union_with_pointwise__merges_vpn_types(uow, session_maker):
    """Один сервер и в пуле, и с точечным грантом → типы VPN объединяются (union)."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        server = await make_server(s, owner_id=user.id, installed_vpns=("amnezia", "openvpn", "outline"))
        # пул сервера даёт все installed
        pool = await make_pool(s, owner_id=user.id, server_ids=(server.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        # точечный грант дублирует один из типов — union не должен ничего потерять
        await grant_group_server(s, group_id=group.id, server_id=server.id, vpn_type="amnezia")
        uid, sid = user.id, server.id

    # Act
    async with uow.query() as tx:
        access, _ = await effective_access(tx, uid)

    # Assert
    assert access == {sid: {"amnezia", "openvpn", "outline"}}


# --------------------------------------------------------------------------- #
# MeService.available                                                         #
# --------------------------------------------------------------------------- #


async def test__me_available__pool_access__returns_server_with_expected_fields(uow, settings, session_maker):
    """Сервер из пула → в выдаче есть id/name/fromGroup и его installed vpns."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id, name="Семья")
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        server = await make_server(s, owner_id=user.id, name="srv-a", installed_vpns=("amnezia", "openvpn"))
        pool = await make_pool(s, owner_id=user.id, server_ids=(server.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        uid, sid = user.id, server.id
    svc = MeService(uow, settings)

    # Act
    out = await svc.available(uid)

    # Assert
    assert len(out) == 1
    item = out[0]
    assert item["id"] == sid
    assert item["name"] == "srv-a"
    assert item["fromGroup"] == "Семья"
    assert item["vpns"] == ["amnezia", "openvpn"]


async def test__me_available__multiple_vpns__sorted_amnezia_openvpn_outline(uow, settings, session_maker):
    """vpns в выдаче отсортированы в порядке amnezia, openvpn, outline независимо от порядка installed."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        # порядок installed намеренно перемешан
        server = await make_server(s, owner_id=user.id, installed_vpns=("outline", "amnezia", "openvpn"))
        pool = await make_pool(s, owner_id=user.id, server_ids=(server.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        uid = user.id
    svc = MeService(uow, settings)

    # Act
    out = await svc.available(uid)

    # Assert
    assert out[0]["vpns"] == ["amnezia", "openvpn", "outline"]


async def test__me_available__several_servers__sorted_by_name(uow, settings, session_maker):
    """Несколько доступных серверов → выдача отсортирована по name по возрастанию."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        srv_b = await make_server(s, owner_id=user.id, name="Bravo", ip="203.0.113.11", installed_vpns=("amnezia",))
        srv_a = await make_server(s, owner_id=user.id, name="Alpha", ip="203.0.113.12", installed_vpns=("amnezia",))
        pool = await make_pool(s, owner_id=user.id, server_ids=(srv_b.id, srv_a.id))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        uid = user.id
    svc = MeService(uow, settings)

    # Act
    out = await svc.available(uid)

    # Assert
    assert [x["name"] for x in out] == ["Alpha", "Bravo"]


async def test__me_available__pointwise_grant_to_missing_server__excluded(uow, settings, session_maker):
    """Точечный грант на несуществующий server_id не появляется в выдаче «доступно мне».

    Такой сервер даёт пустое пересечение с installed и отсекается ещё в effective_access,
    поэтому в списке остаётся только реально существующий доступный сервер.
    """
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        group = await make_group(s, owner_id=user.id)
        await add_member(s, group_id=group.id, user_id=user.id, status="active")
        # реальный доступный сервер
        real = await make_server(s, owner_id=user.id, name="real", installed_vpns=("amnezia",))
        pool = await make_pool(s, owner_id=user.id, server_ids=(real.id,))
        await grant_group_pool(s, group_id=group.id, pool_id=pool.id)
        # грант на несуществующий сервер
        await grant_group_server(s, group_id=group.id, server_id="ghost-server-id", vpn_type="amnezia")
        uid, real_id = user.id, real.id
    svc = MeService(uow, settings)

    # Act
    out = await svc.available(uid)

    # Assert
    assert [x["id"] for x in out] == [real_id]


async def test__me_available__no_access__returns_empty_list(uow, settings, session_maker):
    """Пользователь без активных групп → пустой список доступных серверов."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
        await make_server(s, owner_id=user.id, installed_vpns=("amnezia",))
        uid = user.id
    svc = MeService(uow, settings)

    # Act
    out = await svc.available(uid)

    # Assert
    assert out == []
