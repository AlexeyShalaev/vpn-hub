"""Этап 3b: реконсиляция лимита трафика в sync (SyncService._reconcile_byte_limits).

Логику решения (suspend при превышении / resume при возврате под лимит) проверяем на реальном
SQLite с фейковым ProvisioningService — SSH/провижининг не трогаем.
"""

from __future__ import annotations

import time

import pytest

from tests.factories.orm import make_device, make_device_config, make_group, make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial
from vpnhub.services.limits import period_start
from vpnhub.services.sync import SyncService
from vpnhub.services.sync_logic import ProtocolObservation

pytestmark = pytest.mark.integration

_GB = 1024**3
_AWG = pc.spec_by_id("awg").label


class _FakeProv:
    """Фейковый ProvisioningService: не ходит по SSH, помечает все переданные конфиги как успешные."""

    def __init__(self) -> None:
        self.suspended: list[tuple[str, str, ClientMaterial]] = []
        self.resumed: list[tuple[str, str, ClientMaterial]] = []

    def material_from_config(self, c: m.DeviceConfig) -> ClientMaterial:
        return ClientMaterial(client_id=c.client_id or "", client_ip=c.client_ip or "")

    async def suspend_configs(self, refs: list[tuple[str, str, ClientMaterial]]) -> set[str]:
        self.suspended = refs
        return {mat.client_id for _s, _p, mat in refs}

    async def resume_configs(self, refs: list[tuple[str, str, ClientMaterial]]) -> set[str]:
        self.resumed = refs
        return {mat.client_id for _s, _p, mat in refs}


async def _setup(s, *, phone: str, token: str, limit_bytes: int, used_bytes: int, status: str):
    owner = await make_user(s, phone=phone)
    user = await make_user(s, phone=phone[:-1] + "9")
    srv = await make_server(s, owner_id=owner.id, name=f"srv-{token}")  # billing_day None → 1-е число
    g = await make_group(s, owner_id=owner.id, token=token)
    g.max_bytes = limit_bytes or None  # 0 → None (без лимита), как нормализует API
    s.add(m.GroupMember(group_id=g.id, user_id=user.id, display_name="u", status="active"))
    dev = await make_device(s, user_id=user.id)
    cfg = await make_device_config(
        s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", proto=_AWG, status=status, client_id="pk1"
    )
    cfg.client_ip = "10.8.1.9"
    ps = period_start(time.time(), None)
    s.add(m.TrafficUsage(server_id=srv.id, user_id=user.id, period_start=ps, rx_bytes=used_bytes, tx_bytes=0))
    await s.flush()
    return srv.id, cfg.id


async def test__reconcile__suspends_user_over_limit(session_maker, uow, settings) -> None:
    async with seed(session_maker) as s:
        srv_id, cfg_id = await _setup(
            s, phone="+79005550001", token="grp-over", limit_bytes=_GB, used_bytes=2 * _GB, status="active"
        )
    fake = _FakeProv()
    await SyncService(uow, settings)._reconcile_byte_limits(srv_id, fake)

    assert len(fake.suspended) == 1  # один конфиг к отсечке
    assert not fake.resumed
    async with uow.query() as tx:
        cfg = await tx.session.get(m.DeviceConfig, cfg_id)
        assert cfg.status == "suspended"


async def test__reconcile__resumes_when_under_limit_after_reset(session_maker, uow, settings) -> None:
    # suspended-конфиг, а usage за ТЕКУЩИЙ период = 0 (как после сброса) → должен вернуться
    async with seed(session_maker) as s:
        srv_id, cfg_id = await _setup(
            s, phone="+79005550002", token="grp-under", limit_bytes=_GB, used_bytes=0, status="suspended"
        )
    fake = _FakeProv()
    await SyncService(uow, settings)._reconcile_byte_limits(srv_id, fake)

    assert len(fake.resumed) == 1
    assert not fake.suspended
    async with uow.query() as tx:
        cfg = await tx.session.get(m.DeviceConfig, cfg_id)
        assert cfg.status == "active"


