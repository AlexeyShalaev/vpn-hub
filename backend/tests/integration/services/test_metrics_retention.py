"""Интеграционные тесты ретеншна метрик (in-memory SQLite): override дней, size-cap, отчёт использования."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from tests.factories.orm import make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.services.metrics_retention import (
    SETTING_RAW_RETENTION,
    SETTING_SIZE_CAP_GB,
    chunked_delete,
    metrics_disk_usage,
    raw_retention_override,
    size_cap_bytes,
    trim_oldest_raw_day,
)
from vpnhub.services.traffic_rollup import TrafficRollupService

pytestmark = pytest.mark.integration
_DAY = 86400.0


async def _set(uow, key: str, value: str) -> None:
    async with uow.transaction() as tx:
        await tx.settings.set_value(key, value)


async def test__raw_retention_override__reads_setting_or_none(uow):
    async with uow.query() as tx:
        assert await raw_retention_override(tx.session) is None  # не задано
    await _set(uow, SETTING_RAW_RETENTION, "3")
    async with uow.query() as tx:
        assert await raw_retention_override(tx.session) == 3
    await _set(uow, SETTING_RAW_RETENTION, "0")  # 0 → нет override (env-дефолт)
    async with uow.query() as tx:
        assert await raw_retention_override(tx.session) is None


async def test__size_cap_bytes__parses_gb(uow):
    async with uow.query() as tx:
        assert await size_cap_bytes(tx.session) == 0  # не задано
    await _set(uow, SETTING_SIZE_CAP_GB, "2")
    async with uow.query() as tx:
        assert await size_cap_bytes(tx.session) == 2_000_000_000
    await _set(uow, SETTING_SIZE_CAP_GB, "мусор")
    async with uow.query() as tx:
        assert await size_cap_bytes(tx.session) == 0


async def test__purge_old__respects_ui_override(uow, settings, session_maker):
    """UI-override дней хранения сырья перекрывает env-дефолт в purge трафика."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550001")
        srv = await make_server(s, owner_id=owner.id)

    settings.traffic_raw_retention_days = 30  # env-дефолт большой
    await _set(uow, SETTING_RAW_RETENTION, "2")  # UI: хранить только 2 дня
    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="A", at=now - 5 * _DAY))  # старше 2д
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="B", at=now))  # свежий
        await tx.session.flush()

    svc = TrafficRollupService(uow, settings)
    res = await svc.purge_old(now)
    assert res["purged_raw"] == 1  # удалён по UI-override (2д), а не по env (30д)
    async with uow.query() as tx:
        left = {r.client_id for r in (await tx.session.execute(select(m.TrafficSample))).scalars()}
    assert left == {"B"}


async def test__trim_oldest_raw_day__drops_oldest_day_keeps_last(uow, session_maker):
    """Size-cap trim срезает старейшие сутки сырья и никогда не трогает последние сутки."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550002")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="OLD", at=now - 10 * _DAY))
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="MID", at=now - 5 * _DAY))
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="NEW", at=now - 100))  # < суток
        tx.session.add(m.ServerMetric(server_id=srv.id, at=now - 10 * _DAY, cpu_pct=1.0))
        await tx.session.flush()

    async with uow.transaction() as tx:
        trimmed = await trim_oldest_raw_day(tx.session, now)
    assert trimmed == 2  # старейшие сутки traffic (OLD) + server_metric — по одной строке
    async with uow.query() as tx:
        left = {r.client_id for r in (await tx.session.execute(select(m.TrafficSample))).scalars()}
    assert "OLD" not in left and "NEW" in left  # старейшее срезано, последние сутки целы


async def test__metrics_disk_usage__reports_rows(uow, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79005550003")
        srv = await make_server(s, owner_id=owner.id)
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="A", at=time.time()))
        await tx.session.flush()

    async with uow.query() as tx:
        usage = await metrics_disk_usage(tx.session)
    assert usage["rows"]["traffic_samples"] == 1
    assert usage["totalBytes"] is None  # sqlite — размер неизвестен (size-cap только на Postgres)


async def _seed_metric_samples(uow, n: int) -> None:
    async with uow.transaction() as tx:
        for i in range(n):
            tx.session.add(m.MetricSample(name="vpnhub_test", labels="", at=float(i), value=1.0))
        await tx.session.flush()


async def _metric_count(uow) -> int:
    async with uow.query() as tx:
        return len(list((await tx.session.execute(select(m.MetricSample))).scalars()))


async def test__chunked_delete__removes_all_matching_across_batches(uow):
    await _seed_metric_samples(uow, 25)
    # at < 20 → 20 строк, пачками по 4 (несколько пачек)
    deleted = await chunked_delete(uow, m.MetricSample, m.MetricSample.at < 20, batch=4)
    assert deleted == 20
    assert await _metric_count(uow) == 5  # остались at 20..24


async def test__chunked_delete__max_batches_caps_one_run(uow):
    await _seed_metric_samples(uow, 10)
    # batch=2, max_batches=2 → не больше 4 строк за прогон, остальное добьёт следующий вызов
    deleted = await chunked_delete(uow, m.MetricSample, m.MetricSample.at < 10, batch=2, max_batches=2)
    assert deleted == 4
    assert await _metric_count(uow) == 6
