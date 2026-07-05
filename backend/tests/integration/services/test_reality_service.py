"""Интеграционный тест ServerService.set_reality: ротация shortId и смена SNI/dest для Xray.

SSH-применение подменяется фейком (ProvisioningService.set_reality возвращает обновлённый материал):
проверяем оркестрацию сервиса (владение/online/installed, validate, запись material_encrypted),
а не эмуляцию сервера.
"""

from __future__ import annotations

import json

import pytest

from tests.factories.orm import make_server, make_server_protocol, make_user, seed
from vpnhub.core.errors import BadRequest
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.security import decrypt_secret, encrypt_secret
from vpnhub.services.servers import ServerService

pytestmark = pytest.mark.integration

XRAY = "xray"


async def _make_xray_server(session, *, settings, owner_id, status="online", installed=True, running=True):
    server = await make_server(session, owner_id=owner_id, ip="203.0.113.211", status=status)
    material = ServerMaterial(xray_public_key="PBK", short_id="deadbeef", bootstrap_uuid="boot", site="old.example.com")
    await make_server_protocol(
        session,
        server_id=server.id,
        proto=XRAY,
        state="installed" if installed else "absent",
        installed=installed,
        running=running,
        material_encrypted=encrypt_secret(settings.secret_key, json.dumps(material.as_dict())),
    )
    return server


def _patch_fake_set_reality(monkeypatch, captured: dict):
    async def _fake(self, srv, sp, *, short_id, sni):  # сигнатура зеркалит боевую set_reality
        captured["short_id"] = short_id
        captured["sni"] = sni
        return ServerMaterial(xray_public_key="PBK", short_id=short_id, bootstrap_uuid="boot", site=sni)

    import vpnhub.services.servers as servers_mod

    monkeypatch.setattr(servers_mod.ProvisioningService, "set_reality", _fake)


async def test__set_reality__rotate_short_id__updates_material(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220001")
        server = await _make_xray_server(s, settings=settings, owner_id=owner.id)

    captured: dict[str, str] = {}
    _patch_fake_set_reality(monkeypatch, captured)

    svc = ServerService(uow, settings)
    out = await svc.set_reality(owner.id, server.id, XRAY, rotate_short_id=True)

    assert out["id"] == server.id
    # новый shortId сгенерирован (hex длины 16) и отличается от исходного
    assert len(captured["short_id"]) == 16
    assert captured["short_id"] != "deadbeef"
    assert captured["sni"] == "old.example.com"  # SNI не менялся
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        sp = next(p for p in srv.protocols if p.proto == XRAY)
        mat = ServerMaterial.from_dict(json.loads(decrypt_secret(settings.secret_key, sp.material_encrypted)))
    assert mat.short_id == captured["short_id"]


async def test__set_reality__change_sni__updates_material(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220002")
        server = await _make_xray_server(s, settings=settings, owner_id=owner.id)

    captured: dict[str, str] = {}
    _patch_fake_set_reality(monkeypatch, captured)

    svc = ServerService(uow, settings)
    await svc.set_reality(owner.id, server.id, XRAY, sni="new.example.net")

    assert captured["sni"] == "new.example.net"
    assert captured["short_id"] == "deadbeef"  # shortId сохранён
    async with uow.query() as tx:
        srv = await tx.servers.get(server.id)
        sp = next(p for p in srv.protocols if p.proto == XRAY)
        mat = ServerMaterial.from_dict(json.loads(decrypt_secret(settings.secret_key, sp.material_encrypted)))
    assert mat.site == "new.example.net"


async def test__set_reality__invalid_sni__bad_request(uow, settings, session_maker, monkeypatch):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220003")
        server = await _make_xray_server(s, settings=settings, owner_id=owner.id)

    _patch_fake_set_reality(monkeypatch, {})
    svc = ServerService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.set_reality(owner.id, server.id, XRAY, sni="not-a-domain")


async def test__set_reality__non_xray__bad_request(uow, settings, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220004")
        server = await make_server(s, owner_id=owner.id, ip="203.0.113.212", status="online")

    svc = ServerService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.set_reality(owner.id, server.id, "openvpn", rotate_short_id=True)


async def test__set_reality__offline_server__bad_request(uow, settings, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220005")
        server = await _make_xray_server(s, settings=settings, owner_id=owner.id, status="offline")

    svc = ServerService(uow, settings)
    with pytest.raises(BadRequest):
        await svc.set_reality(owner.id, server.id, XRAY, rotate_short_id=True)
