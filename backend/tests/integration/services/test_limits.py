"""Тесты лимитов: Этап 1 (конфиги на протоколе) + Этап 2 (устройства на пользователя)."""

from __future__ import annotations

import pytest

from tests.factories.orm import (
    make_device,
    make_device_config,
    make_group,
    make_server,
    make_server_protocol,
    make_user,
    seed,
)
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.services.limits import (
    DEFAULT_DEVICES_PER_USER,
    SETTING_DEFAULT_DEVICES,
    effective_device_limit,
    global_device_limit,
    over_limit,
    used_clients,
    used_devices,
)

pytestmark = pytest.mark.integration


def test__over_limit__cases() -> None:
    assert over_limit(0, None) is False  # без лимита
    assert over_limit(100, None) is False
    assert over_limit(4, 5) is False  # ниже лимита
    assert over_limit(5, 5) is True  # достигнут
    assert over_limit(7, 5) is True  # превышен


async def test__used_clients__active_configs_plus_external(session_maker, uow) -> None:
    """used = активные конфиги (client_id, по label) + external; revoked/пустые/чужой прото не считаются."""
    awg_label = pc.spec_by_id("awg").label
    xray_label = pc.spec_by_id("xray").label
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220001")
        srv = await make_server(s, owner_id=owner.id, name="srv")
        sp = await make_server_protocol(s, server_id=srv.id, proto="awg", installed=True, external_clients=2)
        dev = await make_device(s, user_id=owner.id)
        base = {"device_id": dev.id, "server_id": srv.id, "vpn_type": "amnezia"}
        await make_device_config(s, **base, proto=awg_label, status="active", client_id="pk1")  # +1
        await make_device_config(s, **base, proto=awg_label, status="active", client_id="pk2")  # +1
        await make_device_config(s, **base, proto=awg_label, status="revoked", client_id="pk3")  # revoked → 0
        await make_device_config(s, **base, proto=awg_label, status="active", client_id=None)  # без материала → 0
        await make_device_config(s, **base, proto=xray_label, status="active", client_id="u1")  # другой прото → 0

    async with uow.query() as tx:
        used = await used_clients(tx.session, sp)
    assert used == 4  # 2 активных awg-конфига + 2 внешних


async def test__used_clients__no_configs__only_external(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220002")
        srv = await make_server(s, owner_id=owner.id, name="srv2")
        sp = await make_server_protocol(s, server_id=srv.id, proto="awg", external_clients=3)
    async with uow.query() as tx:
        used = await used_clients(tx.session, sp)
    assert used == 3


# ---- Этап 2: лимит устройств на пользователя ----


async def _member(s, group_id: str, user_id: str, *, max_devices=None, status="active") -> None:
    s.add(m.GroupMember(group_id=group_id, user_id=user_id, display_name="m", status=status, max_devices=max_devices))
    await s.flush()


async def test__global_device_limit__default_and_setting(session_maker, uow) -> None:
    async with uow.query() as tx:
        assert await global_device_limit(tx.session) == DEFAULT_DEVICES_PER_USER  # без настройки — дефолт
    async with seed(session_maker) as s:
        s.add(m.Setting(key=SETTING_DEFAULT_DEVICES, value="8"))
        await s.flush()
    async with uow.query() as tx:
        assert await global_device_limit(tx.session) == 8
    async with seed(session_maker) as s:
        (await s.get(m.Setting, SETTING_DEFAULT_DEVICES)).value = "мусор"
        await s.flush()
    async with uow.query() as tx:
        assert await global_device_limit(tx.session) == DEFAULT_DEVICES_PER_USER  # некорректное → дефолт


async def test__effective_device_limit__no_membership__global(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        u = await make_user(s, phone="+79003330001")
    async with uow.query() as tx:
        assert await effective_device_limit(tx.session, u.id) == DEFAULT_DEVICES_PER_USER


async def test__effective_device_limit__group_override(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330002")
        u = await make_user(s, phone="+79003330003")
        g = await make_group(s, owner_id=owner.id, token="grp-lim-1")
        g.max_devices = 3
        await _member(s, g.id, u.id)  # без персонального override → берётся лимит группы
    async with uow.query() as tx:
        assert await effective_device_limit(tx.session, u.id) == 3


async def test__effective_device_limit__member_override_wins(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330004")
        u = await make_user(s, phone="+79003330005")
        g = await make_group(s, owner_id=owner.id, token="grp-lim-2")
        g.max_devices = 3
        await _member(s, g.id, u.id, max_devices=7)  # персональный override перебивает группу
    async with uow.query() as tx:
        assert await effective_device_limit(tx.session, u.id) == 7


async def test__effective_device_limit__max_across_groups(session_maker, uow) -> None:
    """В нескольких группах берётся самый щедрый применимый лимит (доступ аддитивный)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330006")
        u = await make_user(s, phone="+79003330007")
        g1 = await make_group(s, owner_id=owner.id, name="A", token="grp-lim-3")
        g1.max_devices = 2
        g2 = await make_group(s, owner_id=owner.id, name="B", token="grp-lim-4")
        g2.max_devices = 10
        await _member(s, g1.id, u.id)
        await _member(s, g2.id, u.id)
    async with uow.query() as tx:
        assert await effective_device_limit(tx.session, u.id) == 10


async def test__effective_device_limit__inactive_membership_ignored(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330008")
        u = await make_user(s, phone="+79003330009")
        g = await make_group(s, owner_id=owner.id, token="grp-lim-5")
        g.max_devices = 99
        await _member(s, g.id, u.id, status="invited")  # ещё не активен → не учитывается
    async with uow.query() as tx:
        assert await effective_device_limit(tx.session, u.id) == DEFAULT_DEVICES_PER_USER


async def test__used_devices__counts_user_devices(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        u = await make_user(s, phone="+79003330010")
        other = await make_user(s, phone="+79003330011")
        await make_device(s, user_id=u.id, name="d1")
        await make_device(s, user_id=u.id, name="d2")
        await make_device(s, user_id=other.id, name="x")  # чужое устройство не считается
    async with uow.query() as tx:
        assert await used_devices(tx.session, u.id) == 2
