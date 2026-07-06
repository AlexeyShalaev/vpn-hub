"""Тесты Этапа 1 лимитов: занятость протокола (used_clients) + предикат over_limit."""

from __future__ import annotations

import pytest

from tests.factories.orm import make_device, make_device_config, make_server, make_server_protocol, make_user, seed
from vpnhub.infra.provisioning import constants as pc
from vpnhub.services.limits import over_limit, used_clients

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
