"""Финансовый учёт: accrual-арифметика по сегментам цены + FinanceService (история/расчёт)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.factories.orm import make_device, make_device_config, make_server, make_user, seed
from vpnhub.infra.db.orm import models as m
from vpnhub.services.finance import GIB, MICROS, FinanceService, _day_start, accrue_segment, accrued_by_currency
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


async def test__overview__daily_cost_series_and_prev_period(session_maker, uow, settings) -> None:
    now = time.time()
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880006")
        srv = await make_server(s, owner_id=owner.id, name="daily")
        s.add(
            m.ServerPrice(
                server_id=srv.id,
                amount_micros=round(100 * MICROS),
                currency="RUB",
                period="day",
                anchor_day=None,
                effective_from=now - 5 * DAY,
                effective_to=None,
            )
        )
        oid = owner.id

    rep = await FinanceService(uow, settings).overview(oid, now - 3 * DAY, now)

    # окно 3 дня × 100/день = 300; сумма посуточного ряда == итогу за окно
    assert rep["totals"]["costByCurrency"] == [{"currency": "RUB", "amount": 300.0}]
    series_sum = sum(x["amount"] for pt in rep["costSeries"] for x in pt["byCurrency"])
    assert series_sum == pytest.approx(300.0, rel=1e-6)
    assert all(pt["at"] % DAY == 0 for pt in rep["costSeries"])  # бакеты на суточной сетке UTC
    # прошлый период [now-6d, now-3d] пересекает цену только с now-5d → ровно 2 дня × 100 = 200
    assert rep["totals"]["prevCostByCurrency"] == [{"currency": "RUB", "amount": 200.0}]
    # ряд трафика есть и выровнен по той же сетке (данных нет → нули)
    assert len(rep["trafficSeries"]) == len(rep["costSeries"])
    assert all(pt["bytes"] == 0 for pt in rep["trafficSeries"])


async def test__usage_report__attributes_cost_by_traffic_share(session_maker, uow, settings) -> None:
    now = time.time()
    bucket = _day_start(now - 10 * DAY)  # суточный бакет внутри окна [now-30d, now]
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880007")
        srv = await make_server(s, owner_id=owner.id, name="srv-usage")
        s.add(
            m.ServerPrice(
                server_id=srv.id,
                amount_micros=round(300 * MICROS),
                currency="RUB",
                period="month",
                anchor_day=None,
                effective_from=now - 40 * DAY,
                effective_to=None,
            )
        )
        ua = await make_user(s, phone="+79008881001", name="Аня")
        ub = await make_user(s, phone="+79008881002", name="Боря")
        da = await make_device(s, user_id=ua.id, name="Аня-iPhone")
        db = await make_device(s, user_id=ub.id, name="Боря-ПК")
        ca = await make_device_config(s, device_id=da.id, server_id=srv.id, vpn_type="amnezia", client_id="pubA")
        cb = await make_device_config(s, device_id=db.id, server_id=srv.id, vpn_type="amnezia", client_id="pubB")
        for dc_id, client_id, rx in ((ca.id, "pubA", 6 * GIB), (cb.id, "pubB", 3 * GIB), (None, "ext-1", 1 * GIB)):
            s.add(
                m.TrafficDaily(
                    server_id=srv.id,
                    proto="awg",
                    client_id=client_id,
                    device_config_id=dc_id,
                    bucket=bucket,
                    rx=rx,
                    tx=0,
                )
            )
        oid, ua_id = owner.id, ua.id

    rep = await FinanceService(uow, settings).usage_report(oid, now - 30 * DAY, now)

    assert rep["totalUsedBytes"] == 10 * GIB
    assert rep["userCount"] == 2
    assert rep["deviceCount"] == 2
    top = rep["users"][0]  # сорт по трафику desc → Аня (6 ГиБ) первая
    assert top["userId"] == ua_id and top["name"] == "Аня"
    assert top["usedBytes"] == 6 * GIB and top["sharePct"] == 60.0 and top["deviceCount"] == 1
    assert rep["users"][1]["usedBytes"] == 3 * GIB and rep["users"][1]["sharePct"] == 30.0
    # external-клиент (без нашего конфига) — в «неучтённые», доля 10%
    assert rep["external"]["usedBytes"] == 1 * GIB and rep["external"]["sharePct"] == 10.0
    # себестоимость раскидана пропорционально трафику: Аня ≈ 2× Боря, external ≈ доля Бори/3-я часть
    ca_rub = top["costByCurrency"][0]["amount"]
    cb_rub = rep["users"][1]["costByCurrency"][0]["amount"]
    ext_rub = rep["external"]["costByCurrency"][0]["amount"]
    assert ca_rub == pytest.approx(2 * cb_rub, rel=1e-3)
    assert ext_rub == pytest.approx(cb_rub / 3, rel=1e-3)
    # доли суммируются в 1.0 → сумма приписанной стоимости == себестоимость сервера за окно (300₽/мес × 30 сут)
    expected = 300 * (30 * DAY) / (365.25 / 12 * DAY)
    assert ca_rub + cb_rub + ext_rub == pytest.approx(expected, abs=0.05)
