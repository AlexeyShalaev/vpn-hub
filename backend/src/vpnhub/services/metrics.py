"""Admin-дашборд здоровья инстанса панели: скрейп in-process метрик в PG + агрегация для UI.

Речь о здоровье САМОГО инстанса для роли admin (HTTP-нагрузка, тики планировщиков, серверы
online/offline и их latency, ошибки provisioning), а НЕ о VPN-трафике клиентов (тот — owner,
`traffic_samples` + `TrafficService`). Единый механизм хранения: фоновой `scrape_tick` снимает
текущие значения из реестра prometheus-client (`infra/metrics.py`) и из БД и дописывает строки
в `metric_samples` — так история переживает рестарт процесса (реестр живёт только в памяти).
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from vpnhub.api.config import Settings
from vpnhub.infra import metrics as mx
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)

# whitelist периодов дашборда → длительность в секундах (тот же словарь, что в traffic.py)
_PERIODS: dict[str, int] = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
_DEFAULT_PERIOD = "24h"

# гейджи, чьё последнее значение показываем в «сводке сейчас»
_SERVER_SERIES = "vpnhub_servers"
_HTTP_TOTAL_SERIES = "vpnhub_http_requests_total"


class MetricsService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def scrape_tick(self) -> int:
        """Снять текущие значения метрик и дописать сэмплы в metric_samples (одна транзакция).

        Пишем: серверные/provisioning-гейджи (из реестра, куда их кладёт ServerService.run_tick)
        и монотонный HTTP-total (дельту/RPS считает overview по соседним точкам). Число серверов
        по статусу читаем ещё и напрямую из БД — на случай, если монитор ещё не тикал.
        """
        now = time.time()
        rows: list[tuple[str, str, float]] = list(mx.read_gauge_samples())
        rows.append((_HTTP_TOTAL_SERIES, "", mx.read_http_rps()))
        # число серверов по статусу — из БД (авторитетно; гейдж мог не заполниться до первого монитора)
        async with self.uow.query() as tx:
            db_counts = await self._server_counts(tx)
        for status, n in db_counts.items():
            rows = [r for r in rows if not (r[0] == _SERVER_SERIES and r[1] == f"status={status}")]
            rows.append((_SERVER_SERIES, f"status={status}", float(n)))
        async with self.uow.transaction() as tx:
            for name, labels, value in rows:
                tx.session.add(m.MetricSample(name=name, labels=labels, at=now, value=value))
            await tx.session.flush()
        return len(rows)

    async def _server_counts(self, tx: Any) -> dict[str, int]:
        result = await tx.session.execute(select(m.Server.status, func.count()).group_by(m.Server.status))
        counts = {"online": 0, "offline": 0, "unknown": 0}
        for status, n in result.all():
            counts[status] = int(n)
        return counts

    async def overview(self, period: str = _DEFAULT_PERIOD) -> dict:
        """Временные ряды метрик за период + «сводка сейчас» (последние значения)."""
        window = _PERIODS.get(period, _PERIODS[_DEFAULT_PERIOD])
        now = time.time()
        since = now - window
        async with self.uow.query() as tx:
            samples = list(
                (
                    await tx.session.execute(
                        select(m.MetricSample).where(m.MetricSample.at >= since).order_by(m.MetricSample.at.asc())
                    )
                )
                .scalars()
                .all()
            )

        # серия = (name, labels) → упорядоченные точки
        series: dict[tuple[str, str], list[dict[str, float]]] = {}
        for s in samples:
            series.setdefault((s.name, s.labels), []).append({"at": s.at, "value": s.value})

        series_out = [{"name": name, "labels": labels, "points": points} for (name, labels), points in series.items()]

        # сводка сейчас: последние значения серверных серий + текущий HTTP-total
        server_now = {"online": 0.0, "offline": 0.0, "unknown": 0.0}
        for (name, labels), points in series.items():
            if name == _SERVER_SERIES and labels.startswith("status="):
                server_now[labels.split("=", 1)[1]] = points[-1]["value"]
        http_now = 0.0
        for (name, _labels), points in series.items():
            if name == _HTTP_TOTAL_SERIES:
                http_now = points[-1]["value"]

        return {
            "period": period if period in _PERIODS else _DEFAULT_PERIOD,
            "series": series_out,
            "servers": server_now,
            "httpTotal": http_now,
        }

    async def purge_old(self) -> int:
        """Удалить сэмплы старше `metrics_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.metrics_retention_days * 86400
        async with self.uow.transaction() as tx:
            res: Any = await tx.session.execute(sa_delete(m.MetricSample).where(m.MetricSample.at < cutoff))
            return int(res.rowcount or 0)
