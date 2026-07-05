"""Интеграционный тест ChainService: мультихоп-цепочка entry → exit (Xray outbound chaining).

SSH-шаги (add_client на exit, set_chain на entry, revoke/clear при удалении) подменяются фейками:
проверяем оркестрацию сервиса (владение/online/installed, заведение клиента exit, запись ChainLink,
откат при сбое, каскад удаления), а не эмуляцию сервера.
"""

from __future__ import annotations

import json

import pytest

from tests.factories.orm import make_server, make_server_protocol, make_user, seed
from vpnhub.core.errors import BadRequest
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ServerMaterial
from vpnhub.infra.security import encrypt_secret
from vpnhub.services.multihop import ChainService

pytestmark = pytest.mark.integration

XRAY = "xray"


async def _make_xray_server(session, *, settings, owner_id, name, ip, status="online", installed=True, running=True):
    server = await make_server(session, owner_id=owner_id, name=name, ip=ip, status=status)
    material = ServerMaterial(xray_public_key="PBK", short_id="deadbeef", bootstrap_uuid="boot", site="ex.example.com")
    await make_server_protocol(
        session,
        server_id=server.id,
        proto=XRAY,
        container="amnezia-xray",
        state="installed" if installed else "absent",
        installed=installed,
        running=running,
        material_encrypted=encrypt_secret(settings.secret_key, json.dumps(material.as_dict())),
    )
    return server


def _patch_fakes(monkeypatch, captured: dict, *, set_chain_raises=False):
    import vpnhub.services.multihop as mh

    async def _add_client(self, server, sp, name):
        captured["add_client"] = {"server_id": server.id, "name": name}
        return ClientMaterial(client_id="exit-uuid-123")

    async def _set_chain(self, entry, entry_sp, *, exit_host, exit_port, exit_material, exit_uuid):
        captured["set_chain"] = {"entry_id": entry.id, "exit_host": exit_host, "exit_uuid": exit_uuid}
        if set_chain_raises:
            raise RuntimeError("boom")

    async def _revoke(self, server, sp, client_id):
        captured.setdefault("revoke", []).append({"server_id": server.id, "client_id": client_id})

    async def _clear(self, entry, entry_sp):
        captured["clear"] = {"entry_id": entry.id}

    monkeypatch.setattr(mh.ProvisioningService, "add_client", _add_client)
    monkeypatch.setattr(mh.ProvisioningService, "set_chain", _set_chain)
    monkeypatch.setattr(mh.ProvisioningService, "revoke_client", _revoke)
    monkeypatch.setattr(mh.ProvisioningService, "clear_chain", _clear)


async def test__create__links_entry_to_exit(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330001")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.1")
        exit_srv = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="NL", ip="203.0.113.2")

    captured: dict = {}
    _patch_fakes(monkeypatch, captured)

    svc = ChainService(uow, settings)
    out = await svc.create(owner.id, entry.id, exit_srv.id)

    assert out["state"] == "linked"
    assert out["exitServerId"] == exit_srv.id
    assert out["exitServerName"] == "NL"
    # клиент заведён на exit, а его uuid прописан в outbound entry
    assert captured["add_client"]["server_id"] == exit_srv.id
    assert captured["set_chain"]["entry_id"] == entry.id
    assert captured["set_chain"]["exit_host"] == "203.0.113.2"
    assert captured["set_chain"]["exit_uuid"] == "exit-uuid-123"

    async with uow.query() as tx:
        rows = (await tx.session.execute(m.ChainLink.__table__.select())).fetchall()
    assert len(rows) == 1

    listed = await svc.list_for_entry(owner.id, entry.id)
    assert len(listed) == 1 and listed[0]["exitServerName"] == "NL"


async def test__create__same_server__bad_request(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330002")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.3")
    _patch_fakes(monkeypatch, {})
    svc = ChainService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.create(owner.id, entry.id, entry.id)


async def test__create__offline_exit__bad_request(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330003")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.4")
        exit_srv = await _make_xray_server(
            s, settings=settings, owner_id=owner.id, name="NL", ip="203.0.113.5", status="offline"
        )
    _patch_fakes(monkeypatch, {})
    svc = ChainService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.create(owner.id, entry.id, exit_srv.id)


async def test__create__exit_xray_absent__bad_request(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330004")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.6")
        exit_srv = await _make_xray_server(
            s, settings=settings, owner_id=owner.id, name="NL", ip="203.0.113.7", installed=False, running=False
        )
    _patch_fakes(monkeypatch, {})
    svc = ChainService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.create(owner.id, entry.id, exit_srv.id)


async def test__create__entry_set_chain_fails__rolls_back_exit_client(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330005")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.8")
        exit_srv = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="NL", ip="203.0.113.9")

    captured: dict = {}
    _patch_fakes(monkeypatch, captured, set_chain_raises=True)
    svc = ChainService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.create(owner.id, entry.id, exit_srv.id)

    # клиент exit откачен, связка не создана
    assert captured["revoke"][0]["client_id"] == "exit-uuid-123"
    async with uow.query() as tx:
        rows = (await tx.session.execute(m.ChainLink.__table__.select())).fetchall()
    assert rows == []


async def test__delete__clears_entry_and_revokes_exit(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79003330006")
        entry = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="RU", ip="203.0.113.10")
        exit_srv = await _make_xray_server(s, settings=settings, owner_id=owner.id, name="NL", ip="203.0.113.11")

    captured: dict = {}
    _patch_fakes(monkeypatch, captured)
    svc = ChainService(uow, settings)
    link = await svc.create(owner.id, entry.id, exit_srv.id)

    await svc.delete(owner.id, entry.id, link["id"])

    assert captured["clear"]["entry_id"] == entry.id
    assert any(r["client_id"] == "exit-uuid-123" for r in captured["revoke"])
    async with uow.query() as tx:
        rows = (await tx.session.execute(m.ChainLink.__table__.select())).fetchall()
    assert rows == []
