"""Интеграционные тесты HostMetricsService (in-memory SQLite, без SSH).

Покрываем БД-логику: запись сэмплов ресурсов хоста (в т.ч. крупные значения памяти/диска —
BigInteger), чтение overview (последнее значение + история в хронологическом порядке),
guard владельца и ретеншн purge_old.
"""

from __future__ import annotations

import time

import pytest

from tests.factories.orm import make_server, make_user, seed
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.hostmetrics import HostMetrics
from vpnhub.services.hostmetrics import HostMetricsService

pytestmark = pytest.mark.integration


@pytest.fixture
def svc(uow, settings) -> HostMetricsService:
    return HostMetricsService(uow, settings)


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


async def test__purge_old__drops_only_stale_samples(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79002220007")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    old_at = now - (svc.settings.server_metrics_retention_days + 1) * 86400
    async with uow.transaction() as tx:
        tx.session.add(m.ServerMetric(server_id=srv.id, at=old_at, cpu_pct=1.0))
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now, cpu_pct=2.0))
        await tx.session.flush()

    removed = await svc.purge_old()
    assert removed == 1
    ov = await svc.overview(owner.id, srv.id)
    assert len(ov["samples"]) == 1
    assert ov["current"]["cpuPct"] == 2.0
