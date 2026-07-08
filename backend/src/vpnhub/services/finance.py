"""Финансовый учёт стоимости серверов.

Цена сервера задаётся в валюте за период (minute|day|month) и МЕНЯЕТСЯ во времени. Поэтому храним
ИСТОРИЮ сегментов цены (ServerPrice, effective_from/to): при смене цены закрываем текущий сегмент и
открываем новый. Расход считается **accrual по сегментам** — для каждого сегмента, действовавшего в
запрошенном диапазоне: `цена × (длительность_пересечения / длительность_периода)`. Так смена цены и
частичные периоды учитываются корректно, а не «текущая цена × всё время».

Валюты НЕ конвертируем (нет курса) — суммируем и показываем раздельно по каждой валюте.
"""

from __future__ import annotations

import math
import time
from typing import Any

from sqlalchemy import select

from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.limits import period_start, period_usage

MICROS = 1_000_000  # цена хранится в микроединицах валюты (сумма × 1e6) — точность без float
PERIODS = ("minute", "day", "month")
# длительность периода в секундах; месяц — средний (365.25/12 суток), чтобы accrual был ровным
PERIOD_SECONDS: dict[str, float] = {"minute": 60.0, "day": 86400.0, "month": 365.25 / 12 * 86400}
GIB = 1024**3
SALE_MARGIN_PCTS = (20, 50, 100)


def accrue_segment(
    amount_micros: int, period: str, seg_from: float, seg_to: float, q_start: float, q_end: float
) -> float:
    """Расход по ОДНОМУ сегменту цены в пересечении с [q_start, q_end], в единицах валюты (float).

    = (amount) × (длительность_пересечения / длительность_периода). Вне пересечения → 0.
    """
    lo = max(seg_from, q_start)
    hi = min(seg_to, q_end)
    if hi <= lo:
        return 0.0
    per = PERIOD_SECONDS.get(period, PERIOD_SECONDS["month"])
    return (amount_micros / MICROS) * ((hi - lo) / per)


def accrued_by_currency(segments: list[Any], q_start: float, q_end: float, now: float) -> dict[str, float]:
    """Суммарный accrual-расход по сегментам в [q_start, q_end], РАЗДЕЛЬНО по валютам.

    Открытый сегмент (effective_to=None) трактуется как действующий до `now`.
    """
    out: dict[str, float] = {}
    for s in segments:
        seg_to = s.effective_to if s.effective_to is not None else now
        cost = accrue_segment(s.amount_micros, s.period, s.effective_from, seg_to, q_start, q_end)
        if cost:
            out[s.currency] = out.get(s.currency, 0.0) + cost
    return out


def _price_dict(seg: m.ServerPrice | None) -> dict | None:
    if seg is None:
        return None
    return {
        "amount": seg.amount_micros / MICROS,
        "currency": seg.currency,
        "period": seg.period,
        "anchorDay": seg.anchor_day,
        "since": seg.effective_from,
    }


def _norm_currency(cur: str) -> str:
    cur = (cur or "").strip().upper()
    if not (3 <= len(cur) <= 8 and cur.isalpha()):
        raise BadRequest("Валюта — 3–8 латинских букв (напр. RUB, USD, EUR)")
    return cur


def _money_items(values: dict[str, float]) -> list[dict]:
    return [{"currency": c, "amount": round(v, 2)} for c, v in sorted(values.items()) if v]


def _pct(part: int, total: int | None) -> float | None:
    if not total or total <= 0:
        return None
    return round(part / total * 100, 1)


def _unit_amount(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 4 if abs(value) < 1 else 2)


def _unit_costs(
    costs: dict[str, float],
    used_bytes: int,
    quota_bytes: int | None,
    capacity_costs: dict[str, float] | None = None,
) -> list[dict]:
    used_gib = used_bytes / GIB if used_bytes > 0 else None
    quota_gib = quota_bytes / GIB if quota_bytes and quota_bytes > 0 else None
    capacity = capacity_costs if capacity_costs is not None else costs
    out: list[dict] = []
    for currency in sorted(set(costs) | set(capacity)):
        amount = costs.get(currency, 0.0)
        capacity_amount = capacity.get(currency, 0.0)
        per_used = amount / used_gib if used_gib else None
        per_quota = capacity_amount / quota_gib if quota_gib and capacity_amount else None
        basis = per_quota if per_quota is not None else per_used
        out.append(
            {
                "currency": currency,
                "costPerUsedGb": _unit_amount(per_used),
                "costPerQuotaGb": _unit_amount(per_quota),
                "saleGuide": [
                    {
                        "marginPct": margin,
                        "pricePerGb": _unit_amount(basis * (1 + margin / 100)) if basis is not None else None,
                        "pricePerTb": _unit_amount(basis * 1024 * (1 + margin / 100)) if basis is not None else None,
                        "basis": "quota" if per_quota is not None else "used",
                    }
                    for margin in SALE_MARGIN_PCTS
                ],
            }
        )
    return out


