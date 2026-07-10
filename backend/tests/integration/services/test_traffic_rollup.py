"""Интеграционные тесты TrafficRollupService (in-memory SQLite): ярусные агрегаты + ретеншн."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from tests.factories.orm import make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.services.traffic_rollup import TrafficRollupService

pytestmark = pytest.mark.integration

_HOUR = 3600
_DAY = 86400


@pytest.fixture
def svc(uow, settings) -> TrafficRollupService:
    return TrafficRollupService(uow, settings)


async def _add_samples(uow, rows: list[dict]) -> None:
    async with uow.transaction() as tx:
        for r in rows:
            tx.session.add(m.TrafficSample(**r))
        await tx.session.flush()


async def _hourly(uow) -> list[m.TrafficHourly]:
    async with uow.query() as tx:
        return list((await tx.session.execute(select(m.TrafficHourly).order_by(m.TrafficHourly.bucket))).scalars())


async def _daily(uow) -> list[m.TrafficDaily]:
    async with uow.query() as tx:
        return list((await tx.session.execute(select(m.TrafficDaily).order_by(m.TrafficDaily.bucket))).scalars())


async def test__rollup_hourly__aggregates_raw_into_hour_buckets(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440001")
        srv = await make_server(s, owner_id=owner.id)

    # два часа трафика клиента + другой клиент в первом часе
    await _add_samples(
        uow,
        [
            {"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100.0, "rx_delta": 10, "tx_delta": 20},
            {"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 200.0, "rx_delta": 5, "tx_delta": 6},
            {"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 3700.0, "rx_delta": 1, "tx_delta": 2},
            {"server_id": srv.id, "proto": "xray", "client_id": "B", "at": 150.0, "rx_delta": 7, "tx_delta": 8,
             "online": True},
        ],
    )
    n = await svc.rollup_hourly(now=7200.0)
    assert n == 3  # (A,h0), (A,h1), (B,h0)
    rows = await _hourly(uow)
    a0 = next(r for r in rows if r.client_id == "A" and r.bucket == 0)
    assert (a0.rx, a0.tx, a0.samples_total) == (15, 26, 2)
    a1 = next(r for r in rows if r.client_id == "A" and r.bucket == _HOUR)
    assert (a1.rx, a1.tx) == (1, 2)


async def test__rollup_daily__aggregates_hourly(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440002")
        srv = await make_server(s, owner_id=owner.id)

    await _add_samples(
        uow,
        [
            {"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100.0, "rx_delta": 10, "tx_delta": 20},
            {"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 3700.0, "rx_delta": 1, "tx_delta": 2},
        ],
    )
    await svc.rollup_hourly(now=7200.0)
    await svc.rollup_daily(now=7200.0)
    days = await _daily(uow)
    assert len(days) == 1
    assert (days[0].rx, days[0].tx, days[0].bucket) == (11, 22, 0)


async def test__run_tick__is_idempotent(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440003")
        srv = await make_server(s, owner_id=owner.id)

    svc.settings.traffic_raw_retention_days = 3650  # не чистим сырьё в этом тесте
    await _add_samples(
        uow,
        [{"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100.0, "rx_delta": 10, "tx_delta": 20}],
    )
    await svc.rollup_hourly(now=7200.0)
    await svc.rollup_daily(now=7200.0)
    first_h = [(r.client_id, r.bucket, r.rx, r.tx) for r in await _hourly(uow)]
    first_d = [(r.client_id, r.bucket, r.rx, r.tx) for r in await _daily(uow)]

    await svc.rollup_hourly(now=7200.0)  # повторный прогон
    await svc.rollup_daily(now=7200.0)
    assert [(r.client_id, r.bucket, r.rx, r.tx) for r in await _hourly(uow)] == first_h
    assert [(r.client_id, r.bucket, r.rx, r.tx) for r in await _daily(uow)] == first_d


async def test__rollup_hourly__late_sample_recomputes_only_tail(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440004")
        srv = await make_server(s, owner_id=owner.id)

    await _add_samples(
        uow,
        [{"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100.0, "rx_delta": 10, "tx_delta": 20}],
    )
    await svc.rollup_hourly(now=7200.0)
    # поздний сэмпл в тот же час → повторный прогон пересчитывает бакет (не задваивает)
    await _add_samples(
        uow,
        [{"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 300.0, "rx_delta": 5, "tx_delta": 5}],
    )
    await svc.rollup_hourly(now=7200.0)
    rows = await _hourly(uow)
    assert len(rows) == 1
    assert (rows[0].rx, rows[0].tx, rows[0].samples_total) == (15, 25, 2)


async def test__rollup_hourly__does_not_zero_history_after_raw_purge(svc, session_maker, uow):
    """Кламп recompute_from = oldest_raw: старые hourly-бакеты, чьё сырьё удалено, не зануляются."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440005")
        srv = await make_server(s, owner_id=owner.id)

    # старый час свёрнут в hourly, затем его сырьё «удалено»; новое сырьё — в свежем часе
    await _add_samples(
        uow,
        [{"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100.0, "rx_delta": 10, "tx_delta": 20}],
    )
    await svc.rollup_hourly(now=200.0)
    async with uow.transaction() as tx:  # эмулируем purge сырья старого часа
        await tx.session.execute(m.TrafficSample.__table__.delete())
    await _add_samples(
        uow,
        [{"server_id": srv.id, "proto": "awg", "client_id": "A", "at": 100000.0, "rx_delta": 1, "tx_delta": 1}],
    )
    await svc.rollup_hourly(now=100200.0)
    rows = await _hourly(uow)
    buckets = {r.bucket: (r.rx, r.tx) for r in rows}
    assert buckets[0] == (10, 20)  # старый бакет цел (не занулён)
    assert bucket_for(100000.0) in buckets  # новый бакет добавлен


def bucket_for(at: float) -> int:
    return int(at) - int(at) % _HOUR


async def test__purge_old__three_tiers_and_daily_forever(svc, session_maker, uow):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440006")
        srv = await make_server(s, owner_id=owner.id)

    svc.settings.traffic_raw_retention_days = 7
    svc.settings.traffic_hourly_retention_days = 90
    svc.settings.traffic_daily_retention_days = 0  # вечно
    now = 1_000_000_000.0
    async with uow.transaction() as tx:
        # сырьё: одно старое (>7д), одно свежее
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="A", at=now - 8 * _DAY))
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="A", at=now))
        # hourly: одно старое (>90д), одно свежее
        tx.session.add(m.TrafficHourly(server_id=srv.id, proto="awg", client_id="A", bucket=int(now - 91 * _DAY)))
        tx.session.add(m.TrafficHourly(server_id=srv.id, proto="awg", client_id="A", bucket=int(now)))
        # daily: очень старое — не должно удаляться при retention=0
        tx.session.add(m.TrafficDaily(server_id=srv.id, proto="awg", client_id="A", bucket=int(now - 1000 * _DAY)))
        await tx.session.flush()

    res = await svc.purge_old(now=now)
    assert res["purged_raw"] == 1
    assert res["purged_hourly"] == 1
    assert res["purged_daily"] == 0  # daily_retention=0 → вечно
    assert len(await _daily(uow)) == 1


async def test__purge_old__daily_finite_retention_deletes_old_buckets(svc, session_maker, uow):
    # A2: daily теперь по умолчанию конечный — старые посуточные бакеты чистятся
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79004440007")
        srv = await make_server(s, owner_id=owner.id)

    svc.settings.traffic_daily_retention_days = 730
    now = 1_000_000_000.0
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficDaily(server_id=srv.id, proto="awg", client_id="A", bucket=int(now - 800 * _DAY)))
        tx.session.add(m.TrafficDaily(server_id=srv.id, proto="awg", client_id="A", bucket=int(now - 10 * _DAY)))
        await tx.session.flush()

    res = await svc.purge_old(now=now)
    assert res["purged_daily"] == 1  # старше 730 дней удалён, свежий остался
    remaining = await _daily(uow)
    assert len(remaining) == 1
    assert remaining[0].bucket == int(now - 10 * _DAY)