async def test__sync_apply__does_not_clobber_suspended(session_maker, uow, settings) -> None:
    """Полный проход _apply НЕ трогает suspended-конфиг, даже если клиента нет в живом листинге сервера
    (для xray/hysteria suspend убирает клиента → иначе presence-реконсиляция пометила бы revoked и
    resume уже не случился бы). Активный конфиг с отсутствующим клиентом при этом штатно → revoked.
    """
    xray_label = pc.spec_by_id("xray").label
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79006660001")
        srv = await make_server(s, owner_id=owner.id, name="srv-clob")
        dev = await make_device(s, user_id=owner.id)
        susp = await make_device_config(
            s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", proto=xray_label,
            status="suspended", client_id="UUID-A",
        )  # fmt: skip
        act = await make_device_config(
            s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", proto=xray_label,
            status="active", client_id="UUID-B",
        )  # fmt: skip
        srv_id, susp_id, act_id = srv.id, susp.id, act.id
    # xray наблюдается, но НИ ОДНОГО клиента в живом наборе (suspend убрал UUID-A; UUID-B тоже «пропал»)
    obs = {
        "xray": ProtocolObservation(
            proto_id="xray", present=True, running=True, readable_clients=True, client_ids=set()
        )
    }
    await SyncService(uow, settings)._apply(srv_id, set(), obs, {}, {}, {})
    async with uow.query() as tx:
        assert (await tx.session.get(m.DeviceConfig, susp_id)).status == "suspended"  # защищён от clobber
        assert (await tx.session.get(m.DeviceConfig, act_id)).status == "revoked"  # обычная реконсиляция цела


async def test__reconcile__ignores_manual_paused(session_maker, uow, settings) -> None:
    """Ручная пауза (status="paused") не трогается авто-реконсиляцией лимита даже при превышении:
    реконсиляция работает только со статусами active/suspended, поэтому ручная пауза с ней не воюет.
    """
    async with seed(session_maker) as s:
        srv_id, cfg_id = await _setup(
            s, phone="+79005550004", token="grp-paused", limit_bytes=_GB, used_bytes=5 * _GB, status="paused"
        )
    fake = _FakeProv()
    await SyncService(uow, settings)._reconcile_byte_limits(srv_id, fake)

    assert not fake.suspended and not fake.resumed  # paused не суспендится и не резюмится авто
    async with uow.query() as tx:
        assert (await tx.session.get(m.DeviceConfig, cfg_id)).status == "paused"  # ручная пауза цела


async def test__sync_apply__does_not_clobber_paused(session_maker, uow, settings) -> None:
    """Полный проход _apply не перетирает ручную паузу (paused), как и авто-suspended."""
    xray_label = pc.spec_by_id("xray").label
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79006660002")
        srv = await make_server(s, owner_id=owner.id, name="srv-paused")
        dev = await make_device(s, user_id=owner.id)
        cfg = await make_device_config(
            s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", proto=xray_label,
            status="paused", client_id="UUID-P",
        )  # fmt: skip
        srv_id, cfg_id = srv.id, cfg.id
    obs = {
        "xray": ProtocolObservation(
            proto_id="xray", present=True, running=True, readable_clients=True, client_ids=set()
        )
    }
    await SyncService(uow, settings)._apply(srv_id, set(), obs, {}, {}, {})
    async with uow.query() as tx:
        assert (await tx.session.get(m.DeviceConfig, cfg_id)).status == "paused"  # ручная пауза защищена


async def test__reconcile__no_limit__does_nothing(session_maker, uow, settings) -> None:
    # без байт-лимита (group.max_bytes=0 → None) активный конфиг не трогаем даже при большом трафике
    async with seed(session_maker) as s:
        srv_id, cfg_id = await _setup(
            s, phone="+79005550003", token="grp-nolim", limit_bytes=0, used_bytes=9 * _GB, status="active"
        )
    fake = _FakeProv()
    await SyncService(uow, settings)._reconcile_byte_limits(srv_id, fake)

    assert not fake.suspended and not fake.resumed
    async with uow.query() as tx:
        cfg = await tx.session.get(m.DeviceConfig, cfg_id)
        assert cfg.status == "active"
