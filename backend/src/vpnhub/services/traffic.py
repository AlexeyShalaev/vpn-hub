"""Дашборд трафика и подключений (owner): сбор статистики по SSH + агрегация для UI.

Сбор врезан в sync-тик (SSH-сессия уже открыта, материал загружен) и строго best-effort:
любой сбой глотается на стороне SyncService и НЕ влияет на решения sync (никаких ложных revoke).
MVP собирает только wireguard-протоколы (awg/awg_legacy) через `{bin} show {iface} dump`.
Прочие kind (xray/hysteria2/outline) возвращают пусто — точки расширения помечены TODO.

Хранение — таблица дельта-сэмплов `traffic_samples` (одна строка на клиента-протокол на тик).
Дельта считается от прошлого сэмпла; при рестарте счётчиков wg (curr<prev) дельта = curr.
Онлайн-статус — из свежести `last_handshake` (`traffic_online_window_seconds`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)

# whitelist периодов дашборда → длительность в секундах
_PERIODS: dict[str, int] = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
_DEFAULT_PERIOD = "24h"


@dataclass(frozen=True)
class PeerStat:
    """Сырой замер по одному пиру (из `wg show dump`)."""

    client_id: str  # pubkey (wg/awg)
    rx: int  # кумулятивно принято, байт
    tx: int  # кумулятивно отдано, байт
    last_handshake: float | None  # epoch; None — рукопожатий ещё не было (dump отдаёт 0)


def parse_wg_dump(text: str) -> list[PeerStat]:
    """Разобрать вывод `wg show <iface> dump` в список PeerStat.

    Формат: TSV; первая строка — интерфейс (приватный ключ, ...) → пропускается. Каждая
    строка пира: `pubkey  psk  endpoint  allowed-ips  latest-handshake(epoch)  rx  tx  keepalive`.
    Робастно к пустому/битому выводу (короткие строки/нечисловые поля пропускаются) — как
    read_clients_table в sync: сбой парсинга не должен ронять сборщик.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return []
    out: list[PeerStat] = []
    for line in lines[1:]:  # первая строка — интерфейс
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        pubkey = fields[0].strip()
        if not pubkey:
            continue
        try:
            handshake = int(fields[4])
            rx = int(fields[5])
            tx = int(fields[6])
        except ValueError:
            continue
        out.append(PeerStat(client_id=pubkey, rx=rx, tx=tx, last_handshake=float(handshake) if handshake else None))
    return out


class TrafficCollector:
    """Читает статистику пиров по уже открытому SSH-каналу (для одного протокола)."""

    @staticmethod
    async def collect(ssh: Any, spec: pc.ProtoSpec) -> list[PeerStat]:
        """Собрать PeerStat для протокола `spec`. Только wireguard; иначе — пусто.

        wireguard: `{spec.bin} show {spec.interface} dump` внутри контейнера.
        TODO(xray): xray api statsquery (--server=...) → per-uuid uplink/downlink.
        TODO(hysteria2): Hysteria2 traffic stats API (trafficStats.listen).
        TODO(outline): GET <apiUrl>/metrics/transfer → bytesTransferredByUserId.
        """
        if spec.kind != "wireguard":
            return []
        res = await ssh.container_exec(spec.container, f"{spec.bin} show {spec.interface} dump")
        return parse_wg_dump(res.stdout)


