"""Интеграционные тесты AuditService: запись, ролевая видимость, фильтры, ретеншн.

Плюс проверка инструментирования: login/join/revoke порождают событие с ожидаемым type/target.
Всё на in-memory SQLite — SSH/провижининг не задействованы.
"""

from __future__ import annotations

import time

import pytest

from tests.factories.orm import (
    make_device,
    make_device_config,
    make_group,
    make_server,
    make_user,
    seed,
)
from vpnhub.services import audit_types
from vpnhub.services.audit import AuditService
from vpnhub.services.auth import AuthService, Identity
from vpnhub.services.groups import GroupService
from vpnhub.services.server_access import ServerAccessService

pytestmark = pytest.mark.integration

PASSWORD = "Passw0rd!"


def _admin_ident(uid: str) -> Identity:
    return Identity("admin", uid, "Админ", "+79990000000", "owner")


def _owner_ident(uid: str) -> Identity:
    return Identity("user", uid, "Владелец", "+79990000001", "owner")


# ---- record_tx / чтение ----------------------------------------------------


async def test__record_tx__writes_row_with_actor_and_type(uow, settings, session_maker):
    """record_tx пишет строку; поля актора/типа/owner корректны."""
    # Arrange
    async with seed(session_maker) as s:
        actor = await make_user(s, name="Пётр")
    ident = _owner_ident(actor.id)
    # Act
    async with uow.transaction() as tx:
        AuditService.record_tx(
            tx,
            actor=ident,
            type=audit_types.CONFIG_DOWNLOAD,
            target_kind="server",
            target_id="srv1",
            owner_user_id=actor.id,
            meta={"vpn": "amnezia"},
        )
    # Assert
    svc = AuditService(uow, settings)
    events = await svc.list_for(ident)
    assert len(events) == 1
    ev = events[0]
    assert ev["type"] == audit_types.CONFIG_DOWNLOAD
    assert ev["actorId"] == actor.id
    assert ev["actorName"] == "Владелец"
    assert ev["targetId"] == "srv1"
    assert ev["meta"] == {"vpn": "amnezia"}
    assert ev["label"] == "Выдача конфига"


async def test__record_tx__no_actor__writes_system_kind(uow, settings, session_maker):
    """Без актора событие пишется как system."""
    # Act
    async with uow.transaction() as tx:
        AuditService.record_tx(tx, actor=None, type=audit_types.CONFIG_DOWNLOAD)
    # Assert
    async with uow.query() as tx:
        rows = await tx.audit.list()
    assert len(rows) == 1
    assert rows[0].actor_kind == "system"
    assert rows[0].actor_id is None


async def test__list_for__admin_sees_all_owner_only_own(uow, settings, session_maker):
    """admin видит все события; owner — только со своим owner_user_id (или своими действиями)."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79990000000", name="Админ", admin=True)
        owner = await make_user(s, phone="+79990000001", name="Владелец")
    async with uow.transaction() as tx:
        # событие ресурса owner
        AuditService.record_tx(
            tx,
            actor=None,
            type=audit_types.ACCESS_REVOKE,
            target_kind="server",
            target_id="s1",
            owner_user_id=owner.id,
        )
        # чужое событие (другой владелец)
        AuditService.record_tx(
            tx,
            actor=None,
            type=audit_types.ACCESS_REVOKE,
            target_kind="server",
            target_id="s2",
            owner_user_id="other-owner",
        )
    svc = AuditService(uow, settings)
    # Act
    admin_events = await svc.list_for(_admin_ident(admin.id))
    owner_events = await svc.list_for(_owner_ident(owner.id))
    # Assert
    assert len(admin_events) == 2
    assert len(owner_events) == 1
    assert owner_events[0]["targetId"] == "s1"


async def test__list_for__owner_sees_own_login_without_owner_id(uow, settings, session_maker):
    """login-события owner (actor_id==owner, owner_user_id пуст) видны owner-у по actor_id."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, name="Владелец")
    async with uow.transaction() as tx:
        tx.audit.add_event(
            at=time.time(),
            actor_kind="user",
            actor_id=owner.id,
            actor_name="Владелец",
            type_=audit_types.AUTH_LOGIN,
        )
    svc = AuditService(uow, settings)
    # Act
    events = await svc.list_for(_owner_ident(owner.id))
    # Assert
    assert len(events) == 1
    assert events[0]["type"] == audit_types.AUTH_LOGIN


