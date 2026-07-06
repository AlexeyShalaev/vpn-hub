"""Чистые парсеры per-client трафика по протоколам (без SSH/IO — легко тестируются).

Коллектор (services/traffic → TrafficCollector) только ЧИТАЕТ stats у каждого протокола и
отдаёт сырой вывод сюда на разбор. Здесь — только текст→список замеров, никаких побочных эффектов.

Замер одного клиента — `ClientTraffic(client_id, rx, tx, online)`:
- rx — байт клиент→сервер (upload), кумулятивно (как отдаёт движок);
- tx — байт сервер→клиент (download), кумулятивно;
- online — активна ли сессия прямо сейчас (из online-счётчика движка), либо None если неизвестно.

Кумулятив (а не дельта): коллектор читает stats БЕЗ сброса счётчиков (xray -reset=false,
hysteria /traffic без ?clear=1), поэтому TrafficService.record сам посчитает дельты — как для wg.

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
