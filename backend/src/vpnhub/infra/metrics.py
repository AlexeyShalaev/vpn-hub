"""In-process реестр прикладных метрик панели + helper'ы инструментации.

Метрики объявляются модуль-уровнево ОДИН раз (иначе `Duplicated timeseries` при повторном
импорте) в дефолтном реестре prometheus-client — том же, что отдаёт `GET /metrics`. Это единый
источник правды: HTTP-middleware и обёртки джоб пишут сюда, а фоновой `metrics-tick` читает
текущие значения и снимает их в таблицу `metric_samples` (переживает рестарт процесса).

Точки инструментации (только реально существующие):
- HTTP-запросы (middleware в entrypoint) → `observe_http`.
- тики планировщиков (server-monitor/server-sync/backup-tick/...) → `record_scheduler_tick`.
- серверы по статусу и их latency (ServerService.run_tick) → `set_server_gauges`.
- ошибки provisioning по error_code → `set_provisioning_errors`.

НЕ путать с owner-трафиком (`traffic_samples`): здесь — здоровье самого инстанса для admin.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Mapping

from prometheus_client import Counter, Gauge, Histogram

# --- HTTP ------------------------------------------------------------------
http_requests_total = Counter(
    "vpnhub_http_requests_total",
    "Общее число HTTP-запросов к API панели",
    ["method", "path_group", "status"],
)
http_request_seconds = Histogram(
    "vpnhub_http_request_seconds",
    "Длительность обработки HTTP-запроса, сек",
    ["method", "path_group"],
)

# --- планировщики ----------------------------------------------------------
scheduler_tick_total = Counter(
    "vpnhub_scheduler_tick_total",
    "Число выполнений фоновой джобы",
    ["job"],
)
scheduler_tick_seconds = Histogram(
    "vpnhub_scheduler_tick_seconds",
    "Длительность выполнения фоновой джобы, сек",
    ["job"],
)
scheduler_tick_errors_total = Counter(
    "vpnhub_scheduler_tick_errors_total",
    "Число падений фоновой джобы",
    ["job"],
)

# --- серверы / provisioning / sync -----------------------------------------
servers_gauge = Gauge(
    "vpnhub_servers",
    "Число серверов по статусу",
    ["status"],
)
server_latency_ms = Gauge(
    "vpnhub_server_latency_ms",
    "Средняя latency онлайн-серверов, мс",
)
provisioning_errors = Gauge(
    "vpnhub_provisioning_errors",
    "Число протоколов серверов в состоянии error по коду ошибки",
    ["error_code"],
)
sync_seconds = Histogram(
    "vpnhub_sync_seconds",
    "Длительность одного sync-тика, сек",
)

_SERVER_STATUSES = ("online", "offline", "unknown")

# id (uuid hex / числа) в пути → шаблон, чтобы не взрывать кардинальность path_group
_HEX_ID = re.compile(r"^[0-9a-f]{8,}$")
_NUM_ID = re.compile(r"^\d+$")


def path_group(path: str) -> str:
    """Нормализовать путь до шаблона без id: `/api/v1/servers/abc123/traffic` → `/api/v1/servers/{id}/traffic`.

    Сегменты, похожие на идентификатор (hex длиной >=8 или число), заменяются на `{id}`.
    """
    parts = path.split("/")
    out = ["{id}" if (_HEX_ID.match(p) or _NUM_ID.match(p)) else p for p in parts]
    return "/".join(out) or "/"


def observe_http(method: str, path: str, status: int, seconds: float) -> None:
    """Записать один HTTP-запрос (вызывается из middleware)."""
    pg = path_group(path)
    http_requests_total.labels(method=method, path_group=pg, status=str(status)).inc()
    http_request_seconds.labels(method=method, path_group=pg).observe(seconds)


def record_scheduler_tick(job: str, seconds: float, *, error: bool) -> None:
    """Записать одно выполнение фоновой джобы."""
    scheduler_tick_total.labels(job=job).inc()
    scheduler_tick_seconds.labels(job=job).observe(seconds)
    if error:
        scheduler_tick_errors_total.labels(job=job).inc()


def instrument_job[T](job: str, fn: Callable[[], Awaitable[T]]) -> Callable[[], Awaitable[T]]:
    """Обернуть async job-функцию планировщика: писать tick-метрики (успех/падение/длительность).

    Ошибку пробрасываем — APScheduler залогирует её как обычно; метрика падения при этом снимется.
    """

    async def _wrapped() -> T:
        t0 = time.perf_counter()
        err = False
        try:
            return await fn()
        except Exception:
            err = True
            raise
        finally:
            record_scheduler_tick(job, time.perf_counter() - t0, error=err)

    return _wrapped


def set_server_gauges(counts: Mapping[str, int], avg_latency_ms: float | None) -> None:
    """Обновить гейджи серверов: число по каждому статусу + средняя latency онлайн-серверов."""
    for status in _SERVER_STATUSES:
        servers_gauge.labels(status=status).set(counts.get(status, 0))
    server_latency_ms.set(avg_latency_ms if avg_latency_ms is not None else 0.0)


def set_provisioning_errors(by_code: Mapping[str, int]) -> None:
    """Пересчитать гейдж ошибок provisioning по error_code (полностью замещая старые серии)."""
    provisioning_errors.clear()
    for code, n in by_code.items():
        provisioning_errors.labels(error_code=code or "unknown").set(n)


def read_gauge_samples() -> list[tuple[str, str, float]]:
    """Снять текущие значения серверных/provisioning-гейджей как (name, labels, value).

    Используется фоновым `metrics-tick` для записи в `metric_samples`. Формат labels — `k=v,k=v`.
    """
    out: list[tuple[str, str, float]] = []
    for metric in servers_gauge.collect():
        for s in metric.samples:
            status = s.labels.get("status", "unknown")
            out.append(("vpnhub_servers", f"status={status}", float(s.value)))
    for metric in server_latency_ms.collect():
        for s in metric.samples:
            out.append(("vpnhub_server_latency_ms", "", float(s.value)))
    for metric in provisioning_errors.collect():
        for s in metric.samples:
            code = s.labels.get("error_code", "unknown")
            out.append(("vpnhub_provisioning_errors", f"error_code={code}", float(s.value)))
    return out


def read_http_rps() -> float:
    """Суммарный счётчик HTTP-запросов (монотонный total) на текущий момент.

    `metrics-tick` пишет сам total; дельту/RPS считает уже overview по соседним точкам.
    """
    total = 0.0
    for metric in http_requests_total.collect():
        for s in metric.samples:
            if s.name == "vpnhub_http_requests_total":
                total += float(s.value)
    return total
