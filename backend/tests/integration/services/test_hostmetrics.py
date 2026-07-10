"""Интеграционные тесты HostMetricsService (in-memory SQLite, без SSH).

Покрываем БД-логику: запись сэмплов ресурсов хоста (в т.ч. крупные значения памяти/диска —
BigInteger), чтение overview (последнее значение + история в хронологическом порядке),
guard владельца и ретеншн purge_old.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from sqlalchemy import select

from tests.factories.orm import make_server, make_server_protocol, make_user, seed
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.hostmetrics import HostMetrics
from vpnhub.infra.provisioning import constants as pc
from vpnhub.services import hostmetrics as hm
from vpnhub.services.hostmetrics import HostMetricsService
from vpnhub.services.traffic import TRAFFIC_OK, PeerStat, ProtoTraffic
from vpnhub.services.traffic_rollup import bucket_start

pytestmark = pytest.mark.integration


@pytest.fixture
def svc(uow, settings) -> HostMetricsService:
    return HostMetricsService(uow, settings)


class _FakeSshCM:
    """Фейковый async-CM SshClient: __aenter__ отдаёт объект (сам сбор монки-патчится)."""

    def __init__(self, *a: Any, raise_on_enter: Exception | None = None, **k: Any) -> None:
        self._raise = raise_on_enter

    async def __aenter__(self) -> Any:
        if self._raise is not None:
            raise self._raise
        return object()

    async def __aexit__(self, *a: Any) -> None:
        return None


async def test__record__then_overview_returns_current_and_samples(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220001")
        srv = await make_server(s, owner_id=owner.id)

    # крупные значения памяти/диска — проверяем, что BigInteger переживает round-trip
    big_mem = 68719476736  # 64 ГиБ
    await svc.record(
        srv.id,
        HostMetrics(
            cpu_pct=12.5,
            load1=0.3,
            mem_used=big_mem - 1073741824,
            mem_total=big_mem,
            disk_used=10_000_000_000,
            disk_total=50_000_000_000,
            tcp_estab=17,
            uptime_s=98765,
            online_clients=3,
        ),
    )

    ov = await svc.overview(owner.id, srv.id)
    assert ov["serverId"] == srv.id
    assert len(ov["samples"]) == 1
    cur = ov["current"]
    assert cur["cpuPct"] == 12.5
    assert cur["memTotal"] == big_mem
    assert cur["memUsed"] > 2**31  # BigInteger не переполнился
    assert cur["tcpEstab"] == 17
    assert cur["onlineClients"] == 3


async def test__overview__samples_are_chronological(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220002")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now - 20, cpu_pct=10.0))
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now - 10, cpu_pct=20.0))
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now, cpu_pct=30.0))
        await tx.session.flush()

    ov = await svc.overview(owner.id, srv.id)
    ats = [x["at"] for x in ov["samples"]]
    assert ats == sorted(ats)  # хронологический порядок (asc)
    assert ov["current"]["cpuPct"] == 30.0  # последний = самый свежий


async def test__overview__no_samples__current_is_none(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220003")
        srv = await make_server(s, owner_id=owner.id)
    ov = await svc.overview(owner.id, srv.id)
    assert ov["samples"] == []
    assert ov["current"] is None


async def test__overview__respects_history_limit(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220004")
        srv = await make_server(s, owner_id=owner.id)

    svc.settings.server_metrics_history_limit = 5
    now = time.time()
    async with uow.transaction() as tx:
        for i in range(12):
            tx.session.add(m.ServerMetric(server_id=srv.id, at=now - (12 - i), cpu_pct=float(i)))
        await tx.session.flush()

    ov = await svc.overview(owner.id, srv.id)
    assert len(ov["samples"]) == 5  # только последние 5
    assert ov["current"]["cpuPct"] == 11.0  # самый свежий из 12


async def test__overview__foreign_server__raises_notfound(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220005")
        stranger = await make_user(s, phone="+79002220006")
        srv = await make_server(s, owner_id=stranger.id)
    with pytest.raises(NotFound) as exc:
        await svc.overview(owner.id, srv.id)
    assert exc.value.http_status == 404


# --------------------------------------------------------------------------- collect_for (SSH monkeypatched)


async def test__collect_for__writes_metrics_traffic_and_health(svc, session_maker, uow, monkeypatch):
    """Одна сессия: host-метрики + трафик ok-протокола + health; container_down у остановленного."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220100")
        srv = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s, server_id=srv.id, proto="awg", container="amnezia-awg2", installed=True, running=True
        )
        await make_server_protocol(
            s, server_id=srv.id, proto="xray", container="amnezia-xray", installed=True, running=True
        )

    now = time.time()

    async def fake_host_metrics(ssh: Any) -> HostMetrics:
        return HostMetrics(cpu_pct=5.0, mem_used=1, mem_total=2, online_clients=None)

    async def fake_containers(ssh: Any) -> dict[str, bool]:
        return {"amnezia-awg2": True, "amnezia-xray": False}  # xray-контейнер лёг

    async def fake_collect(ssh: Any, spec: pc.ProtoSpec, provo: Any = None) -> ProtoTraffic:
        return ProtoTraffic(
            spec.id, TRAFFIC_OK, stats=[PeerStat(client_id="P", rx=100, tx=200, last_handshake=now, online=None)]
        )

    monkeypatch.setattr(hm, "SshClient", _FakeSshCM)
    monkeypatch.setattr(hm, "collect_host_metrics", fake_host_metrics)
    monkeypatch.setattr(hm, "list_known_containers", fake_containers)
    monkeypatch.setattr(hm.TrafficCollector, "collect", staticmethod(fake_collect))

    # свежий сервер уже detached-объект (как в monitor-тике) — грузим и передаём
    async with uow.query() as tx:
        server = await tx.servers.get(srv.id)
    metrics = await svc.collect_for(server)
    assert metrics is not None

    # ServerMetric записан, online из wg-трафика (свежий handshake) = 1
    ov = await svc.overview(owner.id, srv.id)
    assert ov["current"]["onlineClients"] == 1
    # traffic_sample + peer_state для awg записаны
    async with uow.query() as tx:
        samples = (await tx.session.execute(select(m.TrafficSample))).scalars().all()
        states = (await tx.session.execute(select(m.TrafficPeerState))).scalars().all()
        protos = {sp.proto: sp for sp in (await tx.session.execute(select(m.ServerProtocol))).scalars().all()}
    assert {sm.proto for sm in samples} == {"awg"}  # xray-контейнер лёг → трафик не собирали
    assert len(states) == 1 and states[0].proto == "awg"
    # health: awg ok + collected_at; xray container_down без collected_at
    assert protos["awg"].traffic_status == "ok" and protos["awg"].traffic_collected_at is not None
    assert protos["xray"].traffic_status == "container_down" and protos["xray"].traffic_collected_at is None


