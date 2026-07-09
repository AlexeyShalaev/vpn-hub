"""Супер-мониторинг клиентов (owner): per-client трафик+онлайн по ВСЕМ протоколам.

Сбор врезан в sync-тик (SSH-сессия уже открыта, материал загружен) и строго best-effort:
любой сбой глотается на стороне SyncService и НЕ влияет на решения sync (никаких ложных revoke).
Диспетч по `spec.kind` (см. `TrafficCollector.collect`):
- wireguard (awg/awg_legacy): `{bin} show {iface} dump` (rx/tx кумулятивно, online — свежесть handshake);
- xray (kind=="xray"): `xray api statsquery -reset=false` → per-uuid uplink/downlink/online;
- hysteria2: trafficStats API `/traffic`+`/online` → per-authid rx/tx/online;
- openvpn: OpenVPN status-лог (`status <path>` уже в server.conf) → per-CN Bytes Received/Sent
  (rx/tx кумулятивно) + online по присутствию в CLIENT_LIST;
- outline: `GET <apiUrl>/metrics/transfer` (по SSH на localhost) → per-key СУММАРНЫЙ трафик
  (кладём в tx; rx=0, online не поддержан Outline). Нужен провизионер с материалом (apiUrl).
Идентификатор движка = наш `device_configs.client_id` (pubkey / uuid / authid / CN / key-id).

Хранение — таблица дельта-сэмплов `traffic_samples` (одна строка на клиента-протокол на тик)
плюс состояние счётчиков `traffic_peer_state` (последний кумулятив per server+proto+client).
Дельта считается от peer_state (O(1), переживает purge сырья); при рестарте счётчиков
(curr<prev) дельта = curr.
Онлайн-статус: для wg — свежесть `last_handshake` (`traffic_online_window_seconds`); для
xray/hysteria2 — поле `online` из stats движка (у них handshake нет).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from vpnhub.api.config import Settings
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners import base as pbase
from vpnhub.infra.provisioning.provisioners.hysteria2 import _STATS_LISTEN, HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XRAY_STATS_PORT
from vpnhub.infra.trafficstats import (
    parse_hysteria_traffic,
    parse_openvpn_traffic,
    parse_outline_transfer,
    parse_xray_stats,
)
from vpnhub.infra.uow import Uow
from vpnhub.services.limits import add_period_usage, period_start

log = structlog.get_logger(__name__)

# whitelist периодов дашборда → длительность в секундах
_PERIODS: dict[str, int] = {"1h": 3600, "24h": 86400, "7d": 7 * 86400}
_DEFAULT_PERIOD = "24h"


def _group_by_server(samples: list[m.TrafficSample]) -> dict[str, list[m.TrafficSample]]:
    """Разложить сэмплы по server_id, сохраняя порядок (для аккуратной агрегации per-server)."""
    out: dict[str, list[m.TrafficSample]] = {}
    for s in samples:
        out.setdefault(s.server_id, []).append(s)
    return out


def _aggregate_clients(
    samples: list[m.TrafficSample], names: dict[str, tuple[str, str, str]], now: float, online_window: int
) -> list[dict]:
    """Свернуть сэмплы в per-(proto,client) агрегаты: суммарный трафик, онлайн, скорость.

    Чистая (без IO) — общая для per-server `overview` и глобального `global_overview`.
    - rxTotal/txTotal — сумма дельт за окно (потрачено за период);
    - rxBytes/txBytes — последний кумулятив;
    - online — `online`-флаг из последнего сэмпла (xray/hysteria) ИЛИ свежесть handshake (wg);
    - rxSpeed/txSpeed — байт/сек из последней дельты (delta / интервал между двумя последними сэмплами);
    - lastSeen — max(at по свежему трафику/handshake) для сортировки «последний онлайн».
    `samples` предполагаются в порядке возрастания `at`.
    """
    clients: dict[tuple[str, str | None], dict] = {}
    prev_at: dict[tuple[str, str | None], float] = {}
    for s in samples:
        key = (s.proto, s.client_id)
        agg = clients.get(key)
        if agg is None:
            dev, usr, cfg_status = names.get(s.device_config_id or "", ("", "", "active"))
            agg = {
                "proto": s.proto,
                "clientId": s.client_id,
                "configId": s.device_config_id,  # для ручной паузы/старта из мониторинга (null у external)
                "status": cfg_status,  # active | paused | suspended | revoked
                "deviceName": dev,
                "userName": usr,
                "external": s.device_config_id is None,
                "extName": "",  # имя из Amnezia clientsTable (только для external; ниже добираем непустое)
                "rxTotal": 0,
                "txTotal": 0,
                "rxBytes": s.rx_bytes,
                "txBytes": s.tx_bytes,
                "lastHandshake": s.last_handshake,
                "onlineFlag": s.online,
                "rxSpeed": 0.0,
                "txSpeed": 0.0,
                "lastSeen": None,
                "online": False,
            }
            clients[key] = agg
        agg["rxTotal"] += s.rx_delta
        agg["txTotal"] += s.tx_delta
        agg["rxBytes"] = s.rx_bytes
        agg["txBytes"] = s.tx_bytes
        agg["onlineFlag"] = s.online
        # extName — имя external-клиента из clientsTable; берём непустое (у части сэмплов может быть пусто)
        if agg["external"] and not agg["extName"] and s.ext_name:
            agg["extName"] = s.ext_name
        lh = agg["lastHandshake"]
        if s.last_handshake is not None and (lh is None or s.last_handshake > lh):
            agg["lastHandshake"] = s.last_handshake
        # скорость — по интервалу между двумя последними сэмплами этого клиента
        pa = prev_at.get(key)
        interval = (s.at - pa) if pa is not None else 0.0
        if interval > 0:
            agg["rxSpeed"] = s.rx_delta / interval
            agg["txSpeed"] = s.tx_delta / interval
        prev_at[key] = s.at
        # lastSeen — свежесть контакта: handshake (wg) или at при активной сессии/трафике
        seen_at = s.last_handshake
        if s.online or s.rx_delta or s.tx_delta:
            seen_at = s.at if seen_at is None else max(seen_at, s.at)
        if seen_at is not None and (agg["lastSeen"] is None or seen_at > agg["lastSeen"]):
            agg["lastSeen"] = seen_at

    for agg in clients.values():
        flag = agg.pop("onlineFlag")
        if flag is not None:  # stats-протоколы (xray/hysteria2) — доверяем движку
            agg["online"] = bool(flag)
        else:  # wg — по свежести handshake
            lh = agg["lastHandshake"]
            agg["online"] = lh is not None and (now - lh) < online_window
        if not agg["online"]:  # скорость показываем только у активных
            agg["rxSpeed"] = 0.0
            agg["txSpeed"] = 0.0
    return list(clients.values())


@dataclass(frozen=True)
class PeerStat:
    """Сырой замер по одному клиенту (wg-dump / xray statsquery / hysteria trafficStats)."""

    client_id: str  # pubkey (wg/awg) | uuid (xray) | authid (hysteria2)
    rx: int  # кумулятивно принято (клиент→сервер, upload), байт
    tx: int  # кумулятивно отдано (сервер→клиент, download), байт
    last_handshake: float | None  # epoch; None — рукопожатий не было / протокол без handshake (xray/hysteria)
    online: bool | None = None  # активна ли сессия сейчас (из stats движка); None — определять по handshake
    name: str | None = None  # имя клиента из Amnezia clientsTable (clientName); нужно для external


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


def clients_table_names(rows: list[Any]) -> dict[str, str]:
    """clientId → clientName из строк Amnezia clientsTable (robust к битым/пустым строкам).

    Формат строки: `{"clientId": "<pubkey|uuid>", "userData": {"clientName": "...", ...}}`.
    Строки без clientId / без непустого clientName пропускаются (не ошибка). `rows` — сырой
    JSON-массив из clientsTable, поэтому элементы могут быть чем угодно (проверяем isinstance).
    """
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cid = row.get("clientId")
        user_data = row.get("userData")
        if not isinstance(cid, str) or not cid or not isinstance(user_data, dict):
            continue
        name = user_data.get("clientName")
        if isinstance(name, str) and name.strip():
            out[cid] = name
    return out


# протоколы с Amnezia clientsTable (имена external-клиентов); outline его не использует.
_CLIENTS_TABLE_KINDS = frozenset({"wireguard", "xray", "hysteria2", "openvpn"})


class TrafficCollector:
    """Читает per-client статистику по уже открытому SSH-каналу (диспетч по kind протокола)."""

    @staticmethod
    async def collect(ssh: Any, spec: pc.ProtoSpec, provo: Any = None) -> list[PeerStat]:
        """Собрать PeerStat для протокола `spec` (best-effort; сбой/выкл. stats → пусто, не ошибка).

        - wireguard (awg/awg_legacy): `{spec.bin} show {spec.interface} dump` (rx/tx кумулятивно,
          online — по свежести handshake в overview);
        - xray (VLESS+Reality/XHTTP): `xray api statsquery -reset=false` → per-uuid uplink/downlink/online
          (кумулятив, счётчики НЕ сбрасываются — дельты считает record());
        - hysteria2: trafficStats API `/traffic`+`/online` (кумулятив, без ?clear=1);
        - openvpn: OpenVPN status-лог → per-CN Bytes Received/Sent (кумулятив) + online по CLIENT_LIST;
        - outline: `GET <apiUrl>/metrics/transfer` → per-key суммарный трафик (нужен `provo` с apiUrl).

        `provo` — уже загруженный/адаптированный провизионер этого протокола (из sync-тика); нужен
        только для outline (взять apiUrl). Для остальных протоколов не требуется.
        """
        if spec.kind == "wireguard":
            res = await ssh.container_exec(spec.container, f"{spec.bin} show {spec.interface} dump")
            stats = parse_wg_dump(res.stdout)
        elif spec.kind == "xray":
            stats = await TrafficCollector._collect_xray(ssh, spec)
        elif spec.kind == "hysteria2":
            stats = await TrafficCollector._collect_hysteria(ssh, spec)
        elif spec.kind == "openvpn":
            stats = await TrafficCollector._collect_openvpn(ssh, spec)
        elif spec.kind == "outline":
            stats = await TrafficCollector._collect_outline(ssh, spec, provo)
        else:
            return []
        if stats and spec.kind in _CLIENTS_TABLE_KINDS:
            stats = await TrafficCollector._attach_names(ssh, spec, stats)
        return stats

    @staticmethod
    async def _attach_names(ssh: Any, spec: pc.ProtoSpec, stats: list[PeerStat]) -> list[PeerStat]:
        """Проставить `PeerStat.name` из Amnezia clientsTable (для показа имён external-клиентов).

        Best-effort: нет файла/ошибка чтения → clientsTable пуст → имена просто не добавляются.
        clientId в clientsTable == наш device_configs.client_id (== PeerStat.client_id).
        """
        rows = await pbase.read_clients_table(ssh, spec)
        names = clients_table_names(rows)
        if not names:
            return stats
        return [replace(st, name=names[st.client_id]) if st.client_id in names else st for st in stats]

    # путь OpenVPN status-лога внутри контейнера. server.conf задаёт относительный `status
    # openvpn-status.log`; демон стартует из / (start.sh без cd) → файл в корне. Пробуем оба
    # кандидата (рабочая директория демона и папка конфига) — берём первый непустой.
    _OVPN_STATUS_PATHS = ("/openvpn-status.log", "/opt/amnezia/openvpn/openvpn-status.log")

    @staticmethod
    async def _collect_openvpn(ssh: Any, spec: pc.ProtoSpec) -> list[PeerStat]:
        """Per-CN трафик+онлайн из OpenVPN status-лога (`status <path>` уже в server.conf).

        rx = Bytes Received (client→server), tx = Bytes Sent (server→client), кумулятивно.
        online = присутствие CN в CLIENT_LIST. Лог не настроен/недоступен → пусто (best-effort).
        """
        for path in TrafficCollector._OVPN_STATUS_PATHS:
            res = await ssh.run(f"sudo docker exec {spec.container} cat {path} 2>/dev/null")
            if res.exit_status != 0:
                continue
            rows = parse_openvpn_traffic(res.output)
            if rows:
                return [
                    PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
                    for c in rows
                ]
        return []

    @staticmethod
    async def _collect_outline(ssh: Any, spec: pc.ProtoSpec, provo: Any) -> list[PeerStat]:
        """Per-key суммарный трафик через Outline Management API `GET /metrics/transfer`.

        Ходим curl-ом по SSH на localhost сервера (как сам провизионер). Материал (apiUrl) берём из
        `provo`; без провизионера/материала → пусто. Outline даёт только суммарные байты: tx=total,
        rx=0, online не поддержан (None). Недоступность API → пусто (best-effort).
        """
        if not isinstance(provo, OutlineProvisioner):
            return []
        try:
            url = f"{provo._local_api()}/metrics/transfer"
        except ValueError:  # нет материала (apiUrl)
            return []
        res = await ssh.run(f'curl -sfk --max-time 20 "{url}" 2>/dev/null')
        if res.exit_status != 0:
            return []
        return [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_outline_transfer(res.output)
        ]

    @staticmethod
    async def _collect_xray(ssh: Any, spec: pc.ProtoSpec) -> list[PeerStat]:
        """Per-uuid трафик+онлайн через Xray Stats API. `-reset=false` → счётчики кумулятивны.

        stats не включён / бинарь недоступен → statsquery падает/пусто → пусто (не ошибка).
        """
        cmd = (
            f"sudo docker exec {spec.container} xray api statsquery "
            f"--server=127.0.0.1:{XRAY_STATS_PORT} -reset=false -pattern 'user>>>' 2>/dev/null"
        )
        res = await ssh.run(cmd)
        if res.exit_status != 0:
            return []
        return [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_xray_stats(res.output)
        ]

    @staticmethod
    async def _collect_hysteria(ssh: Any, spec: pc.ProtoSpec) -> list[PeerStat]:
        """Per-authid трафик (/traffic) + онлайн (/online) через Hysteria2 trafficStats API.

        Секрет читаем из config.yaml (`_read_stats_secret`); без него (stats не включён) → пусто.
        `/traffic` БЕЗ ?clear=1 → счётчики кумулятивны (дельты считает record()).
        """
        prov = HysteriaProvisioner(spec)
        secret = await prov._read_stats_secret(ssh)
        if not secret:
            return []
        base = f'sudo docker exec {spec.container} curl -s -H "Authorization: {secret}" http://{_STATS_LISTEN}'
        traffic = await ssh.run(f"{base}/traffic 2>/dev/null")
        online = await ssh.run(f"{base}/online 2>/dev/null")
        if traffic.exit_status != 0:
            return []
        online_text = online.output if online.exit_status == 0 else None
        return [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_hysteria_traffic(traffic.output, online_text)
        ]


class TrafficService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def record(self, server_id: str, proto: str, stats: list[PeerStat]) -> int:
        """Записать сэмплы для протокола за один тик (отдельная транзакция).

        Дельта считается от `traffic_peer_state` (последний кумулятив по server+proto+client):
        curr>=prev → curr-prev, curr<prev (рестарт счётчиков wg) → curr, первый сэмпл → дельта =
        кумулятив. Состояние переживает purge сырых сэмплов — простой клиента дольше ретеншна не
        даёт ложный всплеск. Сопоставление client_id → DeviceConfig — по client_id (pubkey);
        отсутствие устройства не ошибка (external). Конкурентные record() одного клиента разводятся
        уникумом traffic_peer_state_uq (вставка в savepoint, как add_period_usage).
        """
        if not stats:
            return 0
        now = time.time()
        client_ids = [s.client_id for s in stats]
        async with self.uow.transaction() as tx:
            states = await self._peer_states(tx, server_id, proto, client_ids)
            dc_by_client = await self._device_config_ids(tx, server_id, client_ids)
            user_by_client = await self._user_ids(tx, server_id, client_ids)
            billing_day = (
                await tx.session.execute(select(m.Server.billing_day).where(m.Server.id == server_id))
            ).scalar_one_or_none()
            ps = period_start(now, billing_day)
            # накопитель за период: None-ключ — суммарный трафик сервера (вкл. external), user_id — пер-user
            by_user: dict[str | None, list[int]] = {}
            for st in stats:
                state = states.get(st.client_id)
                prev_rx, prev_tx = (state.rx_bytes, state.tx_bytes) if state is not None else (0, 0)
                rx_delta = st.rx - prev_rx if st.rx >= prev_rx else st.rx
                tx_delta = st.tx - prev_tx if st.tx >= prev_tx else st.tx
                await self._upsert_peer_state(
                    tx, server_id, proto, st, state, dc_by_client.get(st.client_id), rx_delta, tx_delta, now
                )
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
                        online=st.online,
                        ext_name=st.name,
                    )
                )
                agg = by_user.setdefault(None, [0, 0])  # суммарно по серверу
                agg[0] += rx_delta
                agg[1] += tx_delta
                uid = user_by_client.get(st.client_id or "")
                if uid:
                    u = by_user.setdefault(uid, [0, 0])
                    u[0] += rx_delta
                    u[1] += tx_delta
            await add_period_usage(tx.session, server_id, ps, {k: (v[0], v[1]) for k, v in by_user.items()}, now)
            await tx.session.flush()
        return len(stats)

    async def _user_ids(self, tx: Any, server_id: str, client_ids: list[str]) -> dict[str, str]:
        """client_id (pubkey/uuid) → user_id владельца устройства (для пер-user учёта трафика)."""
        rows = (
            await tx.session.execute(
                select(m.DeviceConfig.client_id, m.Device.user_id)
                .join(m.Device, m.Device.id == m.DeviceConfig.device_id)
                .where(m.DeviceConfig.server_id == server_id, m.DeviceConfig.client_id.in_(client_ids))
            )
        ).all()
        return {cid: uid for cid, uid in rows if cid and uid}

    async def _peer_states(
        self, tx: Any, server_id: str, proto: str, client_ids: list[str]
    ) -> dict[str, m.TrafficPeerState]:
        """Состояния счётчиков по каждому client_id (O(1)-дельты вместо скана истории сэмплов)."""
        rows = (
            (
                await tx.session.execute(
                    select(m.TrafficPeerState).where(
                        m.TrafficPeerState.server_id == server_id,
                        m.TrafficPeerState.proto == proto,
                        m.TrafficPeerState.client_id.in_(client_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {r.client_id: r for r in rows}

    @staticmethod
    def _apply_peer_state(
        state: m.TrafficPeerState, st: PeerStat, dc_id: str | None, rx_delta: int, tx_delta: int, now: float
    ) -> None:
        """Обновить state последним замером; скорость — из дельты по интервалу от прошлого замера."""
        interval = now - state.last_at
        if state.last_at > 0 and interval > 0:
            state.rx_speed = rx_delta / interval
            state.tx_speed = tx_delta / interval
        state.rx_bytes, state.tx_bytes, state.last_at = st.rx, st.tx, now
        lh = state.last_handshake
        if st.last_handshake is not None and (lh is None or st.last_handshake > lh):
            state.last_handshake = st.last_handshake
        state.online = st.online
        if st.name:  # имя из clientsTable добираем непустым (у части замеров может отсутствовать)
            state.ext_name = st.name
        if dc_id:
            state.device_config_id = dc_id

    async def _upsert_peer_state(
        self,
        tx: Any,
        server_id: str,
        proto: str,
        st: PeerStat,
        state: m.TrafficPeerState | None,
        dc_id: str | None,
        rx_delta: int,
        tx_delta: int,
        now: float,
    ) -> None:
        """Обновить/создать peer_state клиента.

        Вставка — в savepoint: гонка конкурентных record() → IntegrityError по
        traffic_peer_state_uq → перечитываем строку и обновляем (паттерн add_period_usage).
        """
        if state is not None:
            self._apply_peer_state(state, st, dc_id, rx_delta, tx_delta, now)
            return
        fresh = m.TrafficPeerState(
            server_id=server_id,
            proto=proto,
            client_id=st.client_id,
            device_config_id=dc_id,
            ext_name=st.name or None,
            rx_bytes=st.rx,
            tx_bytes=st.tx,
            last_at=now,
            last_handshake=st.last_handshake,
            online=st.online,
        )
        try:
            async with tx.session.begin_nested():
                tx.session.add(fresh)
        except IntegrityError:  # параллельный тик успел вставить строку — обновляем её
            row = (
                await tx.session.execute(
                    select(m.TrafficPeerState).where(
                        m.TrafficPeerState.server_id == server_id,
                        m.TrafficPeerState.proto == proto,
                        m.TrafficPeerState.client_id == st.client_id,
                    )
                )
            ).scalar_one()
            self._apply_peer_state(row, st, dc_id, rx_delta, tx_delta, now)

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

        clients = _aggregate_clients(samples, names, now, online_window)
        series = [
            {"at": s.at, "proto": s.proto, "clientId": s.client_id, "rx": s.rx_delta, "tx": s.tx_delta} for s in samples
        ]
        return {
            "serverId": sid,
            "period": period if period in _PERIODS else _DEFAULT_PERIOD,
            "onlineWindowSeconds": online_window,
            "clients": sorted(clients, key=lambda c: c["rxTotal"] + c["txTotal"], reverse=True),
            "series": series,
        }

    async def global_overview(self, owner_id: str, period: str = _DEFAULT_PERIOD) -> dict:
        """Глобальный супер-мониторинг: агрегаты по клиентам ВСЕХ серверов владельца.

        Одна выборка сэмплов по всем серверам владельца за период → per-(server,proto,client) агрегаты
        (имя пользователя/устройства, протокол, сервер, онлайн, скачал/отдал, текущая скорость,
        последний онлайн) + сводка (онлайн-клиентов, суммарный трафик, число серверов).
        """
        window = _PERIODS.get(period, _PERIODS[_DEFAULT_PERIOD])
        now = time.time()
        since = now - window
        online_window = self.settings.traffic_online_window_seconds
        async with self.uow.query() as tx:
            server_rows = list(
                (
                    await tx.session.execute(
                        select(m.Server.id, m.Server.name).where(m.Server.owner_user_id == owner_id)
                    )
                ).all()
            )
            server_names: dict[str, str] = {row[0]: row[1] for row in server_rows}
            samples: list[m.TrafficSample] = []
            if server_names:
                samples = list(
                    (
                        await tx.session.execute(
                            select(m.TrafficSample)
                            .where(
                                m.TrafficSample.server_id.in_(list(server_names)),
                                m.TrafficSample.at >= since,
                            )
                            .order_by(m.TrafficSample.at.asc())
                        )
                    )
                    .scalars()
                    .all()
                )
            names = await self._names(tx, samples)

        # агрегируем отдельно по каждому серверу (client_id уникален в рамках сервера-протокола),
        # затем сшиваем в единый список с колонкой «сервер».
        clients: list[dict] = []
        for sid, sid_samples in _group_by_server(samples).items():
            for agg in _aggregate_clients(sid_samples, names, now, online_window):
                agg["serverId"] = sid
                agg["serverName"] = server_names.get(sid, "")
                clients.append(agg)
        clients.sort(key=lambda c: c["rxTotal"] + c["txTotal"], reverse=True)

        online_now = sum(1 for c in clients if c["online"])
        rx_total = sum(c["rxTotal"] for c in clients)
        tx_total = sum(c["txTotal"] for c in clients)
        return {
            "period": period if period in _PERIODS else _DEFAULT_PERIOD,
            "onlineWindowSeconds": online_window,
            "summary": {
                "clientsTotal": len(clients),
                "clientsOnline": online_now,
                "serversTotal": len(server_names),
                "rxTotal": rx_total,
                "txTotal": tx_total,
            },
            "clients": clients,
        }

    async def _names(self, tx: Any, samples: list[m.TrafficSample]) -> dict[str, tuple[str, str, str]]:
        """DeviceConfig.id → (имя устройства, имя пользователя, статус конфига) для нон-external клиентов."""
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
        out: dict[str, tuple[str, str, str]] = {}
        for cfg, dev, usr in rows:
            out[cfg.id] = (dev.name if dev else "", usr.name if usr else "", cfg.status)
        return out

    async def purge_old(self) -> int:
        """Удалить сэмплы старше `traffic_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.traffic_retention_days * 86400
        async with self.uow.transaction() as tx:
            res: Any = await tx.session.execute(sa_delete(m.TrafficSample).where(m.TrafficSample.at < cutoff))
            return int(res.rowcount or 0)
