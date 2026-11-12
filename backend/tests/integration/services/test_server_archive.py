"""Архив серверов: archive/unarchive и то, что архивный сервер выпадает из фоновых циклов,
не виден участникам, не начисляет расход и не трогается по SSH.

SSH нигде не мокается «на успех»: архивный путь обязан до него не доходить, поэтому фейки
SSH-клиентов падают при вызове.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

import vpnhub.services.provisioning as prov_mod
import vpnhub.services.servers as srv_mod
from tests.factories.orm import (
    add_member,
    grant_group_server,
    make_device,
    make_device_config,
    make_group,
    make_server,
    make_user,
    seed,
)
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.probe import ProbeResult
from vpnhub.infra.provisioning.creds import server_creds
from vpnhub.services.configs import ConfigService
from vpnhub.services.finance import FinanceService
from vpnhub.services.me import MeService
from vpnhub.services.metrics import MetricsService
from vpnhub.services.multihop import ChainService
from vpnhub.services.provisioning import ProvisioningService
from vpnhub.services.servers import ServerService
from vpnhub.services.sync import SyncService
from vpnhub.services.traffic import TrafficService

pytestmark = pytest.mark.integration

DAY = 86400.0


class _NoSsh:
    """SSH-клиент, которого на архивном пути быть не должно."""

    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("SSH must not be used for an archived server")


@pytest.fixture
def no_ssh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prov_mod, "SshClient", _NoSsh)


async def _events(session_maker, type_: str) -> list[m.AuditEvent]:
    async with session_maker() as s:
        return list((await s.execute(select(m.AuditEvent).where(m.AuditEvent.type == type_))).scalars().all())


async def _owner_and_server(session_maker, *, phone="+79005550001", name="old-vps", status="online"):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone=phone)
        srv = await make_server(s, owner_id=owner.id, name=name, status=status, installed_vpns=("amnezia",))
        return owner.id, srv.id


# --- archive / unarchive ------------------------------------------------------


async def test__archive__sets_archived_at_and_writes_one_event(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    svc = ServerService(uow, settings)

    first = await svc.archive(oid, sid)
    second = await svc.archive(oid, sid)  # повтор — no-op

    assert first["archivedAt"] is not None
    assert second["archivedAt"] == first["archivedAt"]
    events = await _events(session_maker, audit_types.SERVER_ARCHIVE)
    assert len(events) == 1
    assert events[0].target_id == sid
    assert events[0].owner_user_id == oid


async def test__archive__foreign_server__raises_not_found(uow, settings, session_maker) -> None:
    _, sid = await _owner_and_server(session_maker)
    async with seed(session_maker) as s:
        stranger = await make_user(s, phone="+79005550099")

    with pytest.raises(NotFound):
        await ServerService(uow, settings).archive(stranger.id, sid)
    with pytest.raises(NotFound):
        await ServerService(uow, settings).unarchive(stranger.id, sid)


async def test__unarchive__clears_flag_resets_status_and_writes_event(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    restored = await svc.unarchive(oid, sid)
    again = await svc.unarchive(oid, sid)  # повтор — no-op

    assert restored["archivedAt"] is None
    assert restored["status"] == "unknown"  # статус до архива устарел — перепроверит монитор
    assert again["archivedAt"] is None
    assert len(await _events(session_maker, audit_types.SERVER_UNARCHIVE)) == 1


async def test__archive__server_in_chain__raises_and_stays_active(uow, settings, session_maker) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550002")
        entry = await make_server(s, owner_id=owner.id, name="entry", ip="203.0.113.1")
        exit_srv = await make_server(s, owner_id=owner.id, name="exit", ip="203.0.113.2")
        s.add(m.ChainLink(owner_user_id=owner.id, entry_server_id=entry.id, exit_server_id=exit_srv.id))
    svc = ServerService(uow, settings)

    for sid in (entry.id, exit_srv.id):
        with pytest.raises(BadRequest) as exc:
            await svc.archive(owner.id, sid)
        assert exc.value.key == "server.archive_in_chain"
        assert (await svc.get(owner.id, sid))["archivedAt"] is None


async def test__unarchive__reconciles_users_with_configs_on_server(
    uow, settings, session_maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550003")
        member = await make_user(s, phone="+79005550004")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia",))
        dev = await make_device(s, user_id=member.id)
        await make_device_config(s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", client_id="c1")
    seen: list[list[str]] = []

    async def fake_reconcile(self, user_ids):
        seen.append(sorted(user_ids))

    monkeypatch.setattr(ProvisioningService, "reconcile_users", fake_reconcile)
    svc = ServerService(uow, settings)
    await svc.archive(owner.id, srv.id)

    await svc.unarchive(owner.id, srv.id)

    assert seen == [[member.id]]


# --- SSH-операции заблокированы -------------------------------------------------


def test__server_creds__archived_server__raises(settings) -> None:
    server = m.Server(owner_user_id="o", name="x", provider="p", ip="203.0.113.5", archived_at=time.time())

    with pytest.raises(BadRequest) as exc:
        server_creds(server, settings.secret_key)
    assert exc.value.key == "server.archived"


@pytest.mark.parametrize(
    "call",
    [
        lambda svc, oid, sid: svc.check(oid, sid),
        lambda svc, oid, sid: svc.sync(oid, sid),
        lambda svc, oid, sid: svc.vpn_op(oid, sid, "amnezia", "install"),
        lambda svc, oid, sid: svc.protocol_op(oid, sid, "awg", "stop"),
        lambda svc, oid, sid: svc.migrate(oid, sid, {"ip": "203.0.113.77"}),
    ],
)
async def test__host_operations__archived_server__raise_archived(uow, settings, session_maker, call, no_ssh) -> None:
    oid, sid = await _owner_and_server(session_maker)
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    with pytest.raises(BadRequest) as exc:
        await call(svc, oid, sid)
    assert exc.value.key == "server.archived"


async def test__update__archived_server__still_allowed(uow, settings, session_maker) -> None:
    """Правка карточки (имя/локация) — без SSH, в архиве разрешена."""
    oid, sid = await _owner_and_server(session_maker)
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    out = await svc.update(oid, sid, {"name": "old-vps (off)"})

    assert out["name"] == "old-vps (off)"


async def test__delete__archived_server__no_ssh_and_removes_row(uow, settings, session_maker, no_ssh) -> None:
    oid, sid = await _owner_and_server(session_maker)
    async with seed(session_maker) as s:
        s.add(m.ServerProtocol(server_id=sid, vendor="amnezia", proto="awg", installed=True, state="installed"))
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    await svc.delete(oid, sid)

    with pytest.raises(NotFound):
        await svc.get(oid, sid)


# --- фоновые циклы ---------------------------------------------------------------


async def test__monitor_tick__skips_archived(uow, settings, session_maker, monkeypatch: pytest.MonkeyPatch) -> None:
    probed: list[str] = []

    async def fake_probe(host: str, port: int, timeout: float) -> ProbeResult:
        probed.append(host)
        return ProbeResult(True, 10, "SSH")

    monkeypatch.setattr(srv_mod, "probe_tcp", fake_probe)
    monkeypatch.setattr(ServerService, "_collect_host_metrics", lambda self, ids: _noop())
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550005")
        live = await make_server(s, owner_id=owner.id, name="live", ip="203.0.113.10", status="unknown")
        dead = await make_server(s, owner_id=owner.id, name="dead", ip="203.0.113.11", status="offline")
    svc = ServerService(uow, settings)
    await svc.archive(owner.id, dead.id)

    count = await svc.run_tick()

    assert count == 1
    assert probed == ["203.0.113.10"]
    assert (await svc.get(owner.id, live.id))["status"] == "online"
    assert (await svc.get(owner.id, dead.id))["status"] == "offline"  # не тронут


async def _noop() -> None:
    return None


async def test__sync_tick__skips_archived(uow, settings, session_maker, monkeypatch: pytest.MonkeyPatch) -> None:
    synced: list[str] = []

    async def fake_sync(self, server_id: str) -> dict:
        synced.append(server_id)
        return {}

    monkeypatch.setattr(SyncService, "sync_server", fake_sync)
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550006")
        live = await make_server(s, owner_id=owner.id, name="live", ip="203.0.113.20")
        dead = await make_server(s, owner_id=owner.id, name="dead", ip="203.0.113.21")
    await ServerService(uow, settings).archive(owner.id, dead.id)

    done = await SyncService(uow, settings).run_tick()

    assert done == 1
    assert synced == [live.id]


async def test__metrics_server_counts__exclude_archived(uow, settings, session_maker) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550007")
        await make_server(s, owner_id=owner.id, name="a", ip="203.0.113.30", status="online")
        dead = await make_server(s, owner_id=owner.id, name="b", ip="203.0.113.31", status="offline")
    await ServerService(uow, settings).archive(owner.id, dead.id)

    async with uow.query() as tx:
        counts = await MetricsService(uow, settings)._server_counts(tx)

    assert counts == {"online": 1, "offline": 0, "unknown": 0}


async def test__global_monitoring__excludes_archived(uow, settings, session_maker) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550008")
        await make_server(s, owner_id=owner.id, name="a", ip="203.0.113.40")
        dead = await make_server(s, owner_id=owner.id, name="b", ip="203.0.113.41")
    await ServerService(uow, settings).archive(owner.id, dead.id)

    out = await TrafficService(uow, settings).global_overview(owner.id)

    assert out["summary"]["serversTotal"] == 1


# --- участники -------------------------------------------------------------------


async def _member_with_access(session_maker, *, phone_owner: str, phone_member: str):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone=phone_owner)
        member = await make_user(s, phone=phone_member, name="Мария")
        srv = await make_server(s, owner_id=owner.id, name="nl", installed_vpns=("amnezia",))
        group = await make_group(s, owner_id=owner.id, token=f"grp-{phone_member}")
        await add_member(s, group_id=group.id, user_id=member.id)
        await grant_group_server(s, group_id=group.id, server_id=srv.id, vpn_type="amnezia")
        dev = await make_device(s, user_id=member.id)
        return owner.id, member.id, srv.id, dev.id


async def test__me_available__archived_server_hidden_and_back_after_restore(uow, settings, session_maker) -> None:
    oid, uid, sid, _ = await _member_with_access(session_maker, phone_owner="+79005550010", phone_member="+79005550011")
    svc = ServerService(uow, settings)
    me = MeService(uow, settings)
    assert [x["id"] for x in await me.available(uid)] == [sid]

    await svc.archive(oid, sid)
    hidden = await me.available(uid)
    await svc.unarchive(oid, sid)

    assert hidden == []
    assert [x["id"] for x in await me.available(uid)] == [sid]


async def test__generate_config__archived_server__raises(uow, settings, session_maker) -> None:
    oid, uid, sid, dev_id = await _member_with_access(
        session_maker, phone_owner="+79005550012", phone_member="+79005550013"
    )
    await ServerService(uow, settings).archive(oid, sid)

    with pytest.raises(BadRequest) as exc:
        await ConfigService(uow, settings).generate(uid, sid, "amnezia", dev_id, None)
    assert exc.value.key == "config.server_archived"


async def test__reconcile_user__keeps_configs_on_archived_server_without_ssh(
    uow, settings, session_maker, no_ssh
) -> None:
    """Доступ пропал, пока сервер в архиве: конфиг не удаляем и по SSH не ходим (снимем после возврата)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550014")
        member = await make_user(s, phone="+79005550015")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia",))
        dev = await make_device(s, user_id=member.id)
        cfg = await make_device_config(
            s, device_id=dev.id, server_id=srv.id, vpn_type="amnezia", proto="AmneziaWG", client_id="c1"
        )
    await ServerService(uow, settings).archive(owner.id, srv.id)

    await ProvisioningService(uow, settings).reconcile_user(member.id)

    async with session_maker() as s:
        assert await s.get(m.DeviceConfig, cfg.id) is not None


