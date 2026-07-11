"""Интеграционный тест ServerService.set_protocol_params: смена obfuscation-пресета AWG.

SSH-применение подменяется фейком (ProvisioningService.set_protocol_params записывает вызов в память):
проверяем оркестрацию сервиса (владение/online/installed, validate, запись params_json), а не эмуляцию сервера.
"""

from __future__ import annotations

import json
import random

import pytest

from tests.factories.orm import make_server, make_server_protocol, make_user, seed
from vpnhub.core.errors import BadRequest
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.awg_params import AwgParams, generate
from vpnhub.services.servers import ServerService

pytestmark = pytest.mark.integration

AWG = pc.VENDOR_PROTOS[pc.VENDOR_AMNEZIA][0]  # awg (is_awg2=True)


def _params_json(is_awg2: bool) -> str:
    return json.dumps(generate(is_awg2=is_awg2, rng=random.Random(1)).as_dict())


async def _make_awg_server(session, *, owner_id, status="online", installed=True, running=True):
    server = await make_server(session, owner_id=owner_id, ip="203.0.113.201", status=status)
    await make_server_protocol(
        session,
        server_id=server.id,
        proto=AWG,
        state="installed" if installed else "absent",
        installed=installed,
        running=running,
        params_json=_params_json(pc.spec_by_id(AWG).is_awg2),
    )
    return server


async def test__set_protocol_params__aggressive_preset__updates_params_json(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001")
        server = await _make_awg_server(s, owner_id=owner.id)

    applied: dict[str, AwgParams] = {}

    async def _fake_apply(self, srv, sp, new_params):  # сигнатура зеркалит боевую set_protocol_params
        applied["params"] = new_params

    import vpnhub.services.servers as servers_mod

    monkeypatch.setattr(servers_mod.ProvisioningService, "set_protocol_params", _fake_apply)

    svc = ServerService(uow, settings)
    out = await svc.set_protocol_params(owner.id, server.id, AWG, preset="aggressive")

    assert out["id"] == server.id
    assert "params" in applied  # фейковое SSH-применение вызвано
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        sp = next(p for p in srv.protocols if p.proto == AWG)
        saved = AwgParams.from_dict(json.loads(sp.params_json))
    # aggressive-пресет применён: Jc/Jmin из PreSETS
    assert saved.jc == "6"
    assert saved.jmin == "40"
    # то же, что ушло в SSH-применение
    assert applied["params"].jc == "6"


async def test__set_protocol_params__non_wireguard__bad_request(uow, settings, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110002")
        server = await make_server(s, owner_id=owner.id, ip="203.0.113.202", status="online")

    svc = ServerService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.set_protocol_params(owner.id, server.id, "openvpn", preset="aggressive")


async def test__set_protocol_params__offline_server__bad_request(uow, settings, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110003")
        server = await _make_awg_server(s, owner_id=owner.id, status="offline")

    svc = ServerService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.set_protocol_params(owner.id, server.id, AWG, preset="aggressive")