async def test__collect_for__auto_heals_stats_when_disabled(svc, session_maker, uow, monkeypatch):
    """stats_disabled у xray → enable_stats вызывается раз; повтор в пределах TTL — не вызывается."""
    from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
    from vpnhub.services.traffic import TRAFFIC_STATS_DISABLED

    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220110")
        srv = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s, server_id=srv.id, proto="xray", container="amnezia-xray", installed=True, running=True
        )

    hm._STATS_HEAL_ATTEMPTS.clear()
    calls: list[str] = []

    async def fake_host_metrics(ssh: Any) -> HostMetrics:
        return HostMetrics(cpu_pct=1.0)

    async def fake_containers(ssh: Any) -> dict[str, bool]:
        return {"amnezia-xray": True}

    async def fake_collect(ssh: Any, spec: pc.ProtoSpec, provo: Any = None) -> ProtoTraffic:
        return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="off")

    async def fake_enable(self: Any, ssh: Any) -> bool:
        calls.append("enable")
        return True

    monkeypatch.setattr(hm, "SshClient", _FakeSshCM)
    monkeypatch.setattr(hm, "collect_host_metrics", fake_host_metrics)
    monkeypatch.setattr(hm, "list_known_containers", fake_containers)
    monkeypatch.setattr(hm.TrafficCollector, "collect", staticmethod(fake_collect))
    monkeypatch.setattr(XrayProvisioner, "enable_stats", fake_enable)

    async with uow.query() as tx:
        server = await tx.servers.get(srv.id)
    await svc.collect_for(server)
    await svc.collect_for(server)  # второй тик в пределах TTL
    assert calls == ["enable"]  # только одна попытка включения

    # health: статус stats_disabled с подсказкой про авто-включение
    async with uow.query() as tx:
        sp = (await tx.session.execute(select(m.ServerProtocol))).scalar_one()
    assert sp.traffic_status == "stats_disabled"


