"""Тесты лимитов: Этап 1 (конфиги на протоколе) + Этап 2 (устройства на пользователя)."""

from __future__ import annotations

import time

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
    SETTING_DEFAULT_USER_BYTES,
    add_period_usage,
    effective_byte_limit,
    effective_device_limit,
    fmt_bytes,
    global_device_limit,
    over_limit,
    period_start,
    period_usage,
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


async def _member(s, group_id: str, user_id: str, *, max_devices=None, max_bytes=None, status="active") -> None:
    s.add(
        m.GroupMember(
            group_id=group_id,
            user_id=user_id,
            display_name="m",
            status=status,
            max_devices=max_devices,
            max_bytes=max_bytes,
        )
    )
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


# ---- Этап 3: байт-лимиты, период биллинга, накопитель ----


def test__fmt_bytes() -> None:
    assert fmt_bytes(0) == "0 Б"
    assert fmt_bytes(512) == "512 Б"
    assert fmt_bytes(1536) == "1.5 КБ"
    assert fmt_bytes(5 * 1024**3) == "5.0 ГБ"
    assert fmt_bytes(3 * 1024**4) == "3.0 ТБ"


def test__period_start__billing_day_anchor() -> None:
    """Период начинается в billing_day текущего месяца, если день уже наступил, иначе — в прошлом."""
    now = time.mktime((2026, 3, 15, 12, 0, 0, 0, 0, -1))  # 15 марта
    # день сброса 10 ≤ 15 → период с 10 марта
    assert period_start(now, 10) == time.mktime((2026, 3, 10, 0, 0, 0, 0, 0, -1))
    # день сброса 20 > 15 → период с 20 февраля
    assert period_start(now, 20) == time.mktime((2026, 2, 20, 0, 0, 0, 0, 0, -1))
    # None → 1-е число
    assert period_start(now, None) == time.mktime((2026, 3, 1, 0, 0, 0, 0, 0, -1))


def test__period_start__clamps_day_to_month_length() -> None:
    """День 31 клампится к длине месяца (февраль → 28/29)."""
    now = time.mktime((2026, 2, 15, 12, 0, 0, 0, 0, -1))  # 15 фев 2026 (28 дней)
    # день 31 в феврале → якорь 28; 15 < 28 → период с 31 января
    assert period_start(now, 31) == time.mktime((2026, 1, 31, 0, 0, 0, 0, 0, -1))


async def test__global_user_bytes__default_unlimited_and_setting(session_maker, uow) -> None:
    from vpnhub.services.limits import global_user_bytes

    async with uow.query() as tx:
        assert await global_user_bytes(tx.session) is None  # по умолчанию без лимита
    async with seed(session_maker) as s:
        s.add(m.Setting(key=SETTING_DEFAULT_USER_BYTES, value=str(10 * 1024**3)))
        await s.flush()
    async with uow.query() as tx:
        assert await global_user_bytes(tx.session) == 10 * 1024**3
    async with seed(session_maker) as s:
        (await s.get(m.Setting, SETTING_DEFAULT_USER_BYTES)).value = "0"  # 0 = без лимита
        await s.flush()
    async with uow.query() as tx:
        assert await global_user_bytes(tx.session) is None


async def test__effective_byte_limit__hierarchy(session_maker, uow) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440001")
        no_grp = await make_user(s, phone="+79004440002")
        grp_only = await make_user(s, phone="+79004440003")
        member_over = await make_user(s, phone="+79004440004")
        multi = await make_user(s, phone="+79004440005")
        g1 = await make_group(s, owner_id=owner.id, name="G1", token="grp-b-1")
        g1.max_bytes = 5 * 1024**3
        g2 = await make_group(s, owner_id=owner.id, name="G2", token="grp-b-2")  # без байт-лимита
        await _member(s, g1.id, grp_only.id)  # наследует лимит группы
        await _member(s, g1.id, member_over.id, max_bytes=20 * 1024**3)  # персональный перебивает
        await _member(s, g1.id, multi.id)  # G1: 5 ГБ
        await _member(s, g2.id, multi.id)  # G2: без лимита (None) → игнорируется, не обнуляет
    async with uow.query() as tx:
        assert await effective_byte_limit(tx.session, no_grp.id) is None  # без групп → глобал (None)
        assert await effective_byte_limit(tx.session, grp_only.id) == 5 * 1024**3
        assert await effective_byte_limit(tx.session, member_over.id) == 20 * 1024**3
        assert await effective_byte_limit(tx.session, multi.id) == 5 * 1024**3  # явный 5ГБ, None не void


async def test__period_usage__accumulates_server_total_and_per_user(session_maker, uow) -> None:
    """add_period_usage: None-ключ = суммарно по серверу, user_id = пер-user; инкремент складывается."""
    async with seed(session_maker) as s:
        u = await make_user(s, phone="+79004440010")
        srv = await make_server(s, owner_id=u.id, name="srv-b")
    ps = 1_700_000_000.0
    async with uow.transaction() as tx:
        await add_period_usage(tx.session, srv.id, ps, {None: (100, 200), u.id: (30, 70)}, now=ps)
    async with uow.transaction() as tx:
        await add_period_usage(tx.session, srv.id, ps, {None: (10, 20), u.id: (1, 2)}, now=ps)
    async with uow.query() as tx:
        assert await period_usage(tx.session, srv.id, None, ps) == (110, 220)  # сервер суммарно
        assert await period_usage(tx.session, srv.id, u.id, ps) == (31, 72)  # пер-user
        assert await period_usage(tx.session, srv.id, u.id, ps + 1) == (0, 0)  # другой период — пусто
