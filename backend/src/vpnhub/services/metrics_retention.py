"""Ретеншн метрик, настраиваемый из UI: по времени (дни хранения сырья) и по размеру диска (кап, ГБ).

Хранится в таблице `Setting` (runtime, без рестарта) с фолбэком на env-настройки. Читается purge-джобами
(traffic-rollup / server-metrics-rollup). Размер — только на Postgres (`pg_total_relation_size`); на
SQLite (тесты) размер неизвестен и size-cap не применяется (диск — прод-забота).
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text

from vpnhub.infra.db.orm import models as m

SETTING_RAW_RETENTION = "metrics_raw_retention_days"  # override дней хранения сырья (traffic+host); 0/пусто → env
SETTING_SIZE_CAP_GB = "metrics_size_cap_gb"  # лимит суммарного размера метрик, ГБ; 0 = без лимита

# все таблицы метрик (для отчёта использования)
_METRIC_TABLES = (
    "traffic_samples",
    "traffic_hourly",
    "traffic_daily",
    "traffic_peer_state",
    "traffic_usage",
    "server_metrics",
    "server_metrics_hourly",
)
_DAY = 86400.0


async def raw_retention_override(session: Any) -> int | None:
    """UI-override дней хранения сырья (>0) или None (использовать env-дефолт per-tier)."""
    row = await session.get(m.Setting, SETTING_RAW_RETENTION)
    if row and (row.value or "").strip().isdigit():
        n = int(row.value)
        return n if n > 0 else None
    return None


async def size_cap_bytes(session: Any) -> int:
    """Лимит суммарного размера метрик в байтах (0 = без лимита)."""
    row = await session.get(m.Setting, SETTING_SIZE_CAP_GB)
    try:
        gb = float(row.value) if row and row.value else 0.0
    except ValueError:
        gb = 0.0
    return int(gb * 1_000_000_000) if gb > 0 else 0


async def _pg_total_size(session: Any) -> dict[str, int] | None:
    """Размер каждой таблицы метрик (байт) через pg_total_relation_size; не Postgres → None."""
    values = ",".join(f"('{t}')" for t in _METRIC_TABLES)  # имена — константы, не пользовательский ввод
    sql = f"SELECT relname, pg_total_relation_size(relname::regclass) FROM (VALUES {values}) AS x(relname)"  # noqa: S608
    try:
        rows = (await session.execute(text(sql))).all()
    except Exception:
        return None
    return {r[0]: int(r[1] or 0) for r in rows}


async def metrics_disk_usage(session: Any) -> dict:
    """Отчёт: строки по каждой таблице метрик + размер (байт, только Postgres) + суммарный размер."""
    rows: dict[str, int] = {}
    for t in _METRIC_TABLES:
        rows[t] = int((await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar() or 0)  # noqa: S608
    sizes = await _pg_total_size(session)
    total = sum(sizes.values()) if sizes is not None else None
    return {"rows": rows, "sizeBytes": sizes, "totalBytes": total}


async def trim_oldest_raw_day(session: Any, now: float) -> int:
    """Удалить самые старые сутки сырья (traffic_samples + server_metrics), но всегда оставить последние сутки.

    Возвращает число удалённых строк. Один вызов срезает не больше суток на таблицу — при size-cap
    вызывается каждый почасовой прогон, размер сходится по мере autovacuum.
    """
    floor = now - _DAY  # последние сутки не трогаем
    trimmed = 0
    for model in (m.TrafficSample, m.ServerMetric):
        at_col = model.at
        oldest = (await session.execute(select(func.min(at_col)))).scalar_one_or_none()
        if oldest is None:
            continue
        slice_end = min(oldest + _DAY, floor)
        if slice_end <= oldest:
            continue
        res: Any = await session.execute(sa_delete(model).where(at_col < slice_end))
        trimmed += int(res.rowcount or 0)
    return trimmed


async def enforce_size_cap(uow: Any, settings: Any) -> dict:
    """Если суммарный размер метрик превысил лимит — срезать старейшие сутки сырья (best-effort).

    Работает только на Postgres (размер известен). Никогда не удаляет последние сутки.
    """
    async with uow.query() as tx:
        cap = await size_cap_bytes(tx.session)
        if cap <= 0:
            return {"trimmed": 0, "capped": False}
        total = (await metrics_disk_usage(tx.session))["totalBytes"]
    if total is None or total <= cap:
        return {"trimmed": 0, "capped": False}
    async with uow.transaction() as tx:
        trimmed = await trim_oldest_raw_day(tx.session, time.time())
    return {"trimmed": trimmed, "capped": True}
