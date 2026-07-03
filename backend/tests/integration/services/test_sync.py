"""Интеграционные тесты SyncService: инвариант ledger долга на снятие и reconcile в absent.

SSH-слой (и чтение контейнеров) подменяется фейком; проверяем ключевые свойства сверки,
а не эмуляцию сервера. Чистая логика сверки покрыта в test_sync_logic.
"""

from __future__ import annotations

import json

import pytest

import vpnhub.services.sync as sync_mod
from tests.factories.orm import make_server, make_server_protocol, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.ssh import SshError
from vpnhub.services.provisioning import PROVISIONED_PROTO_IDS
from vpnhub.services.sync import SyncService

pytestmark = pytest.mark.integration

PROTO_ID = PROVISIONED_PROTO_IDS[0]
VENDOR = pc.spec_by_id(PROTO_ID).vendor


class _UnreachableSsh:
    """SSH, падающий на подключении → сервер целиком пропускается."""

    def __init__(self, creds, *, connect_timeout=20.0):
        pass

    async def __aenter__(self):
        raise SshError("down")

    async def __aexit__(self, *exc):
        return False


class _NoopSsh:
    """Успешное SSH-подключение (реальные операции подменяются отдельно)."""

    def __init__(self, creds, *, connect_timeout=20.0):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def _fetch_sp(uow, sp_id):
    async with uow.query() as tx:
        return await tx.session.get(m.ServerProtocol, sp_id)


async def test__sync_server__ssh_unreachable__preserves_ledger_and_state(uow, settings, session_maker, monkeypatch):
    """Сервер недоступен → reachable=False; долг на снятие и installed-состояние НЕ трогаются."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
        sp = await make_server_protocol(
            s,
            server_id=server.id,
            proto=PROTO_ID,
            vendor=VENDOR,
            state="installed",
            installed=True,
            running=True,
            pending_revoke_json=json.dumps(["cid1", "cid2"]),
        )
        sp_id = sp.id
    monkeypatch.setattr(sync_mod, "SshClient", _UnreachableSsh)
    svc = SyncService(uow, settings)

    # Act
    result = await svc.sync_server(server.id)

    # Assert
    assert result["reachable"] is False
    sp2 = await _fetch_sp(uow, sp_id)
    assert set(json.loads(sp2.pending_revoke_json)) == {"cid1", "cid2"}  # долг цел
    assert sp2.installed is True and sp2.state == "installed"  # состояние не затёрто


async def test__sync_server__container_absent__drains_ledger_and_marks_absent(
    uow, settings, session_maker, monkeypatch
):
    """SSH доступен, но контейнер снесён → долг гасится (пиры мертвы), протокол → absent."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        server = await make_server(s, owner_id=owner.id)
        sp = await make_server_protocol(
            s,
            server_id=server.id,
            proto=PROTO_ID,
            vendor=VENDOR,
            state="installed",
            installed=True,
            running=True,
            pending_revoke_json=json.dumps(["cid1"]),
        )
        sp_id = sp.id
    monkeypatch.setattr(sync_mod, "SshClient", _NoopSsh)

    async def _no_containers(_ssh):
        return {}

    monkeypatch.setattr(sync_mod, "list_known_containers", _no_containers)
    svc = SyncService(uow, settings)

    # Act
    result = await svc.sync_server(server.id)

    # Assert
    assert result["reachable"] is True
    assert result["drained"] == 1
    sp2 = await _fetch_sp(uow, sp_id)
    assert sp2.pending_revoke_json is None  # долг погашен (пиры заведомо мертвы)
    assert sp2.installed is False and sp2.state == "absent"
