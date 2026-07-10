"""Ярусные rollup-агрегаты трафика: сырьё → hourly → daily + ретеншн (фоновая джоба).

Свежие периоды дашборд читает из сырья `traffic_samples` (детально, но дорого по диску), а старые —
из почасовых/посуточных агрегатов (на порядки меньше строк). Джоба `run_tick` раз в час строго:
hourly → daily → purge.

Идемпотентность — «пересчёт хвоста delete+insert» с двусторонним клампом:
    recompute_from = max(MAX(bucket) в ярусе, bucket_start(MIN(at) в источнике))
Верхний член (watermark) двигает окно вперёд; нижний (oldest в источнике) НЕ даёт пересчитать
бакеты, чьё сырьё уже удалено ретеншном (иначе delete+insert занулил бы историю). Текущий
незавершённый бакет включается (свежие графики) и пересчитывается следующим прогоном.

Бакетирование только в Python (`bucket_start`) — исключает расхождение округления PG/SQLite.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from vpnhub.api.config import Settings
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow
from vpnhub.services.metrics_retention import enforce_size_cap, raw_retention_override
from vpnhub.services.traffic import effective_online_window

log = structlog.get_logger(__name__)

_HOUR = 3600
_DAY = 86400


def bucket_start(at: float, size: int) -> int:
    """Начало бакета UTC-сетки: `int(at) - int(at) % size` (портабельно, без SQL-округления)."""
    ts = int(at)
    return ts - ts % size


def recompute_from(watermark: int | None, oldest_source: float | None, size: int) -> int | None:
    """Нижняя граница «пересчёта хвоста» delete+insert: `max(watermark, bucket_start(oldest))`.

    Двусторонний кламп: watermark двигает окно вперёд, oldest_source не даёт пересчитать бакеты,
    чьё сырьё уже удалено ретеншном (иначе delete+insert занулил бы историю). Источник пуст
    (`oldest_source is None`) → None (пересчитывать нечего). Общая для всех ярусных rollup-ов.
    """
    if oldest_source is None:
        return None
    return max(watermark or 0, bucket_start(oldest_source, size))


def _sample_online(online: bool | None, last_handshake: float | None, at: float, window: int) -> bool:
    """Считать ли сырой сэмпл онлайном: флаг движка (xray/hysteria) или свежесть handshake (wg)."""
    if online is not None:
        return bool(online)
    if last_handshake is not None:
        return (at - last_handshake) < window
    return False


@dataclass
class _Agg:
    """Накопитель одного бакета (server, proto, client)."""

    rx: int = 0
    tx: int = 0
    samples_total: int = 0
    samples_online: int = 0
    last_handshake: float | None = None
    device_config_id: str | None = None
    ext_name: str | None = None

    def merge_meta(self, device_config_id: str | None, ext_name: str | None, last_handshake: float | None) -> None:
        if device_config_id:
            self.device_config_id = device_config_id
        if ext_name:
            self.ext_name = ext_name
        if last_handshake is not None and (self.last_handshake is None or last_handshake > self.last_handshake):
            self.last_handshake = last_handshake


_Key = tuple[str, str, str, int]  # (server_id, proto, client_id, bucket)


def aggregate_samples(rows: Iterable[Any], size: int, window: int) -> dict[_Key, _Agg]:
    """Свернуть сырые сэмплы в бакеты `size` (сумма дельт, счётчики online/total, max handshake)."""
    out: dict[_Key, _Agg] = {}
    for r in rows:
        bucket = bucket_start(r.at, size)
        key = (r.server_id, r.proto, r.client_id, bucket)
        agg = out.get(key)
        if agg is None:
            agg = _Agg()
            out[key] = agg
        agg.rx += r.rx_delta
        agg.tx += r.tx_delta
        agg.samples_total += 1
        if _sample_online(r.online, r.last_handshake, r.at, window):
            agg.samples_online += 1
        agg.merge_meta(r.device_config_id, r.ext_name, r.last_handshake)
    return out


def aggregate_rollups(rows: Iterable[Any], size: int) -> dict[_Key, _Agg]:
    """Свернуть агрегаты нижнего яруса (hourly) в бакеты `size` (суммы rx/tx/счётчиков, max handshake)."""
    out: dict[_Key, _Agg] = {}
    for r in rows:
        bucket = bucket_start(r.bucket, size)
        key = (r.server_id, r.proto, r.client_id, bucket)
        agg = out.get(key)
        if agg is None:
            agg = _Agg()
            out[key] = agg
        agg.rx += r.rx
        agg.tx += r.tx
        agg.samples_total += r.samples_total
        agg.samples_online += r.samples_online
        agg.merge_meta(r.device_config_id, r.ext_name, r.last_handshake)
    return out


class TrafficRollupService:
    """Досчитывает hourly/daily агрегаты и чистит просроченные ярусы (фоновая джоба run_tick)."""

    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def run_tick(self) -> dict[str, int]:
        """Один прогон: hourly → daily → purge (строгий порядок). Возвращает счётчики строк."""
        import time  # noqa: PLC0415 — локально, чтобы не тянуть в чистые функции модуля

        now = time.time()
        hourly = await self.rollup_hourly(now)
        daily = await self.rollup_daily(now)
        purged = await self.purge_old(now)
        # диск-кап метрик (UI-настройка): срезаем старейшее сырьё, если суммарный размер превышен
        capped = await enforce_size_cap(self.uow, self.settings)
        result = {"hourly": hourly, "daily": daily, **purged, "size_trimmed": capped["trimmed"]}
        log.info("traffic_rollup_tick", **result)
        return result

    async def rollup_hourly(self, now: float) -> int:
        """Досчитать почасовые агрегаты из сырья (пересчёт хвоста; идемпотентно)."""
        window = effective_online_window(self.settings)
        async with self.uow.transaction() as tx:
            watermark = (
                await tx.session.execute(select(func.max(m.TrafficHourly.bucket)))
            ).scalar_one_or_none()
            oldest_at = (await tx.session.execute(select(func.min(m.TrafficSample.at)))).scalar_one_or_none()
            rf = recompute_from(watermark, oldest_at, _HOUR)
            if rf is None:
                return 0  # сырья нет — нечего сворачивать
            await tx.session.execute(sa_delete(m.TrafficHourly).where(m.TrafficHourly.bucket >= rf))
            rows = (
                await tx.session.execute(
                    select(
                        m.TrafficSample.server_id,
                        m.TrafficSample.proto,
                        m.TrafficSample.client_id,
                        m.TrafficSample.device_config_id,
                        m.TrafficSample.ext_name,
                        m.TrafficSample.at,
                        m.TrafficSample.rx_delta,
                        m.TrafficSample.tx_delta,
                        m.TrafficSample.online,
                        m.TrafficSample.last_handshake,
                    ).where(
                        m.TrafficSample.at >= rf,
                        m.TrafficSample.client_id.isnot(None),
                    )
                )
            ).all()
            aggs = aggregate_samples(rows, _HOUR, window)
            await self._insert(tx, m.TrafficHourly, aggs)
            return len(aggs)

    async def rollup_daily(self, now: float) -> int:
        """Досчитать посуточные агрегаты из почасовых (пересчёт хвоста; идемпотентно)."""
        async with self.uow.transaction() as tx:
            watermark = (await tx.session.execute(select(func.max(m.TrafficDaily.bucket)))).scalar_one_or_none()
            oldest_bucket = (
                await tx.session.execute(select(func.min(m.TrafficHourly.bucket)))
            ).scalar_one_or_none()
            rf = recompute_from(watermark, oldest_bucket, _DAY)
            if rf is None:
                return 0
            await tx.session.execute(sa_delete(m.TrafficDaily).where(m.TrafficDaily.bucket >= rf))
            rows = (
                (await tx.session.execute(select(m.TrafficHourly).where(m.TrafficHourly.bucket >= rf)))
                .scalars()
                .all()
            )
            aggs = aggregate_rollups(rows, _DAY)
            await self._insert(tx, m.TrafficDaily, aggs)
            return len(aggs)

    @staticmethod
    async def _insert(tx: Any, model: Any, aggs: dict[_Key, _Agg]) -> None:
        """Массовая вставка агрегатов яруса (core insert; bucket уже вычислен в Python)."""
        if not aggs:
            return
        await tx.session.execute(
            model.__table__.insert(),
            [
                {
                    "id": uuid.uuid4().hex[:16],
                    "server_id": server_id,
                    "proto": proto,
                    "client_id": client_id,
                    "bucket": bucket,
                    "device_config_id": agg.device_config_id,
                    "ext_name": agg.ext_name,
                    "rx": agg.rx,
                    "tx": agg.tx,
                    "samples_total": agg.samples_total,
                    "samples_online": agg.samples_online,
                    "last_handshake": agg.last_handshake,
                }
                for (server_id, proto, client_id, bucket), agg in aggs.items()
            ],
        )

    async def purge_old(self, now: float) -> dict[str, int]:
        """Удалить просроченное по трём ярусам. daily_retention_days=0 → daily хранится вечно.

        Дни хранения сырья берутся из UI-override (`raw_retention_override`), иначе из env.
        """
        hourly_cutoff = now - self.settings.traffic_hourly_retention_days * _DAY
        async with self.uow.transaction() as tx:
            raw_days = await raw_retention_override(tx.session) or self.settings.traffic_raw_retention_days
            raw_cutoff = now - raw_days * _DAY
            raw: Any = await tx.session.execute(sa_delete(m.TrafficSample).where(m.TrafficSample.at < raw_cutoff))
            hourly: Any = await tx.session.execute(
                sa_delete(m.TrafficHourly).where(m.TrafficHourly.bucket < hourly_cutoff)
            )
            daily_n = 0
            if self.settings.traffic_daily_retention_days > 0:
                daily_cutoff = now - self.settings.traffic_daily_retention_days * _DAY
                daily: Any = await tx.session.execute(
                    sa_delete(m.TrafficDaily).where(m.TrafficDaily.bucket < daily_cutoff)
                )
                daily_n = int(daily.rowcount or 0)
        return {
            "purged_raw": int(raw.rowcount or 0),
            "purged_hourly": int(hourly.rowcount or 0),
            "purged_daily": daily_n,
        }
