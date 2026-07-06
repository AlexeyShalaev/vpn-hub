"""Member-facing «мой трафик за период» (MeService.usage): used/limit/suspended по серверам."""

from __future__ import annotations

import time

import pytest

from tests.factories.orm import (
    grant_group_server,
    make_device,
    make_device_config,
    make_group,
    make_server,
    make_user,
    seed,
)
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.services.limits import period_start
from vpnhub.services.me import MeService

pytestmark = pytest.mark.integration

_GB = 1024**3


async def test__me_usage__used_limit_suspended(session_maker, uow, settings) -> None:
    ps = period_start(time.time(), None)
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79007770001")
        user = await make_user(s, phone="+79007770002")
        srv = await make_server(s, owner_id=owner.id, name="srv-usage", installed_vpns=("amnezia",))
        g = await make_group(s, owner_id=owner.id, token="grp-usage")
        g.max_bytes = 5 * _GB
        s.add(m.GroupMember(group_id=g.id, user_id=user.id, display_name="u", status="active"))
        await grant_group_server(s, group_id=g.id, server_id=srv.id, vpn_type="amnezia")
        dev = await make_device(s, user_id=user.id)
        await make_device_config(
            s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia",
            proto=pc.spec_by_id("awg").label, status="suspended", client_id="pk1",
        )  # fmt: skip
        s.add(m.TrafficUsage(server_id=srv.id, user_id=user.id, period_start=ps, rx_bytes=3 * _GB, tx_bytes=1 * _GB))
        await s.flush()
        srv_id, uid = srv.id, user.id

    rows = await MeService(uow, settings).usage(uid)
    assert len(rows) == 1
    r = rows[0]
    assert r["serverId"] == srv_id
    assert r["used"] == 4 * _GB  # rx+tx
    assert r["limit"] == 5 * _GB
    assert r["suspended"] is True


async def test__me_usage__no_limit_no_traffic__empty(session_maker, uow, settings) -> None:
    # доступ есть, но лимита нет и трафика нет → сервер не засоряет список
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79007770003")
        user = await make_user(s, phone="+79007770004")
        srv = await make_server(s, owner_id=owner.id, name="srv-empty", installed_vpns=("amnezia",))
        g = await make_group(s, owner_id=owner.id, token="grp-empty")
        s.add(m.GroupMember(group_id=g.id, user_id=user.id, display_name="u", status="active"))
        await grant_group_server(s, group_id=g.id, server_id=srv.id, vpn_type="amnezia")
        uid = user.id

    assert await MeService(uow, settings).usage(uid) == []
