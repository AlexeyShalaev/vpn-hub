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
from vpnhub.infra.provisioning.ssh import ServerCreds, SshClient, SshError
from vpnhub.infra.security import decrypt_secret
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)


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


class HostMetricsService:
    """Сбор/хранение/агрегация ресурсных метрик серверов (owner-scoped на чтении)."""

    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def collect_for(self, server: m.Server) -> HostMetrics | None:
        """Собрать метрики одного сервера отдельной короткой SSH-сессией и записать сэмпл.

        Best-effort: сбой SSH/парсинга → None (лог + пропуск), тик не роняем.
        """
        creds = _creds(self.settings, server)
        try:
            async with SshClient(creds, connect_timeout=self.settings.monitor_timeout) as ssh:
                metrics = await collect_host_metrics(ssh)
        except (SshError, OSError) as e:
            log.info("host_metrics collect skipped", server=server.id, error=str(e))
            return None
        await self.record(server.id, metrics)
        return metrics

    async def record(self, server_id: str, metrics: HostMetrics) -> None:
        """Записать один сэмпл ресурсов хоста (отдельная транзакция)."""
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
                    online_clients=metrics.online_clients,
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
        }

    async def purge_old(self) -> int:
        """Удалить сэмплы старше `server_metrics_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.server_metrics_retention_days * 86400
        async with self.uow.transaction() as tx:
            res: Any = await tx.session.execute(sa_delete(m.ServerMetric).where(m.ServerMetric.at < cutoff))
            return int(res.rowcount or 0)
