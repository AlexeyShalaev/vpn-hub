"""Per-server мониторинг ресурсов хоста (owner): сбор по SSH + хранение + агрегация для UI.

Сбор врезан в monitor-тик (`ServerService.run_tick`) строго best-effort: отдельная короткая
SSH-сессия к онлайн-серверу гоняет `HOST_METRICS_CMD` (один блок KEY=VALUE), парсит его чистой
функцией `parse_host_metrics` (см. infra/hostmetrics — без IO) и пишет строку в `server_metrics`.
Любой сбой сбора глотается и НЕ влияет на online/offline и не роняет тик.

Опционально — число онлайн-VPN-пиров: `wg show all latest-handshakes` внутри amnezia-wg
контейнера (свежие handshakes). Не установлено/недоступно → None (поле необязательное).

Хранение — таблица `server_metrics` (одна строка на сервер на тик). Ретеншн — фоновой purge
(`server_metrics_retention_days`). Показ — последние значения + N последних сэмплов для графиков.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, insert, select

from vpnhub.api.config import Settings
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.hostmetrics import (
    AMNEZIA_WG_CONTAINERS,
    HOST_METRICS_CMD,
    HostMetrics,
    parse_host_metrics,
    parse_online_clients,
)
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.creds import server_creds
from vpnhub.infra.provisioning.script_runner import list_known_containers
from vpnhub.infra.provisioning.ssh import SshClient, SshError
from vpnhub.infra.provisioning.stats import STATS_PROTOS, enable_stats
from vpnhub.infra.uow import Uow
from vpnhub.services.traffic import (
    TRAFFIC_CONTAINER_DOWN,
    TRAFFIC_OK,
    TRAFFIC_STATS_DISABLED,
    TRAFFIC_UNREACHABLE,
    ProtoTraffic,
    TrafficCollector,
    TrafficService,
    effective_online_window,
)
from vpnhub.services.traffic_rollup import bucket_start, recompute_from

log = structlog.get_logger(__name__)

# STATS_PROTOS — единый список протоколов с включаемой статистикой (см. infra.provisioning.stats)

# авто-heal точной статистики: если при сборе stats выключены, включаем их (идемпотентно) прямо в
# monitor-тике. Троттлинг попыток per (server, proto), чтобы не рестартить контейнер каждый тик.
# In-memory достаточно: рестарт панели разрешит одну лишнюю идемпотентную попытку.
_STATS_HEAL_ATTEMPTS: dict[tuple[str, str], float] = {}
_STATS_HEAL_RETRY_SECONDS = 3600.0


def _hourly_id() -> str:
    """id для строки server_metrics_hourly (как models._id, без импорта приватного хелпера)."""
    return uuid.uuid4().hex[:16]


async def collect_host_metrics(ssh: Any, *, count_clients: bool = True) -> HostMetrics:
    """Собрать `HostMetrics` по уже открытому SSH-каналу (host-метрики + опционально онлайн-пиры).

    Хост-метрики — один вызов `HOST_METRICS_CMD`. Онлайн-клиенты (best-effort): пробуем каждый
    amnezia-wg контейнер, берём первый успешный ответ; недоступно → online_clients=None.
    """
    res = await ssh.run(HOST_METRICS_CMD)
    metrics = parse_host_metrics(res.output)
    if not count_clients:
        return metrics
    online = await _online_clients(ssh)
    if online is not None:
        metrics = HostMetrics(
            cpu_pct=metrics.cpu_pct,
            load1=metrics.load1,
            mem_used=metrics.mem_used,
            mem_total=metrics.mem_total,
            disk_used=metrics.disk_used,
            disk_total=metrics.disk_total,
            tcp_estab=metrics.tcp_estab,
            uptime_s=metrics.uptime_s,
            online_clients=online,
        )
    return metrics


async def _online_clients(ssh: Any) -> int | None:
    """Онлайн-VPN-пиры: свежие handshakes в amnezia-wg контейнере. Недоступно/нет контейнеров → None."""
    now = time.time()
    for container in AMNEZIA_WG_CONTAINERS:
        try:
            res = await ssh.run(f"sudo docker exec -i {container} wg show all latest-handshakes 2>/dev/null")
        except SshError:
            return None
        # непустой вывод с хотя бы одной цифрой (epoch) = живой wg-контейнер; парсер робастен сам
        out = res.output.strip()
        if out and any(ch.isdigit() for ch in out):
            return parse_online_clients(out, now)
    return None


def online_from_traffic(results: dict[str, ProtoTraffic], now: float, window: int) -> dict[str, int | None]:
    """Онлайн-счёт per installed-протокол из уже собранного трафика (без доп. SSH-запросов).

    Раньше online опрашивался отдельно (`collect_online_by_proto` — дублирующие вызовы движка); теперь
    выводится из тех же PeerStat, что дают трафик. Контракт значения: int>=0 — известно; None —
    неизвестно (сбор не ok / протокол без сессий).
    - wireguard (awg/awg_legacy): пиры со свежим handshake (now - last_handshake < window);
    - xray/xray_xhttp/hysteria2/openvpn: пиры с online-флагом движка;
    - outline: None (Shadowsocks без концепции сессии).
    """
    out: dict[str, int | None] = {}
    for proto, res in results.items():
        if res.status != TRAFFIC_OK:
            out[proto] = None  # сбор не удался — честно «неизвестно», не 0
            continue
        try:
            kind = pc.spec_by_id(proto).kind
        except (KeyError, ValueError):
            out[proto] = None
            continue
        if kind == "wireguard":
            out[proto] = sum(
                1 for st in res.stats if st.last_handshake is not None and (now - st.last_handshake) < window
            )
        elif kind in ("xray", "hysteria2", "openvpn"):
            out[proto] = sum(1 for st in res.stats if st.online)
        else:  # outline — сессий нет
            out[proto] = None
    return out


def _sum_known(by_proto: dict[str, int | None]) -> int | None:
    """Сумма известных значений (None-протоколы не считаются). Всё неизвестно → None."""
    known = [v for v in by_proto.values() if v is not None]
    return sum(known) if known else None


class _HostAgg:
    """Накопитель хост-метрик одного бакета: avg по непустым, max, last-by-at для моментальных."""

    def __init__(self) -> None:
        self._sum: dict[str, float] = {}
        self._cnt: dict[str, int] = {}
        self._max: dict[str, float] = {}
        self._last: dict[str, Any] = {}
        self._last_at = float("-inf")
        self.samples_total = 0

    def add(self, r: m.ServerMetric) -> None:
        self.samples_total += 1
        for field in ("cpu_pct", "load1", "mem_used", "tcp_estab", "online_clients"):
            v = getattr(r, field)
            if v is not None:
                self._sum[field] = self._sum.get(field, 0.0) + v
                self._cnt[field] = self._cnt.get(field, 0) + 1
                self._max[field] = v if field not in self._max else max(self._max[field], v)
        if r.at > self._last_at:  # моментальные (total/used) — из последнего сэмпла бакета
            self._last_at = r.at
            for field in ("mem_total", "disk_used", "disk_total"):
                self._last[field] = getattr(r, field)

    def _avg(self, field: str) -> float | None:
        c = self._cnt.get(field, 0)
        return self._sum[field] / c if c else None

    def _max_of(self, field: str) -> float | None:
        return self._max.get(field)

    def as_row(self, server_id: str, bucket: int) -> dict[str, Any]:
        return {
            "server_id": server_id,
            "bucket": bucket,
            "cpu_pct_avg": self._avg("cpu_pct"),
            "cpu_pct_max": self._max_of("cpu_pct"),
            "load1_avg": self._avg("load1"),
            "load1_max": self._max_of("load1"),
            "mem_used_avg": self._avg("mem_used"),
            "mem_total": self._last.get("mem_total"),
            "disk_used": self._last.get("disk_used"),
            "disk_total": self._last.get("disk_total"),
            "tcp_estab_avg": self._avg("tcp_estab"),
            "tcp_estab_max": int(v) if (v := self._max_of("tcp_estab")) is not None else None,
            "online_clients_avg": self._avg("online_clients"),
            "online_clients_max": int(v) if (v := self._max_of("online_clients")) is not None else None,
            "samples_total": self.samples_total,
        }


def aggregate_host_metrics(rows: Iterable[m.ServerMetric], size: int) -> dict[tuple[str, int], dict[str, Any]]:
    """Свернуть сырые ServerMetric в почасовые бакеты (avg по непустым, max, last-by-at)."""
    aggs: dict[tuple[str, int], _HostAgg] = {}
    for r in rows:
        key = (r.server_id, bucket_start(r.at, size))
        agg = aggs.get(key)
        if agg is None:
            agg = _HostAgg()
            aggs[key] = agg
        agg.add(r)
    return {key: agg.as_row(key[0], key[1]) for key, agg in aggs.items()}


class HostMetricsService:
    """Сбор/хранение/агрегация ресурсных метрик серверов (owner-scoped на чтении)."""

    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def collect_for(self, server: m.Server) -> HostMetrics | None:
        """Собрать метрики + трафик одного сервера ОДНОЙ SSH-сессией и записать (best-effort).

        Одна сессия: host-метрики + список контейнеров + per-proto трафик (диспетч TrafficCollector).
        Затем вне SSH: сэмпл ServerMetric (online — из собранного трафика), сэмплы трафика по
        ok-протоколам и health-статусы. Сбой SSH → сервер недоступен: метрики не пишем, health всех
        installed-протоколов = unreachable (чтобы UI показал «сервер недоступен», а не «нет данных»).
        """
        creds = server_creds(server, self.settings.secret_key)
        now = time.time()
        window = effective_online_window(self.settings)
        try:
            async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
                metrics = await collect_host_metrics(ssh, count_clients=False)
                containers = await list_known_containers(ssh)
                results = await self._collect_protocols(ssh, server, containers, now)
        except (SshError, OSError) as e:
            log.info("host_metrics collect skipped", server=server.id, error=str(e))
            await self._mark_unreachable(server.id)
            return None
        by_proto = online_from_traffic(results, now, window)
        await self.record(server.id, metrics, by_proto)
        await self._record_traffic(server.id, results)
        await self._save_health(server.id, results, now)
        return metrics

    async def _collect_protocols(
        self, ssh: SshClient, server: m.Server, containers: dict[str, bool], now: float
    ) -> dict[str, ProtoTraffic]:
        """Собрать per-proto трафик по installed-протоколам сервера в уже открытой SSH-сессии.

        Контейнер отсутствует/не запущен → container_down (движок не трогаем). Для outline подгружаем
        провизионер с материалом (нужен apiUrl). Если stats выключены (stats_disabled) — авто-heal в
        той же сессии. Каждый протокол изолирован внутри TrafficCollector.
        """
        from vpnhub.services.provisioning import ProvisioningService  # noqa: PLC0415 — избегаем цикла import

        prov = ProvisioningService(self.uow, self.settings)
        out: dict[str, ProtoTraffic] = {}
        for sp in server.protocols:
            if not sp.installed:
                continue
            try:
                spec = pc.spec_by_id(sp.proto)
            except (KeyError, ValueError):
                continue
            if not containers.get(spec.container, False):
                out[sp.proto] = ProtoTraffic(sp.proto, TRAFFIC_CONTAINER_DOWN, error="контейнер не запущен")
                continue
            provo = None
            if spec.kind == "outline" and sp.material_encrypted:
                try:
                    provo = prov.loaded_provisioner(sp)
                except Exception:
                    provo = None
            res = await TrafficCollector.collect(ssh, spec, provo)
            if res.status == TRAFFIC_STATS_DISABLED and await self._maybe_heal_stats(ssh, sp.server_id, spec, now):
                res = replace(res, error="точная статистика включается автоматически, данные со следующего сбора")
            out[sp.proto] = res
        return out

    async def _maybe_heal_stats(self, ssh: SshClient, server_id: str, spec: pc.ProtoSpec, now: float) -> bool:
        """Авто-включить точную статистику (idempotent), если протокол поддерживает и она выключена.

        Троттлинг per (server, proto) на `_STATS_HEAL_RETRY_SECONDS`, чтобы не рестартить контейнер
        каждый тик. Возвращает True, если попытка сделана (данные появятся со следующего сбора).
        """
        if spec.id not in STATS_PROTOS or not self.settings.stats_auto_enable:
            return False
        key = (server_id, spec.id)
        if now - _STATS_HEAL_ATTEMPTS.get(key, 0.0) < _STATS_HEAL_RETRY_SECONDS:
            return False
        _STATS_HEAL_ATTEMPTS[key] = now
        try:
            await enable_stats(spec, ssh)
        except (SshError, OSError) as e:  # heal best-effort — следующая попытка через TTL
            log.warning("stats auto-enable failed", server=server_id, proto=spec.id, error=str(e))
            return False
        log.info("stats auto-enabled", server=server_id, proto=spec.id)
        return True

    async def _record_traffic(self, server_id: str, results: dict[str, ProtoTraffic]) -> None:
        """Записать сэмплы трафика по ok-протоколам (best-effort, изоляция на протокол)."""
        traffic = TrafficService(self.uow, self.settings)
        for proto, res in results.items():
            if res.status != TRAFFIC_OK or not res.stats:
                continue
            try:
                await traffic.record(server_id, proto, res.stats)
            except Exception as e:
                log.warning("traffic record failed", server=server_id, proto=proto, error=str(e))

    async def _save_health(self, server_id: str, results: dict[str, ProtoTraffic], now: float) -> None:
        """Сохранить статус сбора в ServerProtocol: ok → collected_at=now, error=None; иначе статус+ошибка."""
        if not results:
            return
        async with self.uow.transaction() as tx:
            rows = (
                (
                    await tx.session.execute(
                        select(m.ServerProtocol).where(m.ServerProtocol.server_id == server_id)
                    )
                )
                .scalars()
                .all()
            )
            by_proto = {sp.proto: sp for sp in rows}
            for proto, res in results.items():
                sp = by_proto.get(proto)
                if sp is None:
                    continue
                sp.traffic_status = res.status
                if res.status == TRAFFIC_OK:
                    sp.traffic_collected_at = now
                    sp.traffic_error = None
                else:
                    sp.traffic_error = res.error

    async def _mark_unreachable(self, server_id: str) -> None:
        """SSH недоступен → health всех installed-протоколов = unreachable (collected_at не трогаем)."""
        async with self.uow.transaction() as tx:
            rows = (
                (
                    await tx.session.execute(
                        select(m.ServerProtocol).where(
                            m.ServerProtocol.server_id == server_id,
                            m.ServerProtocol.installed.is_(True),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for sp in rows:
                sp.traffic_status = TRAFFIC_UNREACHABLE
                sp.traffic_error = "сервер недоступен по SSH"

    async def record(self, server_id: str, metrics: HostMetrics, by_proto: dict[str, int | None] | None = None) -> None:
        """Записать один сэмпл ресурсов хоста (отдельная транзакция).

        online_clients = сумма известных per-proto значений; при отсутствии per-proto берётся
        `metrics.online_clients` (обратная совместимость).
        """
        by_proto = by_proto or {}
        total = _sum_known(by_proto) if by_proto else metrics.online_clients
        async with self.uow.transaction() as tx:
            tx.session.add(
                m.ServerMetric(
                    server_id=server_id,
                    at=time.time(),
                    cpu_pct=metrics.cpu_pct,
                    load1=metrics.load1,
                    mem_used=metrics.mem_used,
                    mem_total=metrics.mem_total,
                    disk_used=metrics.disk_used,
                    disk_total=metrics.disk_total,
                    tcp_estab=metrics.tcp_estab,
                    uptime_s=metrics.uptime_s,
                    online_clients=total,
                    online_by_proto=json.dumps(by_proto) if by_proto else None,
                )
            )
            await tx.session.flush()

    # периоды графика ресурсов: сутки — из сырья (детально), длиннее — из почасовых агрегатов.
    _RAW_PERIOD = "24h"
    _PERIODS = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400, "180d": 180 * 86400}

    async def overview(self, owner_id: str, sid: str, period: str = _RAW_PERIOD) -> dict:
        """Последние значения + история за период. 24h — сырьё; 7d/30d/180d — почасовые агрегаты."""
        period = period if period in self._PERIODS else self._RAW_PERIOD
        limit = max(1, self.settings.server_metrics_history_limit)
        async with self.uow.query() as tx:
            server = await tx.servers.get(sid)
            if not server or server.owner_user_id != owner_id:
                raise NotFound("Сервер не найден")
            if period == self._RAW_PERIOD:
                raw = list(
                    (
                        await tx.session.execute(
                            select(m.ServerMetric)
                            .where(m.ServerMetric.server_id == sid)
                            .order_by(m.ServerMetric.at.desc())
                            .limit(limit)
                        )
                    )
                    .scalars()
                    .all()
                )
                raw.reverse()  # хронологический порядок для графиков
                samples = [self._sample_dict(r) for r in raw]
            else:
                since = time.time() - self._PERIODS[period]
                agg = list(
                    (
                        await tx.session.execute(
                            select(m.ServerMetricHourly)
                            .where(m.ServerMetricHourly.server_id == sid, m.ServerMetricHourly.bucket >= since)
                            .order_by(m.ServerMetricHourly.bucket.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
                samples = [self._hourly_dict(r) for r in agg]
        current = samples[-1] if samples else None
        return {"serverId": sid, "period": period, "current": current, "samples": samples}

    @staticmethod
    def _sample_dict(r: m.ServerMetric) -> dict:
        return {
            "at": r.at,
            "cpuPct": r.cpu_pct,
            "load1": r.load1,
            "memUsed": r.mem_used,
            "memTotal": r.mem_total,
            "diskUsed": r.disk_used,
            "diskTotal": r.disk_total,
            "tcpEstab": r.tcp_estab,
            "uptimeS": r.uptime_s,
            "onlineClients": r.online_clients,
            "onlineByProto": json.loads(r.online_by_proto) if r.online_by_proto else {},
        }

    @staticmethod
    def _hourly_dict(r: m.ServerMetricHourly) -> dict:
        """Почасовой агрегат в форму сэмпла (avg-значения) — тот же контракт, что и _sample_dict."""
        return {
            "at": float(r.bucket),
            "cpuPct": r.cpu_pct_avg,
            "load1": r.load1_avg,
            "memUsed": int(r.mem_used_avg) if r.mem_used_avg is not None else None,
            "memTotal": r.mem_total,
            "diskUsed": r.disk_used,
            "diskTotal": r.disk_total,
            "tcpEstab": int(r.tcp_estab_avg) if r.tcp_estab_avg is not None else None,
            "uptimeS": None,  # аптайм не усредняется
            "onlineClients": int(r.online_clients_avg) if r.online_clients_avg is not None else None,
            "onlineByProto": {},
        }

    async def rollup_tick(self) -> dict[str, int]:
        """Досчитать почасовые агрегаты хост-метрик и почистить сырьё/агрегаты (фоновая джоба)."""
        now = time.time()
        rolled = await self._rollup_hourly(now)
        purged = await self._purge_old(now)
        result = {"hourly": rolled, **purged}
        log.info("server_metrics_rollup_tick", **result)
        return result

    async def _rollup_hourly(self, now: float) -> int:
        """Пересчёт хвоста delete+insert с клампом на oldest сырья (как traffic-rollup)."""
        async with self.uow.transaction() as tx:
            watermark = (
                await tx.session.execute(select(func.max(m.ServerMetricHourly.bucket)))
            ).scalar_one_or_none()
            oldest_at = (await tx.session.execute(select(func.min(m.ServerMetric.at)))).scalar_one_or_none()
            rf = recompute_from(watermark, oldest_at, 3600)
            if rf is None:
                return 0
            await tx.session.execute(sa_delete(m.ServerMetricHourly).where(m.ServerMetricHourly.bucket >= rf))
            rows = list(
                (
                    await tx.session.execute(select(m.ServerMetric).where(m.ServerMetric.at >= rf))
                )
                .scalars()
                .all()
            )
            aggs = aggregate_host_metrics(rows, 3600)
            if aggs:
                await tx.session.execute(
                    insert(m.ServerMetricHourly),
                    [{"id": _hourly_id(), **row} for row in aggs.values()],
                )
            return len(aggs)

    async def _purge_old(self, now: float) -> dict[str, int]:
        """Удалить сырьё старше `server_metrics_retention_days` и агрегаты старше hourly-ретеншна."""
        raw_cutoff = now - self.settings.server_metrics_retention_days * 86400
        hourly_cutoff = now - self.settings.server_metrics_hourly_retention_days * 86400
        async with self.uow.transaction() as tx:
            raw: Any = await tx.session.execute(sa_delete(m.ServerMetric).where(m.ServerMetric.at < raw_cutoff))
            hourly: Any = await tx.session.execute(
                sa_delete(m.ServerMetricHourly).where(m.ServerMetricHourly.bucket < hourly_cutoff)
            )
        return {"purged_raw": int(raw.rowcount or 0), "purged_hourly": int(hourly.rowcount or 0)}

    async def enable_stats(self, owner_id: str, sid: str) -> dict[str, str]:
        """Включить точную онлайн-статистику на сервере (owner-scoped).

        Идёт по installed-протоколам xray/xray_xhttp/hysteria2 и вызывает `enable_stats` провизионера
        (идемпотентно; контейнер перезапускается ТОЛЬКО если конфиг реально менялся). Возвращает
        {proto: 'enabled'|'already'|'error'}. Best-effort по каждому протоколу.
        """
        async with self.uow.query() as tx:
            server = await tx.servers.get(sid)
            if not server or server.owner_user_id != owner_id:
                raise NotFound("Сервер не найден")
            protos = [sp.proto for sp in server.protocols if sp.installed and sp.proto in STATS_PROTOS]
            creds = server_creds(server, self.settings.secret_key)
        result: dict[str, str] = {}
        if not protos:
            return result
        async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
            for proto in protos:
                try:
                    changed = await enable_stats(pc.spec_by_id(proto), ssh)
                    result[proto] = "enabled" if changed else "already"
                except (SshError, OSError) as e:
                    log.warning("enable_stats failed", server=sid, proto=proto, error=str(e))
                    result[proto] = "error"
        return result