async def test__list_for__type_and_period_filters(uow, settings, session_maker):
    """Фильтр по type и диапазону since/until работает."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, admin=True)
    now = time.time()
    async with uow.transaction() as tx:
        tx.audit.add_event(
            at=now - 1000, actor_kind="system", actor_id=None, actor_name="", type_=audit_types.AUTH_LOGIN
        )
        tx.audit.add_event(at=now, actor_kind="system", actor_id=None, actor_name="", type_=audit_types.GROUP_JOIN)
    svc = AuditService(uow, settings)
    # Act
    by_type = await svc.list_for(_admin_ident(admin.id), type=audit_types.GROUP_JOIN)
    by_period = await svc.list_for(_admin_ident(admin.id), since=now - 10)
    # Assert
    assert len(by_type) == 1 and by_type[0]["type"] == audit_types.GROUP_JOIN
    assert len(by_period) == 1 and by_period[0]["type"] == audit_types.GROUP_JOIN


async def test__purge_old__removes_old_and_idempotent(uow, settings, session_maker):
    """purge_old удаляет события старше ретеншна и идемпотентен (повтор → 0)."""
    # Arrange
    settings.audit_retention_days = 30
    old = time.time() - 40 * 86400
    fresh = time.time()
    async with uow.transaction() as tx:
        tx.audit.add_event(at=old, actor_kind="system", actor_id=None, actor_name="", type_=audit_types.AUTH_LOGIN)
        tx.audit.add_event(at=fresh, actor_kind="system", actor_id=None, actor_name="", type_=audit_types.AUTH_LOGIN)
    svc = AuditService(uow, settings)
    # Act
    removed = await svc.purge_old()
    removed_again = await svc.purge_old()
    # Assert
    assert removed == 1
    assert removed_again == 0
    async with uow.query() as tx:
        rows = await tx.audit.list()
    assert len(rows) == 1


# ---- инструментирование действий -------------------------------------------


async def test__auth_login__records_login_event(uow, settings, session_maker):
    """AuthService.login пишет событие auth.login с актором-пользователем."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233", password=PASSWORD, name="Иван")
    svc = AuthService(uow, settings)
    # Act
    await svc.login("+79001112233", PASSWORD, ip="1.2.3.4")
    # Assert
    async with uow.query() as tx:
        rows = await tx.audit.list(type_=audit_types.AUTH_LOGIN)
    assert len(rows) == 1
    assert rows[0].actor_id == user.id


async def test__group_join__records_join_event(uow, settings, session_maker):
    """GroupService.join пишет событие group.join с target=group и owner_user_id владельца группы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79990000001", name="Владелец")
        member = await make_user(s, phone="+79001112233", name="Гость")
        group = await make_group(s, owner_id=owner.id, token="tok-join")
    svc = GroupService(uow, settings)
    # Act
    await svc.join(member.id, "Гость", "tok-join")
    # Assert
    async with uow.query() as tx:
        rows = await tx.audit.list(type_=audit_types.GROUP_JOIN)
    assert len(rows) == 1
    assert rows[0].target_id == group.id
    assert rows[0].owner_user_id == owner.id
    assert rows[0].actor_id == member.id


async def test__revoke_client__records_revoke_event(uow, settings, session_maker):
    """ServerAccessService.revoke_client пишет событие access.revoke (актор — владелец)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79990000001", name="Владелец")
        server = await make_server(s, owner_id=owner.id, name="srv")
        member = await make_user(s, phone="+79001112233", name="Гость")
        device = await make_device(s, user_id=member.id)
        cfg = await make_device_config(
            s,
            device_id=device.id,
            server_id=server.id,
            vpn_type="amnezia",
            proto="awg",
        )
    svc = ServerAccessService(uow, settings)
    # Act
    await svc.revoke_client(owner.id, server.id, cfg.id)
    # Assert
    async with uow.query() as tx:
        rows = await tx.audit.list(type_=audit_types.ACCESS_REVOKE)
    assert len(rows) == 1
    assert rows[0].target_id == server.id
    assert rows[0].owner_user_id == owner.id
    assert rows[0].actor_id == owner.id