class FinanceService:
    def __init__(self, uow: Uow, settings: Any) -> None:
        self.uow = uow
        self.settings = settings

    async def _owned(self, tx: UowTransaction, owner_id: str, sid: str) -> m.Server:
        s: m.Server | None = await tx.servers.get(sid)
        if not s or s.owner_user_id != owner_id:
            raise NotFound("Сервер не найден")
        return s

    @staticmethod
    async def _open_segment(tx: UowTransaction, sid: str) -> m.ServerPrice | None:
        return (
            (
                await tx.session.execute(
                    select(m.ServerPrice)
                    .where(m.ServerPrice.server_id == sid, m.ServerPrice.effective_to.is_(None))
                    .order_by(m.ServerPrice.effective_from.desc())
                )
            )
            .scalars()
            .first()
        )

    async def get_price(self, owner_id: str, sid: str) -> dict | None:
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
            return _price_dict(await self._open_segment(tx, sid))

    async def set_price(
        self, owner_id: str, sid: str, amount: float | None, currency: str, period: str, anchor_day: int | None
    ) -> dict | None:
        """Задать/сменить цену. amount None/≤0 → закрыть текущий сегмент (сервер бесплатен).

        При реальном изменении: закрываем текущий сегмент (effective_to=now) и открываем новый — так
        сохраняется история для accrual-расчёта. Без изменений — no-op.
        """
        now = time.time()
        # не-конечное (NaN/±Inf) не должно долетать до round()/BigInteger (иначе 500); отрицательное
        # бесконечное иначе тихо закрыло бы сегмент. Верхняя граница — чтобы micros влез в BigInteger.
        if amount is not None and not math.isfinite(amount):
            raise BadRequest("Цена должна быть конечным числом")
        if amount is not None and amount > 1_000_000_000_000:  # 1e12 → micros 1e18 < bigint max
            raise BadRequest("Слишком большая цена")
        async with self.uow.transaction() as tx:
            await self._owned(tx, owner_id, sid)
            cur = await self._open_segment(tx, sid)

            if amount is None or amount <= 0:
                if cur is not None:
                    cur.effective_to = now
                await tx.session.flush()
                return None

            if period not in PERIODS:
                raise BadRequest("Период — minute | day | month")
            currency = _norm_currency(currency)
            anchor = anchor_day if (period == "month" and anchor_day and 1 <= anchor_day <= 31) else None
            micros = round(amount * MICROS)

            # без изменений — не плодим сегменты
            if (
                cur is not None
                and cur.amount_micros == micros
                and cur.currency == currency
                and cur.period == period
                and cur.anchor_day == anchor
            ):
                return _price_dict(cur)

            if cur is not None:
                cur.effective_to = now
            seg = m.ServerPrice(
                server_id=sid,
                amount_micros=micros,
                currency=currency,
                period=period,
                anchor_day=anchor,
                effective_from=now,
                effective_to=None,
            )
            tx.session.add(seg)
            await tx.session.flush()
            return _price_dict(seg)

    async def _segments(self, tx: UowTransaction, sid: str) -> list[m.ServerPrice]:
        return list(
            (await tx.session.execute(select(m.ServerPrice).where(m.ServerPrice.server_id == sid))).scalars().all()
        )

    async def server_cost(self, owner_id: str, sid: str, start: float, end: float) -> dict:
        now = time.time()
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
            segs = await self._segments(tx, sid)
            price = _price_dict(await self._open_segment(tx, sid))
        by_cur = accrued_by_currency(segs, start, min(end, now), now)
        return {
            "serverId": sid,
            "start": start,
            "end": end,
            "price": price,
            "byCurrency": [{"currency": c, "amount": round(v, 2)} for c, v in sorted(by_cur.items())],
        }

    async def cost_report(self, owner_id: str, start: float, end: float) -> dict:
        """Сводный отчёт затрат по всем серверам владельца за [start, end], раздельно по валютам."""
        now = time.time()
        end = min(end, now)
        totals: dict[str, float] = {}
        servers_out: list[dict] = []
        async with self.uow.query() as tx:
            servers = await tx.servers.for_owner(owner_id)
            for s in servers:
                segs = await self._segments(tx, s.id)
                by_cur = accrued_by_currency(segs, start, end, now)
                price = _price_dict(await self._open_segment(tx, s.id))
                for c, v in by_cur.items():
                    totals[c] = totals.get(c, 0.0) + v
                if by_cur or price:
                    servers_out.append(
                        {
                            "serverId": s.id,
                            "name": s.name,
                            "price": price,
                            "byCurrency": [{"currency": c, "amount": round(v, 2)} for c, v in sorted(by_cur.items())],
                        }
                    )
        servers_out.sort(key=lambda x: x["name"].lower())
        return {
            "start": start,
            "end": end,
            "totals": [{"currency": c, "amount": round(v, 2)} for c, v in sorted(totals.items())],
            "servers": servers_out,
        }

    async def overview(self, owner_id: str, start: float, end: float) -> dict:
        """Финансовый overview владельца: cost + текущая утилизация трафика + unit economics.

        Расход считается за выбранный диапазон [start, end]. Трафик/квоты — за текущий
        биллинг-период каждого сервера, потому что квота сбрасывается по server.billing_day.
        Валюты не конвертируем, поэтому себестоимость и сценарии продажи идут отдельно по валютам.
        """
        now = time.time()
        end = min(end, now)
        if end <= start:
            raise BadRequest("Некорректный период отчёта")

        totals_cost: dict[str, float] = {}
        quota_cost: dict[str, float] = {}
        total_quota_bytes = 0
        total_used_bytes = 0
        priced = 0
        quota_servers = 0
        servers_out: list[dict] = []

        async with self.uow.query() as tx:
            servers = await tx.servers.for_owner(owner_id)
            for s in servers:
                segs = await self._segments(tx, s.id)
                price = _price_dict(await self._open_segment(tx, s.id))
                if price is not None:
                    priced += 1
                by_cur = accrued_by_currency(segs, start, end, now)
                for currency, amount in by_cur.items():
                    totals_cost[currency] = totals_cost.get(currency, 0.0) + amount

                billing_start = period_start(now, s.billing_day)
                rx, txb = await period_usage(tx.session, s.id, None, billing_start)
                used = int(rx) + int(txb)
                quota = s.bandwidth_quota_bytes
                if quota and quota > 0:
                    quota_servers += 1
                    total_quota_bytes += int(quota)
                    for currency, amount in by_cur.items():
                        quota_cost[currency] = quota_cost.get(currency, 0.0) + amount
                total_used_bytes += used

                metadata = s.provider_metadata if isinstance(s.provider_metadata, dict) else {}
                provider_plan = metadata.get("providerPlan")
                servers_out.append(
                    {
                        "serverId": s.id,
                        "name": s.name,
                        "provider": s.provider,
                        "providerPlan": provider_plan if isinstance(provider_plan, str) else None,
                        "location": s.location,
                        "status": s.status,
                        "price": price,
                        "costByCurrency": _money_items(by_cur),
                        "trafficQuotaBytes": quota,
                        "trafficUsedBytes": used,
                        "trafficUtilizationPct": _pct(used, quota),
                        "billingDay": s.billing_day,
                        "billingPeriodStart": billing_start,
                        "unitCosts": _unit_costs(by_cur, used, quota),
                    }
                )

        servers_out.sort(
            key=lambda row: (
                -(row["trafficUtilizationPct"] or -1),
                row["name"].lower(),
            )
        )
        return {
            "start": start,
            "end": end,
            "totals": {
                "servers": len(servers_out),
                "pricedServers": priced,
                "quotaServers": quota_servers,
                "trafficQuotaBytes": total_quota_bytes or None,
                "trafficUsedBytes": total_used_bytes,
                "trafficUtilizationPct": _pct(total_used_bytes, total_quota_bytes),
                "costByCurrency": _money_items(totals_cost),
                "unitCosts": _unit_costs(totals_cost, total_used_bytes, total_quota_bytes or None, quota_cost),
            },
            "servers": servers_out,
        }
