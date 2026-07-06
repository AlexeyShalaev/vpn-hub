"""Чистые парсеры per-client трафика по протоколам (без SSH/IO — легко тестируются).

Коллектор (services/traffic → TrafficCollector) только ЧИТАЕТ stats у каждого протокола и
отдаёт сырой вывод сюда на разбор. Здесь — только текст→список замеров, никаких побочных эффектов.

Замер одного клиента — `ClientTraffic(client_id, rx, tx, online)`:
- rx — байт клиент→сервер (upload), кумулятивно (как отдаёт движок);
- tx — байт сервер→клиент (download), кумулятивно;
- online — активна ли сессия прямо сейчас (из online-счётчика движка), либо None если неизвестно.

Кумулятив (а не дельта): коллектор читает stats БЕЗ сброса счётчиков (xray -reset=false,
hysteria /traffic без ?clear=1), поэтому TrafficService.record сам посчитает дельты — как для wg.

Парсеры по протоколам:
- `parse_xray_stats` — per-uuid uplink/downlink/online (Xray Stats API);
- `parse_hysteria_traffic` — per-authid rx/tx/online (Hysteria2 trafficStats);
- `parse_openvpn_traffic` — per-CN Bytes Received/Sent + online из status-лога (v2 и v3);
- `parse_outline_transfer` — per-key суммарные байты из /metrics/transfer (без rx/tx-сплита и online).

Контракт устойчивости: пустой/битый ответ → пустой список (stats не включён / ошибка), не падаем.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ClientTraffic:
    """Сырой per-client замер трафика/онлайна (кумулятив, как отдаёт движок)."""

    client_id: str
    rx: int  # клиент→сервер (upload), байт, кумулятивно
    tx: int  # сервер→клиент (download), байт, кумулятивно
    online: bool | None  # активна ли сессия сейчас; None — неизвестно


def _loads(text: str) -> Any | None:
    """json.loads с проглатыванием пустого/битого ответа → None (а не исключение)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def parse_xray_stats(traffic_text: str, online_text: str | None = None) -> list[ClientTraffic]:
    """Разобрать `xray api statsquery` в per-uuid замеры.

    Ответ statsquery: {"stat":[{"name":"user>>>UUID>>>traffic>>>uplink","value":"N"},
    {"name":"user>>>UUID>>>traffic>>>downlink","value":"M"},{"name":"user>>>UUID>>>online","value":"K"}]}
    (или {} / пусто, если никого/битый). uplink=rx (client→server), downlink=tx (server→client).
    online (>0) → сессия активна. `online_text` — опциональный отдельный ответ по `>>>online`;
    если None, online берётся из общего `traffic_text` (когда pattern охватывает всё).

    Пустой/битый traffic_text → []. UUID с любым из uplink/downlink/online попадает в результат.
    """
    rx: dict[str, int] = {}
    tx: dict[str, int] = {}
    online: dict[str, bool] = {}
    _accumulate_xray(traffic_text, rx, tx, online)
    if online_text is not None:
        _accumulate_xray(online_text, rx, tx, online)
    uuids = set(rx) | set(tx) | set(online)
    return [
        ClientTraffic(
            client_id=uuid,
            rx=rx.get(uuid, 0),
            tx=tx.get(uuid, 0),
            online=online.get(uuid) if uuid in online else None,
        )
        for uuid in sorted(uuids)
    ]


def _accumulate_xray(text: str, rx: dict[str, int], tx: dict[str, int], online: dict[str, bool]) -> None:
    """Разложить один statsquery-ответ по словарям rx/tx/online (мутирует их)."""
    doc = _loads(text)
    if not isinstance(doc, dict):
        return
    stat = doc.get("stat")
    if not isinstance(stat, list):
        return
    for entry in stat:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not name.startswith("user>>>"):
            continue
        # user>>>{uuid}>>>traffic>>>uplink | user>>>{uuid}>>>traffic>>>downlink | user>>>{uuid}>>>online
        parts = name.split(">>>")
        if len(parts) < 3:
            continue
        uuid = parts[1]
        if not uuid:
            continue
        try:
            value = int(entry.get("value", 0))
        except (TypeError, ValueError):
            continue
        tail = ">>>".join(parts[2:])
        if tail == "traffic>>>uplink":
            rx[uuid] = value
        elif tail == "traffic>>>downlink":
            tx[uuid] = value
        elif tail == "online":
            online[uuid] = value > 0


def parse_hysteria_traffic(traffic_text: str, online_text: str | None = None) -> list[ClientTraffic]:
    """Разобрать Hysteria2 trafficStats API в per-authid замеры.

    /traffic → {"AUTHID":{"tx":N,"rx":M}}: tx=сервер→клиент=download, rx=клиент→сервер=upload.
    /online  → {"AUTHID":count}: count>0 → онлайн. authid = наш client_id.

    В ClientTraffic сохраняем семантику rx=upload/tx=download (как у wg/xray): rx=<rx из /traffic>,
    tx=<tx из /traffic>. Пустой/битый /traffic → [] (клиентов без трафика ещё нет в API).
    Онлайн-only клиенты (в /online, но не в /traffic) добавляются с rx=tx=0, online=True.
    """
    online = _parse_hysteria_online_map(online_text)
    traffic = _loads(traffic_text)
    out: list[ClientTraffic] = []
    seen: set[str] = set()
    if isinstance(traffic, dict):
        for authid, val in traffic.items():
            if not isinstance(val, dict):
                continue
            try:
                rx = int(val.get("rx", 0))
                tx = int(val.get("tx", 0))
            except (TypeError, ValueError):
                continue
            seen.add(authid)
            out.append(ClientTraffic(client_id=authid, rx=rx, tx=tx, online=online.get(authid)))
    # клиенты, что есть только в /online (трафика ещё нет) — тоже онлайн
    for authid, is_on in online.items():
        if authid not in seen and is_on:
            out.append(ClientTraffic(client_id=authid, rx=0, tx=0, online=True))
    return out


