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
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

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
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
from vpnhub.infra.provisioning.script_runner import list_known_containers
from vpnhub.infra.provisioning.ssh import ServerCreds, SshClient, SshError
from vpnhub.infra.security import decrypt_secret
from vpnhub.infra.uow import Uow
from vpnhub.services.traffic import (
    TRAFFIC_CONTAINER_DOWN,
    TRAFFIC_OK,
    TRAFFIC_UNREACHABLE,
    ProtoTraffic,
    TrafficCollector,
    TrafficService,
    effective_online_window,
)

log = structlog.get_logger(__name__)

# протоколы с включаемым stats-API (точный per-user online): xray/xray_xhttp — Xray Stats API,
# hysteria2 — trafficStats. awg/awg_legacy считаются по handshakes (включать нечего), outline/openvpn — нет.
_STATS_PROTOS = ("xray", "xray_xhttp", "hysteria2")


def _creds(settings: Settings, server: m.Server) -> ServerCreds:
    return ServerCreds(
        host=server.ip,
        port=int(server.ssh_port or 22),
        username=server.ssh_user or "root",
        auth=server.ssh_auth or "key",
        secret=decrypt_secret(settings.secret_key, server.ssh_secret_encrypted or ""),
    )


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
        creds = _creds(self.settings, server)
        now = time.time()
        window = effective_online_window(self.settings)
        try:
            async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
                metrics = await collect_host_metrics(ssh, count_clients=False)
                containers = await list_known_containers(ssh)
                results = await self._collect_protocols(ssh, server, containers)
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
        self, ssh: SshClient, server: m.Server, containers: dict[str, bool]
    ) -> dict[str, ProtoTraffic]:
        """Собрать per-proto трафик по installed-протоколам сервера в уже открытой SSH-сессии.

        Контейнер отсутствует/не запущен → container_down (движок не трогаем). Для outline подгружаем
        провизионер с материалом (нужен apiUrl). Каждый протокол изолирован внутри TrafficCollector.
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
            out[sp.proto] = await TrafficCollector.collect(ssh, spec, provo)
        return out

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

    async def overview(self, owner_id: str, sid: str) -> dict:
        """Последние значения + история N последних сэмплов для графиков. Владение как в ServerService."""
        limit = max(1, self.settings.server_metrics_history_limit)
        async with self.uow.query() as tx:
            server = await tx.servers.get(sid)
            if not server or server.owner_user_id != owner_id:
                raise NotFound("Сервер не найден")
            rows = list(
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
        rows.reverse()  # хронологический порядок для графиков (было desc для limit последних)
        samples = [self._sample_dict(r) for r in rows]
        current = samples[-1] if samples else None
        return {"serverId": sid, "current": current, "samples": samples}

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

    async def purge_old(self) -> int:
        """Удалить сэмплы старше `server_metrics_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.server_metrics_retention_days * 86400
        async with self.uow.transaction() as tx:
            res: Any = await tx.session.execute(sa_delete(m.ServerMetric).where(m.ServerMetric.at < cutoff))
            return int(res.rowcount or 0)

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
            protos = [sp.proto for sp in server.protocols if sp.installed and sp.proto in _STATS_PROTOS]
            creds = _creds(self.settings, server)
        result: dict[str, str] = {}
        if not protos:
            return result
        async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
            for proto in protos:
                spec = pc.spec_by_id(proto)
                try:
                    if proto in ("xray", "xray_xhttp"):
                        changed = await XrayProvisioner(spec).enable_stats(ssh)
                        result[proto] = "enabled" if changed else "already"
                    else:  # hysteria2
                        await HysteriaProvisioner(spec).enable_stats(ssh)
                        result[proto] = "enabled"
                except (SshError, OSError) as e:
                    log.warning("enable_stats failed", server=sid, proto=proto, error=str(e))
                    result[proto] = "error"
        return result