async def test__revoke_on_servers__archived_server__skips_ssh(uow, settings, session_maker, no_ssh) -> None:
    oid, sid = await _owner_and_server(session_maker)
    await ServerService(uow, settings).archive(oid, sid)

    await ProvisioningService(uow, settings).revoke_on_servers([(sid, "AmneziaWG", "c1")])  # не падает, без SSH


# --- финансы ---------------------------------------------------------------------


async def _price_rows(session_maker, sid: str) -> list[m.ServerPrice]:
    async with session_maker() as s:
        rows = (await s.execute(select(m.ServerPrice).where(m.ServerPrice.server_id == sid))).scalars().all()
        return sorted(rows, key=lambda r: r.effective_from)


async def test__archive__closes_price_segment_and_stops_accrual(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    fin = FinanceService(uow, settings)
    await fin.set_price(oid, sid, 300, "RUB", "month", None)
    svc = ServerService(uow, settings)

    await svc.archive(oid, sid)

    rows = await _price_rows(session_maker, sid)
    assert len(rows) == 1 and rows[0].effective_to is not None
    assert await fin.get_price(oid, sid) is None
    later = time.time() + 30 * DAY  # окно целиком после архива — начислять нечего
    cost = await fin.server_cost(oid, sid, time.time(), later)
    assert cost["byCurrency"] == []


async def test__unarchive__resumes_same_price(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    fin = FinanceService(uow, settings)
    await fin.set_price(oid, sid, 300, "RUB", "month", 15)
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    await svc.unarchive(oid, sid)

    rows = await _price_rows(session_maker, sid)
    assert len(rows) == 2
    assert rows[0].effective_to is not None and rows[1].effective_to is None
    price = await fin.get_price(oid, sid)
    assert price is not None
    assert (price["amount"], price["currency"], price["period"], price["anchorDay"]) == (300, "RUB", "month", 15)


async def test__unarchive__no_price_before_archive__stays_free(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    svc = ServerService(uow, settings)
    await svc.archive(oid, sid)

    await svc.unarchive(oid, sid)

    assert await _price_rows(session_maker, sid) == []


async def test__set_price__archived_server__raises(uow, settings, session_maker) -> None:
    oid, sid = await _owner_and_server(session_maker)
    await ServerService(uow, settings).archive(oid, sid)

    with pytest.raises(BadRequest) as exc:
        await FinanceService(uow, settings).set_price(oid, sid, 100, "RUB", "month", None)
    assert exc.value.key == "finance.server_archived"


async def test__finance_overview__archived_without_cost_hidden_quota_not_counted(uow, settings, session_maker) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550016")
        live = await make_server(s, owner_id=owner.id, name="live", ip="203.0.113.50")
        dead = await make_server(s, owner_id=owner.id, name="dead", ip="203.0.113.51")
        dead.bandwidth_quota_bytes = 10**12
    await ServerService(uow, settings).archive(owner.id, dead.id)
    now = time.time()

    out = await FinanceService(uow, settings).overview(owner.id, now - DAY, now)

    assert [row["serverId"] for row in out["servers"]] == [live.id]
    assert out["totals"]["trafficQuotaBytes"] is None


# --- мультихоп -------------------------------------------------------------------


async def test__chain_create__archived_server__raises(uow, settings, session_maker) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550017")
        entry = await make_server(s, owner_id=owner.id, name="entry", ip="203.0.113.60", status="online")
        exit_srv = await make_server(s, owner_id=owner.id, name="exit", ip="203.0.113.61", status="online")
    await ServerService(uow, settings).archive(owner.id, exit_srv.id)

    with pytest.raises(BadRequest) as exc:
        await ChainService(uow, settings).create(owner.id, entry.id, exit_srv.id)
    assert exc.value.key == "multihop.server_archived"