def _parse_hysteria_online_map(text: str | None) -> dict[str, bool]:
    """Hysteria2 /online → {authid: online?}. Пусто/битый → {}."""
    doc = _loads(text or "")
    if not isinstance(doc, dict):
        return {}
    out: dict[str, bool] = {}
    for authid, value in doc.items():
        try:
            out[authid] = int(value) > 0
        except (TypeError, ValueError):
            continue
    return out


def parse_openvpn_traffic(text: str) -> list[ClientTraffic]:
    """Разобрать OpenVPN status-лог (`status <path>`) в per-CN замеры (rx/tx кумулятивно + online).

    clientId = CN сертификата (= наш device_configs.client_id). Поддержаны оба формата секции
    CLIENT_LIST:
    - v3 (machine-readable): `CLIENT_LIST,<CN>,<real>,<virt>,<virt6>,<bytesRecv>,<bytesSent>,...`
      (после заголовка `HEADER,CLIENT_LIST,...` порядок колонок фиксирован спецификацией OpenVPN);
    - v2 (human-readable): секция `OpenVPN CLIENT LIST` → после заголовка
      `Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since` по строке на клиента.

    rx = Bytes Received (клиент→сервер, upload), tx = Bytes Sent (сервер→клиент, download) —
    семантика как у wg/xray. online=True: клиент присутствует в CLIENT_LIST. Значения кумулятивны
    (record() сам считает дельты). Дубли CN (duplicate-cn) суммируются в одну строку.

    Пустой/битый ввод / нет секции CLIENT_LIST → [] (status-лог не настроен / недоступен).
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return []
    rows = _parse_openvpn_v3(lines)
    if rows is None:
        rows = _parse_openvpn_v2(lines)
    # суммируем дубликаты CN (duplicate-cn → несколько сессий одного сертификата)
    agg: dict[str, tuple[int, int]] = {}
    for cn, rx, tx in rows:
        prx, ptx = agg.get(cn, (0, 0))
        agg[cn] = (prx + rx, ptx + tx)
    return [ClientTraffic(client_id=cn, rx=rx, tx=tx, online=True) for cn, (rx, tx) in agg.items()]


def _parse_openvpn_v3(lines: list[str]) -> list[tuple[str, int, int]] | None:
    """v3 CLIENT_LIST-строки → [(cn, rx, tx)]. Секции v3 нет → None (пробуем v2).

    Формат: `CLIENT_LIST,<CN>,<Real Address>,<Virtual Address>,<Virtual IPv6 Address>,
    <Bytes Received>,<Bytes Sent>,<Connected Since>,...` — индексы 5/6 = recv/sent.
    """
    v3 = [ln for ln in lines if ln.startswith("CLIENT_LIST,")]
    has_header = any(ln.startswith("HEADER,CLIENT_LIST,") or ln.startswith("TITLE,") for ln in lines)
    if not v3 and not has_header:
        return None
    out: list[tuple[str, int, int]] = []
    for ln in v3:
        fields = ln.split(",")
        if len(fields) < 7:
            continue
        cn = fields[1].strip()
        if not cn:
            continue
        try:
            rx = int(fields[5])
            tx = int(fields[6])
        except ValueError:
            continue
        out.append((cn, rx, tx))
    return out


def _parse_openvpn_v2(lines: list[str]) -> list[tuple[str, int, int]]:
    """v2 human-readable `OpenVPN CLIENT LIST` секция → [(cn, rx, tx)]. Нет секции → [].

    Строки клиента после заголовка `Common Name,Real Address,Bytes Received,Bytes Sent,...`
    до `ROUTING TABLE`/`GLOBAL STATS`.
    """
    if not any(ln.strip().lower().startswith("openvpn client list") for ln in lines):
        return []
    out: list[tuple[str, int, int]] = []
    in_clients = False
    for ln in lines:
        low = ln.strip().lower()
        if low.startswith("common name,"):
            in_clients = True
            continue
        if low.startswith("routing table") or low.startswith("global stats"):
            in_clients = False
            continue
        if not in_clients:
            continue
        fields = ln.split(",")
        if len(fields) < 4:
            continue
        cn = fields[0].strip()
        if not cn:
            continue
        try:
            rx = int(fields[2])
            tx = int(fields[3])
        except ValueError:
            continue
        out.append((cn, rx, tx))
    return out


def parse_outline_transfer(text: str) -> list[ClientTraffic]:
    """Разобрать Outline `GET /metrics/transfer` в per-key суммарный трафик.

    Ответ: {"bytesTransferredByUserId":{"<keyId>": <totalBytes>, ...}} (или {} — трафика нет).
    keyId = id access-key (= наш device_configs.client_id). Outline даёт ТОЛЬКО суммарные байты
    без rx/tx-сплита и без online: кладём tx=total, rx=0, online=None (см. tasks/17). Кумулятив.

    Пустой/битый ответ / нет ключа bytesTransferredByUserId → [].
    """
    doc = _loads(text)
    if not isinstance(doc, dict):
        return []
    by_user = doc.get("bytesTransferredByUserId")
    if not isinstance(by_user, dict):
        return []
    out: list[ClientTraffic] = []
    for key_id, total in by_user.items():
        try:
            total_bytes = int(total)
        except (TypeError, ValueError):
            continue
        # суммарный трафик кладём в tx (download), rx=0; online не поддержан Outline (None)
        out.append(ClientTraffic(client_id=str(key_id), rx=0, tx=total_bytes, online=None))
    return out