async def test__collect_for__no_auto_heal_when_disabled_by_setting(svc, session_maker, uow, monkeypatch):
    """stats_auto_enable=False → enable_stats не вызывается даже при stats_disabled."""
    from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
    from vpnhub.services.traffic import TRAFFIC_STATS_DISABLED

    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220111")
        srv = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s, server_id=srv.id, proto="xray", container="amnezia-xray", installed=True, running=True
        )

    hm._STATS_HEAL_ATTEMPTS.clear()
    svc.settings.stats_auto_enable = False
    calls: list[str] = []

    async def fake_host_metrics(ssh: Any) -> HostMetrics:
        return HostMetrics(cpu_pct=1.0)

    async def fake_containers(ssh: Any) -> dict[str, bool]:
        return {"amnezia-xray": True}

    async def fake_collect(ssh: Any, spec: pc.ProtoSpec, provo: Any = None) -> ProtoTraffic:
        return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="off")

    async def fake_enable(self: Any, ssh: Any) -> bool:
        calls.append("enable")
        return True

    monkeypatch.setattr(hm, "SshClient", _FakeSshCM)
    monkeypatch.setattr(hm, "collect_host_metrics", fake_host_metrics)
    monkeypatch.setattr(hm, "list_known_containers", fake_containers)
    monkeypatch.setattr(hm.TrafficCollector, "collect", staticmethod(fake_collect))
    monkeypatch.setattr(XrayProvisioner, "enable_stats", fake_enable)

    async with uow.query() as tx:
        server = await tx.servers.get(srv.id)
    await svc.collect_for(server)
    assert calls == []


async def test__collect_for__ssh_failure_marks_unreachable(svc, session_maker, uow, monkeypatch):
    """Сбой SSH → метрики не пишем, health всех installed-протоколов = unreachable."""
    from vpnhub.infra.provisioning.ssh import SshError

    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220101")
        srv = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s, server_id=srv.id, proto="awg", container="amnezia-awg2", installed=True, running=True
        )

    def raising_cm(*a: Any, **k: Any) -> _FakeSshCM:
        return _FakeSshCM(raise_on_enter=SshError("boom"))

    monkeypatch.setattr(hm, "SshClient", raising_cm)

    async with uow.query() as tx:
        server = await tx.servers.get(srv.id)
    assert await svc.collect_for(server) is None

    ov = await svc.overview(owner.id, srv.id)
    assert ov["samples"] == []  # метрики не записаны
    async with uow.query() as tx:
        sp = (await tx.session.execute(select(m.ServerProtocol))).scalar_one()
    assert sp.traffic_status == "unreachable"


