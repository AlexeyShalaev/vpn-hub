"""Супер-мониторинг клиентов (owner): per-client трафик+онлайн по ВСЕМ протоколам.

Сбор врезан в monitor-тик (`HostMetricsService.collect_for`, та же SSH-сессия, что и
хост-метрики; интервал `monitor_interval`) и строго best-effort: сбой сбора не роняет тик и
не влияет на sync/revoke. Результат по протоколу — `ProtoTraffic` (замеры + статус сбора:
ok | stats_disabled | container_down | unreachable | error) — статус пишется в health-поля
ServerProtocol и показывается в UI мониторинга (честный диагноз вместо «нет данных»).
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
from dataclasses import dataclass, field, replace
from typing import Any

import structlog
from sqlalchemy import func, select
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
_PERIODS: dict[str, int] = {
    "1h": 3600,
    "24h": 86400,
    "7d": 7 * 86400,
    "30d": 30 * 86400,
    "90d": 90 * 86400,
    "365d": 365 * 86400,
}
_DEFAULT_PERIOD = "24h"

# статусы сбора трафика по протоколу (health; пишутся в ServerProtocol.traffic_status)
TRAFFIC_OK = "ok"
TRAFFIC_STATS_DISABLED = "stats_disabled"  # stats-API/status-лог не включён — данных нет by design
TRAFFIC_CONTAINER_DOWN = "container_down"  # контейнер протокола не запущен
TRAFFIC_UNREACHABLE = "unreachable"  # сервер недоступен по SSH (проставляет вызывающая сторона)
TRAFFIC_ERROR = "error"  # сбой сбора/парсинга

# заглушка health-меты сервера без installed-протоколов (или ещё не собранного)
_EMPTY_COLLECTION: dict[str, Any] = {"lastCollectedAt": None, "protocols": []}


def effective_online_window(settings: Settings) -> int:
    """Честное окно онлайна: не короче двух интервалов сбора + запас на rekey WG (~120с).

    WG-онлайн определяется свежестью handshake в последнем замере; замер устаревает на
    monitor_interval, а активный пир рукопожимается раз в ~2 мин — окно короче даёт ложный офлайн.
    """
    return max(settings.traffic_online_window_seconds, 2 * settings.monitor_interval + 60)


# Ярус хранения для СУММ трафика за период и для временного ряда (series). Свежее — из сырья
# (детально), старое — из rollup-агрегатов (дёшево). «Онлайн/скорость/кумулятив» — ВСЕГДА из
# peer_state, независимо от периода. series для длинных периодов — крупнее (меньше объём ответа).
_TOTALS_TIER = {"1h": "raw", "24h": "raw", "7d": "hourly", "30d": "hourly", "90d": "hourly", "365d": "daily"}
_SERIES_TIER = {"1h": "raw", "24h": "raw", "7d": "hourly", "30d": "daily", "90d": "daily", "365d": "daily"}
_SERIES_BUCKET_SECONDS = {"raw": 0, "hourly": 3600, "daily": 86400}


def _client_dict(
    state: m.TrafficPeerState,
    totals: tuple[int, int],
    names: dict[str, tuple[str, str, str]],
    server_names: dict[str, str],
    now: float,
    window: int,
) -> dict:
    """Собрать per-client запись дашборда: трафик за период (из яруса) + «сейчас» (из peer_state).

    rxTotal/txTotal — из выбранного яруса (totals); online/скорость/кумулятив/handshake — из peer_state
    (не зависят от периода). external — клиент без нашего DeviceConfig (заведён мимо панели).
    """
    dev, usr, cfg_status = names.get(state.device_config_id or "", ("", "", "active"))
    if state.online is not None:  # stats-протоколы (xray/hysteria2) — доверяем движку
        online = bool(state.online)
    else:  # wg — по свежести handshake
        online = state.last_handshake is not None and (now - state.last_handshake) < window
    return {
        "proto": state.proto,
        "clientId": state.client_id,
        "configId": state.device_config_id,  # для ручной паузы/старта (null у external)
        "status": cfg_status,  # active | paused | suspended | revoked
        "deviceName": dev,
        "userName": usr,
        "external": state.device_config_id is None,
        "extName": state.ext_name or "" if state.device_config_id is None else "",
        "rxTotal": totals[0],
        "txTotal": totals[1],
        "rxBytes": state.rx_bytes,
        "txBytes": state.tx_bytes,
        "lastHandshake": state.last_handshake,
        "rxSpeed": state.rx_speed if online else 0.0,  # скорость показываем только у активных
        "txSpeed": state.tx_speed if online else 0.0,
        "lastSeen": state.last_handshake,  # свежесть контакта (wg); у stats-протоколов handshake нет
        "online": online,
        "serverId": state.server_id,
        "serverName": server_names.get(state.server_id, ""),
    }


def _merge_clients(
    states: list[m.TrafficPeerState],
    totals: dict[tuple[str, str, str], tuple[int, int]],
    names: dict[str, tuple[str, str, str]],
    server_names: dict[str, str],
    now: float,
    window: int,
    since: float,
) -> list[dict]:
    """Список клиентов = peer_state, активные в периоде (last_at>=since) или с трафиком за период.

    Клиент, живой но без трафика за период, виден с нулями; давно снятый (last_at до периода и без
    трафика) — отсеивается, чтобы список не рос мёртвыми клиентами (peer_state не чистится).
    """
    out: list[dict] = []
    for st in states:
        key = (st.server_id, st.proto, st.client_id)
        t = totals.get(key)
        if t is None and st.last_at < since:
            continue  # ни трафика за период, ни активности — не показываем
        out.append(_client_dict(st, t or (0, 0), names, server_names, now, window))
    return out


@dataclass(frozen=True)
class PeerStat:
    """Сырой замер по одному клиенту (wg-dump / xray statsquery / hysteria trafficStats)."""

    client_id: str  # pubkey (wg/awg) | uuid (xray) | authid (hysteria2)
    rx: int  # кумулятивно принято (клиент→сервер, upload), байт
    tx: int  # кумулятивно отдано (сервер→клиент, download), байт
    last_handshake: float | None  # epoch; None — рукопожатий не было / протокол без handshake (xray/hysteria)
    online: bool | None = None  # активна ли сессия сейчас (из stats движка); None — определять по handshake
    name: str | None = None  # имя клиента из Amnezia clientsTable (clientName); нужно для external


@dataclass(frozen=True)
class ProtoTraffic:
    """Результат сбора по одному протоколу: замеры + статус (для health и честного диагноза в UI)."""

    proto: str
    status: str  # TRAFFIC_OK | TRAFFIC_STATS_DISABLED | TRAFFIC_CONTAINER_DOWN | TRAFFIC_UNREACHABLE | TRAFFIC_ERROR
    stats: list[PeerStat] = field(default_factory=list)  # только при status == TRAFFIC_OK (может быть пуст)
    error: str | None = None  # человекочитаемая причина для не-ok статусов


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
    async def collect(ssh: Any, spec: pc.ProtoSpec, provo: Any = None) -> ProtoTraffic:
        """Собрать замеры протокола `spec` + статус сбора (не бросает: исключение → status=error).

        - wireguard (awg/awg_legacy): `{spec.bin} show {spec.interface} dump` (rx/tx кумулятивно,
          online — по свежести handshake в overview);
        - xray (VLESS+Reality/XHTTP): `xray api statsquery -reset=false` → per-uuid uplink/downlink/online
          (кумулятив, счётчики НЕ сбрасываются — дельты считает record()); stats выключен → stats_disabled;
        - hysteria2: trafficStats API `/traffic`+`/online` (кумулятив, без ?clear=1); нет секрета →
          stats_disabled;
        - openvpn: OpenVPN status-лог → per-CN Bytes Received/Sent (кумулятив) + online по CLIENT_LIST;
          лог не найден → stats_disabled;
        - outline: `GET <apiUrl>/metrics/transfer` → per-key суммарный трафик (нужен `provo` с apiUrl);
          без материала → stats_disabled.

        Статусы `container_down`/`unreachable` проставляет вызывающая сторона (ей виден docker ps
        и доступность SSH). `provo` — уже загруженный провизионер, нужен только для outline (apiUrl).
        """
        try:
            if spec.kind == "wireguard":
                res = await ssh.container_exec(spec.container, f"{spec.bin} show {spec.interface} dump")
                if res.exit_status != 0:
                    return ProtoTraffic(spec.id, TRAFFIC_ERROR, error="wg dump недоступен")
                out = ProtoTraffic(spec.id, TRAFFIC_OK, stats=parse_wg_dump(res.stdout))
            elif spec.kind == "xray":
                out = await TrafficCollector._collect_xray(ssh, spec)
            elif spec.kind == "hysteria2":
                out = await TrafficCollector._collect_hysteria(ssh, spec)
            elif spec.kind == "openvpn":
                out = await TrafficCollector._collect_openvpn(ssh, spec)
            elif spec.kind == "outline":
                out = await TrafficCollector._collect_outline(ssh, spec, provo)
            else:
                return ProtoTraffic(spec.id, TRAFFIC_ERROR, error=f"неизвестный kind: {spec.kind}")
        except Exception as e:  # сбор best-effort: любой сбой → честный статус, не исключение
            return ProtoTraffic(spec.id, TRAFFIC_ERROR, error=str(e))
        if out.stats and spec.kind in _CLIENTS_TABLE_KINDS:
            out = replace(out, stats=await TrafficCollector._attach_names(ssh, spec, out.stats))
        return out

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
    async def _collect_openvpn(ssh: Any, spec: pc.ProtoSpec) -> ProtoTraffic:
        """Per-CN трафик+онлайн из OpenVPN status-лога (`status <path>` уже в server.conf).

        rx = Bytes Received (client→server), tx = Bytes Sent (server→client), кумулятивно.
        online = присутствие CN в CLIENT_LIST. Непустой лог = ok (даже с нулём клиентов);
        ни один кандидат-путь не читается → stats_disabled (status-лог не настроен).
        """
        for path in TrafficCollector._OVPN_STATUS_PATHS:
            res = await ssh.run(f"sudo docker exec {spec.container} cat {path} 2>/dev/null")
            if res.exit_status != 0 or not res.output.strip():
                continue
            stats = [
                PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
                for c in parse_openvpn_traffic(res.output)
            ]
            return ProtoTraffic(spec.id, TRAFFIC_OK, stats=stats)
        return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="OpenVPN status-лог не найден в контейнере")

    @staticmethod
    async def _collect_outline(ssh: Any, spec: pc.ProtoSpec, provo: Any) -> ProtoTraffic:
        """Per-key суммарный трафик через Outline Management API `GET /metrics/transfer`.

        Ходим curl-ом по SSH на localhost сервера (как сам провизионер). Материал (apiUrl) берём из
        `provo`; без провизионера/материала → stats_disabled. Outline даёт только суммарные байты:
        tx=total, rx=0, online не поддержан (None).
        """
        if not isinstance(provo, OutlineProvisioner):
            return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="нет материала Outline (apiUrl)")
        try:
            url = f"{provo._local_api()}/metrics/transfer"
        except ValueError:  # нет материала (apiUrl)
            return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="нет материала Outline (apiUrl)")
        res = await ssh.run(f'curl -sfk --max-time 20 "{url}" 2>/dev/null')
        if res.exit_status != 0:
            return ProtoTraffic(spec.id, TRAFFIC_ERROR, error="Outline Management API недоступен")
        stats = [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_outline_transfer(res.output)
        ]
        return ProtoTraffic(spec.id, TRAFFIC_OK, stats=stats)

    @staticmethod
    async def _collect_xray(ssh: Any, spec: pc.ProtoSpec) -> ProtoTraffic:
        """Per-uuid трафик+онлайн через Xray Stats API. `-reset=false` → счётчики кумулятивны.

        stats не включён / бинарь недоступен → statsquery падает → stats_disabled (авто-включение
        сделает monitor-тик; см. hostmetrics).
        """
        cmd = (
            f"sudo docker exec {spec.container} xray api statsquery "
            f"--server=127.0.0.1:{XRAY_STATS_PORT} -reset=false -pattern 'user>>>' 2>/dev/null"
        )
        res = await ssh.run(cmd)
        if res.exit_status != 0:
            return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="Xray Stats API не включён")
        stats = [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_xray_stats(res.output)
        ]
        return ProtoTraffic(spec.id, TRAFFIC_OK, stats=stats)

    @staticmethod
    async def _collect_hysteria(ssh: Any, spec: pc.ProtoSpec) -> ProtoTraffic:
        """Per-authid трафик (/traffic) + онлайн (/online) через Hysteria2 trafficStats API.

        Секрет читаем из config.yaml (`_read_stats_secret`); нет секрета (stats не включён) →
        stats_disabled. `/traffic` БЕЗ ?clear=1 → счётчики кумулятивны (дельты считает record()).
        """
        prov = HysteriaProvisioner(spec)
        secret = await prov._read_stats_secret(ssh)
        if not secret:
            return ProtoTraffic(spec.id, TRAFFIC_STATS_DISABLED, error="Hysteria2 trafficStats не включён")
        base = f'sudo docker exec {spec.container} curl -s -H "Authorization: {secret}" http://{_STATS_LISTEN}'
        traffic = await ssh.run(f"{base}/traffic 2>/dev/null")
        online = await ssh.run(f"{base}/online 2>/dev/null")
        if traffic.exit_status != 0:
            return ProtoTraffic(spec.id, TRAFFIC_ERROR, error="Hysteria2 trafficStats API недоступен")
        online_text = online.output if online.exit_status == 0 else None
        stats = [
            PeerStat(client_id=c.client_id, rx=c.rx, tx=c.tx, last_handshake=None, online=c.online)
            for c in parse_hysteria_traffic(traffic.output, online_text)
        ]
        return ProtoTraffic(spec.id, TRAFFIC_OK, stats=stats)


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
        period = period if period in _PERIODS else _DEFAULT_PERIOD
        window = _PERIODS[period]
        now = time.time()
        since = now - window
        online_window = effective_online_window(self.settings)
        totals_tier, series_tier = _TOTALS_TIER[period], _SERIES_TIER[period]
        async with self.uow.query() as tx:
            server = await tx.servers.get(sid)
            if not server or server.owner_user_id != owner_id:
                raise NotFound(key="traffic.server_not_found")
            states = await self._peer_states_for(tx, [sid])
            totals = await self._tier_totals(tx, [sid], since, totals_tier)
            series = await self._tier_series(tx, [sid], since, series_tier)
            names = await self._names(tx, [st.device_config_id for st in states])
            collection = (await self._collection_meta(tx, [sid])).get(sid, _EMPTY_COLLECTION)

        clients = _merge_clients(states, totals, names, {}, now, online_window, since)
        return {
            "serverId": sid,
            "period": period,
            "onlineWindowSeconds": online_window,
            "seriesBucketSeconds": _SERIES_BUCKET_SECONDS[series_tier],
            "collection": collection,
            "clients": sorted(clients, key=lambda c: c["rxTotal"] + c["txTotal"], reverse=True),
            "series": series,
        }

    async def global_overview(self, owner_id: str, period: str = _DEFAULT_PERIOD) -> dict:
        """Глобальный супер-мониторинг: агрегаты по клиентам ВСЕХ серверов владельца.

        Клиенты берутся из peer_state (онлайн/скорость/кумулятив «сейчас», не зависят от периода),
        трафик за период — из выбранного по периоду яруса (сырьё/hourly/daily). Плюс сводка
        (онлайн-клиентов, суммарный трафик, число серверов) и health-мета сбора per сервер.
        """
        period = period if period in _PERIODS else _DEFAULT_PERIOD
        window = _PERIODS[period]
        now = time.time()
        since = now - window
        online_window = effective_online_window(self.settings)
        totals_tier = _TOTALS_TIER[period]
        async with self.uow.query() as tx:
            server_rows = list(
                (
                    await tx.session.execute(
                        select(m.Server.id, m.Server.name).where(m.Server.owner_user_id == owner_id)
                    )
                ).all()
            )
            server_names: dict[str, str] = {row[0]: row[1] for row in server_rows}
            states: list[m.TrafficPeerState] = []
            totals: dict[tuple[str, str, str], tuple[int, int]] = {}
            collection: dict[str, dict] = {}
            if server_names:
                ids = list(server_names)
                states = await self._peer_states_for(tx, ids)
                totals = await self._tier_totals(tx, ids, since, totals_tier)
                collection = await self._collection_meta(tx, ids)
            names = await self._names(tx, [st.device_config_id for st in states])

        clients = _merge_clients(states, totals, names, server_names, now, online_window, since)
        clients.sort(key=lambda c: c["rxTotal"] + c["txTotal"], reverse=True)

        online_now = sum(1 for c in clients if c["online"])
        rx_total = sum(c["rxTotal"] for c in clients)
        tx_total = sum(c["txTotal"] for c in clients)
        return {
            "period": period,
            "onlineWindowSeconds": online_window,
            "summary": {
                "clientsTotal": len(clients),
                "clientsOnline": online_now,
                "serversTotal": len(server_names),
                "rxTotal": rx_total,
                "txTotal": tx_total,
            },
            "collection": collection,
            "clients": clients,
        }

    async def _peer_states_for(self, tx: Any, server_ids: list[str]) -> list[m.TrafficPeerState]:
        """Все состояния счётчиков по серверам (источник списка клиентов и «сейчас»-полей)."""
        if not server_ids:
            return []
        return list(
            (
                await tx.session.execute(
                    select(m.TrafficPeerState).where(m.TrafficPeerState.server_id.in_(server_ids))
                )
            )
            .scalars()
            .all()
        )

    async def _tier_totals(
        self, tx: Any, server_ids: list[str], since: float, tier: str
    ) -> dict[tuple[str, str, str], tuple[int, int]]:
        """Суммы rx/tx per (server, proto, client) за период из нужного яруса (сырьё/hourly/daily)."""
        if not server_ids:
            return {}
        model: Any
        rx_col: Any
        tx_col: Any
        if tier == "raw":
            model = m.TrafficSample
            rx_col, tx_col = m.TrafficSample.rx_delta, m.TrafficSample.tx_delta
            at_filter = m.TrafficSample.at >= since
        else:
            model = m.TrafficHourly if tier == "hourly" else m.TrafficDaily
            rx_col, tx_col = model.rx, model.tx
            at_filter = model.bucket >= since
        client_filter = model.client_id.isnot(None)
        rows = (
            await tx.session.execute(
                select(
                    model.server_id,
                    model.proto,
                    model.client_id,
                    func.sum(rx_col),
                    func.sum(tx_col),
                )
                .where(model.server_id.in_(server_ids), at_filter, client_filter)
                .group_by(model.server_id, model.proto, model.client_id)
            )
        ).all()
        return {(sid, proto, cid): (int(rx or 0), int(tx or 0)) for sid, proto, cid, rx, tx in rows}

    async def _tier_series(self, tx: Any, server_ids: list[str], since: float, tier: str) -> list[dict]:
        """Временной ряд (bucket/at, proto, clientId, rx, tx) за период из нужного яруса."""
        if not server_ids:
            return []
        if tier == "raw":
            rows = (
                await tx.session.execute(
                    select(
                        m.TrafficSample.at,
                        m.TrafficSample.proto,
                        m.TrafficSample.client_id,
                        m.TrafficSample.rx_delta,
                        m.TrafficSample.tx_delta,
                    )
                    .where(m.TrafficSample.server_id.in_(server_ids), m.TrafficSample.at >= since)
                    .order_by(m.TrafficSample.at.asc())
                )
            ).all()
        else:
            model = m.TrafficHourly if tier == "hourly" else m.TrafficDaily
            rows = (
                await tx.session.execute(
                    select(model.bucket, model.proto, model.client_id, model.rx, model.tx)
                    .where(model.server_id.in_(server_ids), model.bucket >= since)
                    .order_by(model.bucket.asc())
                )
            ).all()
        return [
            {"at": float(at), "proto": proto, "clientId": cid, "rx": rx, "tx": tx} for at, proto, cid, rx, tx in rows
        ]

    async def _collection_meta(self, tx: Any, server_ids: list[str]) -> dict[str, dict]:
        """Здоровье сбора трафика per сервер: last-collected + статус каждого installed-протокола.

        Читается из health-полей ServerProtocol (пишутся в monitor-тике). Даёт UI честный диагноз
        («точная статистика не включена» / «контейнер остановлен» / «сервер недоступен») вместо
        общей фразы «нет данных». lastCollectedAt сервера = max по его протоколам.
        """
        if not server_ids:
            return {}
        rows = (
            (
                await tx.session.execute(
                    select(m.ServerProtocol).where(
                        m.ServerProtocol.server_id.in_(server_ids),
                        m.ServerProtocol.installed.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        out: dict[str, dict] = {}
        for sp in rows:
            entry = out.setdefault(sp.server_id, {"lastCollectedAt": None, "protocols": []})
            entry["protocols"].append(
                {
                    "proto": sp.proto,
                    "status": sp.traffic_status,
                    "lastCollectedAt": sp.traffic_collected_at,
                    "error": sp.traffic_error,
                }
            )
            if sp.traffic_collected_at is not None and (
                entry["lastCollectedAt"] is None or sp.traffic_collected_at > entry["lastCollectedAt"]
            ):
                entry["lastCollectedAt"] = sp.traffic_collected_at
        return out

    async def _names(self, tx: Any, dc_id_list: list[str | None]) -> dict[str, tuple[str, str, str]]:
        """DeviceConfig.id → (имя устройства, имя пользователя, статус конфига) для нон-external клиентов."""
        dc_ids = {d for d in dc_id_list if d}
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

    # Ретеншн сырья/агрегатов вынесен в TrafficRollupService.purge_old (ярусная джоба traffic-rollup).
