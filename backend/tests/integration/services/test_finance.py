"""Финансовый учёт: accrual-арифметика по сегментам цены + FinanceService (история/расчёт)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.factories.orm import make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.services.finance import GIB, MICROS, FinanceService, accrue_segment, accrued_by_currency
from vpnhub.services.limits import period_start

pytestmark = pytest.mark.integration

DAY = 86400.0


def _seg(amount: float, currency: str, period: str, frm: float, to: float | None):
    return SimpleNamespace(
        amount_micros=round(amount * MICROS), currency=currency, period=period, effective_from=frm, effective_to=to
    )


def test__accrue_segment__exact_periods() -> None:
    # 30/день за 2 дня = 60
    assert accrue_segment(30 * MICROS, "day", 0, 2 * DAY, 0, 2 * DAY) == pytest.approx(60)
    # 1/минуту за час = 60
    assert accrue_segment(1 * MICROS, "minute", 0, 3600, 0, 3600) == pytest.approx(60)
    # вне пересечения — 0
    assert accrue_segment(30 * MICROS, "day", 0, DAY, 5 * DAY, 6 * DAY) == 0.0
    # частичное пересечение клиппится
    assert accrue_segment(30 * MICROS, "day", 0, 10 * DAY, DAY, 3 * DAY) == pytest.approx(60)  # ровно 2 дня окна


def test__accrued_by_currency__price_change_segments_and_open() -> None:
    now = 2 * DAY
    segs = [
        _seg(10, "RUB", "day", 0, DAY),  # первый день по 10
        _seg(20, "RUB", "day", DAY, None),  # со второго дня по 20, открытый → до now
    ]
    out = accrued_by_currency(segs, 0, now, now)
    assert out["RUB"] == pytest.approx(30)  # 10 + 20


def test__accrued_by_currency__separate_per_currency() -> None:
    now = DAY
    segs = [_seg(10, "RUB", "day", 0, None), _seg(3, "USD", "day", 0, None)]
    out = accrued_by_currency(segs, 0, now, now)
    assert out == {"RUB": pytest.approx(10), "USD": pytest.approx(3)}  # НЕ конвертируем — раздельно


async def test__set_price__keeps_history_segments(session_maker, uow, settings) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880001")
        srv = await make_server(s, owner_id=owner.id, name="srv-price")
        sid, oid = srv.id, owner.id
    fin = FinanceService(uow, settings)

    await fin.set_price(oid, sid, 10, "RUB", "day", None)
    await fin.set_price(oid, sid, 20, "RUB", "day", None)  # смена → новый сегмент, старый закрыт
    await fin.set_price(oid, sid, 20, "RUB", "day", None)  # без изменений → no-op

    async with uow.query() as tx:
        segs = list((await tx.session.execute(select(m.ServerPrice).where(m.ServerPrice.server_id == sid))).scalars())
    assert len(segs) == 2  # два сегмента истории
    assert sum(1 for x in segs if x.effective_to is None) == 1  # ровно один открытый
    price = await fin.get_price(oid, sid)
    assert price["amount"] == pytest.approx(20) and price["currency"] == "RUB" and price["period"] == "day"


async def test__set_price__none_closes_segment(session_maker, uow, settings) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880002")
        srv = await make_server(s, owner_id=owner.id, name="srv-free")
        sid, oid = srv.id, owner.id
    fin = FinanceService(uow, settings)
    await fin.set_price(oid, sid, 5, "USD", "month", 15)
    assert await fin.set_price(oid, sid, None, "USD", "month", None) is None  # закрыли
    assert await fin.get_price(oid, sid) is None  # больше нет открытого сегмента


async def test__set_price__rejects_non_finite_and_huge(session_maker, uow, settings) -> None:
    from vpnhub.core.errors import BadRequest

    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880004")
        srv = await make_server(s, owner_id=owner.id, name="srv-bad")
        sid, oid = srv.id, owner.id
    fin = FinanceService(uow, settings)
    for bad in (float("nan"), float("inf"), float("-inf"), 1e13):
        with pytest.raises(BadRequest):  # не 500 (round(nan/inf) / переполнение BigInteger)
            await fin.set_price(oid, sid, bad, "RUB", "day", None)
    assert await fin.get_price(oid, sid) is None  # кривой ввод не создал и не закрыл сегмент


async def test__cost_report__sums_per_currency(session_maker, uow, settings) -> None:
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880003")
        a = await make_server(s, owner_id=owner.id, name="A")
        b = await make_server(s, owner_id=owner.id, name="B")
        aid, bid, oid = a.id, b.id, owner.id
    fin = FinanceService(uow, settings)
    await fin.set_price(oid, aid, 100, "RUB", "day", None)
    await fin.set_price(oid, bid, 2, "USD", "day", None)

    rep = await fin.cost_report(oid, 0, 10**12)  # огромный диапазон, но end клиппится к now
    curs = {t["currency"] for t in rep["totals"]}
    assert curs == {"RUB", "USD"}  # обе валюты в сводке, раздельно
    assert len(rep["servers"]) == 2


async def test__overview__combines_cost_traffic_and_unit_economics(session_maker, uow, settings) -> None:
    now = time.time()
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880005")
        srv = await make_server(s, owner_id=owner.id, name="MSK", status="online")
        srv.location = "Москва"
        srv.provider = "FirstByte"
        srv.provider_metadata = {"providerPlan": "MSK-highmem-KVM-SSD-2"}
        srv.bandwidth_quota_bytes = 10 * GIB
        srv.billing_day = None
        s.add(
            m.ServerPrice(
                server_id=srv.id,
                amount_micros=round(300 * MICROS),
                currency="RUB",
                period="month",
                anchor_day=None,
                effective_from=now - DAY,
                effective_to=None,
            )
        )
        s.add(
            m.TrafficUsage(
                server_id=srv.id,
                user_id=None,
                period_start=period_start(now, None),
                rx_bytes=1 * GIB,
                tx_bytes=2 * GIB,
                updated_at=now,
            )
        )
        sid, oid = srv.id, owner.id

    rep = await FinanceService(uow, settings).overview(oid, now - DAY, now)

    assert rep["totals"]["servers"] == 1
    assert rep["totals"]["pricedServers"] == 1
    assert rep["totals"]["quotaServers"] == 1
    assert rep["totals"]["trafficQuotaBytes"] == 10 * GIB
    assert rep["totals"]["trafficUsedBytes"] == 3 * GIB
    assert rep["totals"]["trafficUtilizationPct"] == 30.0
    assert rep["totals"]["costByCurrency"][0]["currency"] == "RUB"
    assert rep["totals"]["costByCurrency"][0]["amount"] > 0
    assert rep["totals"]["unitCosts"][0]["saleGuide"][1]["marginPct"] == 50

    row = rep["servers"][0]
    assert row["serverId"] == sid
    assert row["provider"] == "FirstByte"
    assert row["providerPlan"] == "MSK-highmem-KVM-SSD-2"
    assert row["trafficUtilizationPct"] == 30.0