async def test__reconcile_owner__enables_stats_where_missing(svc, session_maker, uow, monkeypatch):
    """On-access доводка: включает статистику на протоколах владельца без ok-мониторинга; ok — пропускает."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220200")
        srv = await make_server(s, owner_id=owner.id)
        await make_server_protocol(
            s, server_id=srv.id, proto="xray", container="amnezia-xray", installed=True, running=True
        )  # traffic_status=None → доводим
        await make_server_protocol(
            s, server_id=srv.id, proto="hysteria2", container="amnezia-hysteria2", installed=True, running=True
        )
        await make_server_protocol(
            s, server_id=srv.id, proto="awg", container="amnezia-awg2", installed=True, running=True
        )  # не stats-протокол
    async with uow.transaction() as tx:  # hysteria2 уже ok → трогать не должны
        sp = (
            await tx.session.execute(select(m.ServerProtocol).where(m.ServerProtocol.proto == "hysteria2"))
        ).scalar_one()
        sp.traffic_status = "ok"

    enabled: list[str] = []

    async def fake_enable(spec, ssh):
        enabled.append(spec.id)
        return True

    monkeypatch.setattr(hm, "SshClient", _FakeSshCM)
    monkeypatch.setattr(hm, "enable_stats", fake_enable)
    svc.settings.stats_auto_enable = True

    await svc._reconcile_owner(owner.id)
    assert enabled == ["xray"]  # только xray (без ok); hysteria2 уже ok, awg — не stats


async def test__kick_reconcile__throttled_per_owner(svc, monkeypatch):
    """kick_reconcile троттлится per-owner — повторный заход в окне не плодит фоновые задачи."""
    spawned: list[str] = []
    monkeypatch.setattr(hm, "_spawn", lambda coro: (spawned.append("x"), coro.close()))
    hm._RECONCILE_KICKS.clear()

    svc.kick_reconcile("owner-1")
    svc.kick_reconcile("owner-1")  # сразу же — в окне троттлинга
    assert len(spawned) == 1


async def test__rollup_tick__aggregates_and_purges_raw(svc, session_maker, uow):
    """rollup_tick сворачивает сырьё в почасовые avg/max и чистит сырьё старше ретеншна."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220007")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    hour = bucket_start(now, 3600)  # выравниваем оба свежих сэмпла в ОДИН часовой бакет (детерминизм)
    old_at = now - (svc.settings.server_metrics_retention_days + 1) * 86400
    async with uow.transaction() as tx:
        # два сэмпла в одном часе → один hourly-бакет (avg cpu 15, max 20)
        tx.session.add(m.ServerMetric(server_id=srv.id, at=hour + 10, cpu_pct=10.0, tcp_estab=5, mem_used=100))
        tx.session.add(m.ServerMetric(server_id=srv.id, at=hour + 20, cpu_pct=20.0, tcp_estab=9, mem_used=200))
        tx.session.add(m.ServerMetric(server_id=srv.id, at=old_at, cpu_pct=1.0))  # старое сырьё
        await tx.session.flush()

    res = await svc.rollup_tick()
    assert res["purged_raw"] == 1  # старый сэмпл удалён
    async with uow.query() as tx:
        hourly = list((await tx.session.execute(select(m.ServerMetricHourly))).scalars())
    # старый сэмпл (в своём часе) тоже свернулся до purge — считаем текущий бакет
    cur = next(h for h in hourly if h.samples_total == 2)
    assert cur.cpu_pct_avg == pytest.approx(15.0) and cur.cpu_pct_max == 20.0
    assert cur.tcp_estab_max == 9


async def test__rollup_tick__is_idempotent(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220008")
        srv = await make_server(s, owner_id=owner.id)

    svc.settings.server_metrics_retention_days = 3650  # не чистить сырьё
    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now, cpu_pct=10.0))
        await tx.session.flush()

    await svc.rollup_tick()
    await svc.rollup_tick()
    async with uow.query() as tx:
        hourly = list((await tx.session.execute(select(m.ServerMetricHourly))).scalars())
    assert len(hourly) == 1  # повторный прогон не задвоил


async def test__overview__long_period_reads_hourly(svc, session_maker, uow):
    """period=7d читает почасовые агрегаты (avg), 24h — сырьё."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220009")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now, cpu_pct=50.0))  # сырьё (24h)
        tx.session.add(
            m.ServerMetricHourly(
                server_id=srv.id, bucket=int(now - 3600), cpu_pct_avg=30.0, cpu_pct_max=40.0, samples_total=5
            )
        )
        await tx.session.flush()

    raw = await svc.overview(owner.id, srv.id, period="24h")
    assert raw["period"] == "24h" and raw["current"]["cpuPct"] == 50.0
    agg = await svc.overview(owner.id, srv.id, period="7d")
    assert agg["period"] == "7d" and agg["current"]["cpuPct"] == 30.0  # avg из hourly