class TrafficService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def record(self, server_id: str, proto: str, stats: list[PeerStat]) -> int:
        """Записать сэмплы для протокола за один тик (отдельная транзакция).

        Дельта считается от последнего сэмпла по (server, proto, client): curr>=prev → curr-prev,
        curr<prev (рестарт счётчиков wg) → curr, первый сэмпл → дельта = кумулятив. Сопоставление
        client_id → DeviceConfig — по client_id (pubkey); отсутствие устройства не ошибка (external).
        """
        if not stats:
            return 0
        now = time.time()
        client_ids = [s.client_id for s in stats]
        async with self.uow.transaction() as tx:
            prev = await self._last_cumulative(tx, server_id, proto, client_ids)
            dc_by_client = await self._device_config_ids(tx, server_id, client_ids)
            for st in stats:
                prev_rx, prev_tx = prev.get(st.client_id, (0, 0))
                rx_delta = st.rx - prev_rx if st.rx >= prev_rx else st.rx
                tx_delta = st.tx - prev_tx if st.tx >= prev_tx else st.tx
                tx.session.add(
                    m.TrafficSample(
                        server_id=server_id,
                        proto=proto,
                        client_id=st.client_id,
                        device_config_id=dc_by_client.get(st.client_id),
                        at=now,
                        rx_bytes=st.rx,
                        tx_bytes=st.tx,
                        rx_delta=rx_delta,
                        tx_delta=tx_delta,
                        last_handshake=st.last_handshake,
                    )
                )
            await tx.session.flush()
        return len(stats)

    async def _last_cumulative(
        self, tx: Any, server_id: str, proto: str, client_ids: list[str]
    ) -> dict[str, tuple[int, int]]:
        """Последние кумулятивы (rx,tx) по каждому client_id (для расчёта дельт)."""
        rows = list(
            (
                await tx.session.execute(
                    select(m.TrafficSample)
                    .where(
                        m.TrafficSample.server_id == server_id,
                        m.TrafficSample.proto == proto,
                        m.TrafficSample.client_id.in_(client_ids),
                    )
                    .order_by(m.TrafficSample.at.asc())
                )
            )
            .scalars()
            .all()
        )
        # последний по времени выигрывает (asc → последняя запись перетирает)
        out: dict[str, tuple[int, int]] = {}
        for r in rows:
            if r.client_id is not None:
                out[r.client_id] = (r.rx_bytes, r.tx_bytes)
        return out

    async def _device_config_ids(self, tx: Any, server_id: str, client_ids: list[str]) -> dict[str, str]:
        """client_id (pubkey) → DeviceConfig.id для клиентов этого сервера."""
        rows = list(
            (
                await tx.session.execute(
                    select(m.DeviceConfig).where(
                        m.DeviceConfig.server_id == server_id,
                        m.DeviceConfig.client_id.in_(client_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {r.client_id: r.id for r in rows if r.client_id}

    async def overview(self, owner_id: str, sid: str, period: str = _DEFAULT_PERIOD) -> dict:
        """Агрегаты по клиентам + временные ряды за период. Владение проверяется как в ServerService."""
        window = _PERIODS.get(period, _PERIODS[_DEFAULT_PERIOD])
        now = time.time()
        since = now - window
        online_window = self.settings.traffic_online_window_seconds
        async with self.uow.query() as tx:
            server = await tx.servers.get(sid)
            if not server or server.owner_user_id != owner_id:
                raise NotFound("Сервер не найден")
            samples = list(
                (
                    await tx.session.execute(
                        select(m.TrafficSample)
                        .where(m.TrafficSample.server_id == sid, m.TrafficSample.at >= since)
                        .order_by(m.TrafficSample.at.asc())
                    )
                )
                .scalars()
                .all()
            )
            names = await self._names(tx, samples)

        # агрегация per (proto, client)
        clients: dict[tuple[str, str | None], dict] = {}
        series: list[dict] = []
        for s in samples:
            key = (s.proto, s.client_id)
            agg = clients.get(key)
            if agg is None:
                dev, usr = names.get(s.device_config_id or "", ("", ""))
                agg = {
                    "proto": s.proto,
                    "clientId": s.client_id,
                    "deviceName": dev,
                    "userName": usr,
                    "external": s.device_config_id is None,
                    "rxTotal": 0,
                    "txTotal": 0,
                    "rxBytes": s.rx_bytes,
                    "txBytes": s.tx_bytes,
                    "lastHandshake": s.last_handshake,
                    "online": False,
                }
                clients[key] = agg
            agg["rxTotal"] += s.rx_delta
            agg["txTotal"] += s.tx_delta
            agg["rxBytes"] = s.rx_bytes
            agg["txBytes"] = s.tx_bytes
            lh = agg["lastHandshake"]
            if s.last_handshake is not None and (lh is None or s.last_handshake > lh):
                agg["lastHandshake"] = s.last_handshake
            series.append({"at": s.at, "proto": s.proto, "clientId": s.client_id, "rx": s.rx_delta, "tx": s.tx_delta})

        for agg in clients.values():
            lh = agg["lastHandshake"]
            agg["online"] = lh is not None and (now - lh) < online_window

        return {
            "serverId": sid,
            "period": period if period in _PERIODS else _DEFAULT_PERIOD,
            "onlineWindowSeconds": online_window,
            "clients": sorted(clients.values(), key=lambda c: c["rxTotal"] + c["txTotal"], reverse=True),
            "series": series,
        }

    async def _names(self, tx: Any, samples: list[m.TrafficSample]) -> dict[str, tuple[str, str]]:
        """DeviceConfig.id → (имя устройства, имя пользователя) для нон-external клиентов."""
        dc_ids = {s.device_config_id for s in samples if s.device_config_id}
        if not dc_ids:
            return {}
        rows = list(
            (
                await tx.session.execute(
                    select(m.DeviceConfig, m.Device, m.User)
                    .join(m.Device, m.Device.id == m.DeviceConfig.device_id)
                    .join(m.User, m.User.id == m.Device.user_id, isouter=True)
                    .where(m.DeviceConfig.id.in_(dc_ids))
                )
            ).all()
        )
        out: dict[str, tuple[str, str]] = {}
        for cfg, dev, usr in rows:
            out[cfg.id] = (dev.name if dev else "", usr.name if usr else "")
        return out

    async def purge_old(self) -> int:
        """Удалить сэмплы старше `traffic_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.traffic_retention_days * 86400
        async with self.uow.transaction() as tx:
            res: Any = await tx.session.execute(sa_delete(m.TrafficSample).where(m.TrafficSample.at < cutoff))
            return int(res.rowcount or 0)
