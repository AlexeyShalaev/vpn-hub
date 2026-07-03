"""Интеграционные тесты PoolService (без провижининга)."""

from __future__ import annotations

import pytest

from tests.factories.orm import make_pool, make_server, make_user, seed
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.services.pools import PoolService

pytestmark = pytest.mark.integration


async def test__list__only_owner_pools__excludes_foreign(uow, settings, session_maker):
    """list возвращает только пулы владельца, чужие пулы отфильтрованы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001")
        stranger = await make_user(s, phone="+79001110002")
        await make_pool(s, owner_id=owner.id, name="Мой пул")
        await make_pool(s, owner_id=stranger.id, name="Чужой пул")
    svc = PoolService(uow, settings)
    # Act
    pools = await svc.list(owner.id)
    # Assert
    assert [p["name"] for p in pools] == ["Мой пул"]


async def test__list__pool_with_servers__returns_server_ids(uow, settings, session_maker):
    """list отдаёт форму pool_to_dict (id/name/serverIds) с составом серверов пула."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110010")
        srv_a = await make_server(s, owner_id=owner.id, name="A", ip="203.0.113.1")
        srv_b = await make_server(s, owner_id=owner.id, name="B", ip="203.0.113.2")
        pool = await make_pool(s, owner_id=owner.id, name="Пул с серверами", server_ids=(srv_a.id, srv_b.id))
    svc = PoolService(uow, settings)
    # Act
    pools = await svc.list(owner.id)
    # Assert
    assert len(pools) == 1
    dto = pools[0]
    assert dto["id"] == pool.id
    assert dto["name"] == "Пул с серверами"
    assert sorted(dto["serverIds"]) == sorted([srv_a.id, srv_b.id])


async def test__list__no_pools__returns_empty_list(uow, settings, session_maker):
    """У владельца без пулов list возвращает пустой список."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110020")
    svc = PoolService(uow, settings)
    # Act
    pools = await svc.list(owner.id)
    # Assert
    assert pools == []


@pytest.mark.parametrize("bad_name", ["", None])
async def test__create__empty_name__raises_badrequest(uow, settings, session_maker, bad_name):
    """Пустое/отсутствующее название пула → BadRequest, пул не создаётся."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110030")
    svc = PoolService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.create(owner.id, bad_name, [])
    assert exc.value.http_status == 400
    assert await svc.list(owner.id) == []


async def test__create__with_servers__returns_dict_with_server_ids(uow, settings, session_maker):
    """create с непустым именем и серверами → dict формы pool_to_dict с serverIds."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110040")
        srv_a = await make_server(s, owner_id=owner.id, name="A", ip="203.0.113.11")
        srv_b = await make_server(s, owner_id=owner.id, name="B", ip="203.0.113.12")
    svc = PoolService(uow, settings)
    # Act
    dto = await svc.create(owner.id, "Новый пул", [srv_a.id, srv_b.id])
    # Assert
    assert set(dto.keys()) == {"id", "name", "serverIds"}
    assert dto["name"] == "Новый пул"
    assert dto["serverIds"] == [srv_a.id, srv_b.id]


async def test__create__persists_pool_and_servers(uow, settings, session_maker):
    """Созданный пул реально сохраняется вместе с составом серверов (виден в list)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110050")
        srv = await make_server(s, owner_id=owner.id, name="A", ip="203.0.113.13")
    svc = PoolService(uow, settings)
    # Act
    created = await svc.create(owner.id, "Пул", [srv.id])
    # Assert
    pools = await svc.list(owner.id)
    assert len(pools) == 1
    assert pools[0]["id"] == created["id"]
    assert pools[0]["serverIds"] == [srv.id]


async def test__create__without_servers__has_empty_server_ids(uow, settings, session_maker):
    """create без серверов создаёт пул с пустым составом serverIds."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110060")
    svc = PoolService(uow, settings)
    # Act
    dto = await svc.create(owner.id, "Пустой пул", [])
    # Assert
    assert dto["serverIds"] == []
    assert (await svc.list(owner.id))[0]["serverIds"] == []


async def test__update__foreign_pool__raises_notfound(uow, settings, session_maker):
    """Обновление чужого пула → NotFound, имя не меняется."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110070")
        stranger = await make_user(s, phone="+79001110071")
        pool = await make_pool(s, owner_id=stranger.id, name="Чужой пул")
    svc = PoolService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.update(owner.id, pool.id, "Взлом", [])
    assert exc.value.http_status == 404
    assert (await svc.list(stranger.id))[0]["name"] == "Чужой пул"


async def test__update__missing_pool__raises_notfound(uow, settings, session_maker):
    """Обновление несуществующего пула → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110080")
    svc = PoolService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.update(owner.id, "no-such-id", "Имя", [])


async def test__update__changes_name_and_servers(uow, settings, session_maker):
    """update меняет имя пула и полностью заменяет состав серверов."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110090")
        srv_old = await make_server(s, owner_id=owner.id, name="old", ip="203.0.113.21")
        srv_new = await make_server(s, owner_id=owner.id, name="new", ip="203.0.113.22")
        pool = await make_pool(s, owner_id=owner.id, name="Старое имя", server_ids=(srv_old.id,))
    svc = PoolService(uow, settings)
    # Act
    dto = await svc.update(owner.id, pool.id, "Новое имя", [srv_new.id])
    # Assert
    assert dto["name"] == "Новое имя"
    assert dto["serverIds"] == [srv_new.id]
    persisted = (await svc.list(owner.id))[0]
    assert persisted["name"] == "Новое имя"
    assert persisted["serverIds"] == [srv_new.id]


async def test__update__empty_name__keeps_previous_name(uow, settings, session_maker):
    """Пустое имя при update не затирает старое имя, но состав серверов обновляется."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110100")
        srv = await make_server(s, owner_id=owner.id, name="srv", ip="203.0.113.31")
        pool = await make_pool(s, owner_id=owner.id, name="Исходное имя")
    svc = PoolService(uow, settings)
    # Act
    dto = await svc.update(owner.id, pool.id, "", [srv.id])
    # Assert
    assert dto["name"] == "Исходное имя"
    assert dto["serverIds"] == [srv.id]


async def test__delete__foreign_pool__raises_notfound(uow, settings, session_maker):
    """Удаление чужого пула → NotFound, пул остаётся у владельца."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110110")
        stranger = await make_user(s, phone="+79001110111")
        pool = await make_pool(s, owner_id=stranger.id, name="Чужой пул")
    svc = PoolService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.delete(owner.id, pool.id)
    assert exc.value.http_status == 404
    assert len(await svc.list(stranger.id)) == 1


async def test__delete__own_pool__removes_it(uow, settings, session_maker):
    """Удаление собственного пула убирает его из выборки владельца."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110120")
        pool = await make_pool(s, owner_id=owner.id, name="На удаление")
    svc = PoolService(uow, settings)
    # Act
    result = await svc.delete(owner.id, pool.id)
    # Assert
    assert result is None
    assert await svc.list(owner.id) == []
