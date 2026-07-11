"""Чистые парсеры «онлайн сейчас» по протоколам (без SSH/IO — легко тестируются).

Коллектор online (services/hostmetrics) только ЧИТАЕТ stats у каждого протокола одной
командой и отдаёт её вывод сюда на разбор. Здесь — только текст→число (или None), никаких
побочных эффектов. Контракт возвращаемых значений одинаков для всех парсеров:

- `int >= 0`  — известное число онлайн-клиентов;
- `None`      — «неизвестно» (stats не включён / ответ битый / бинарь недоступен). НЕ 0.

«Клиент онлайн» = один пользователь/устройство с активной сессией прямо сейчас (не трафик за
период). Правила подсчёта задокументированы в tasks/16-honest-online-stats.md.
"""

from __future__ import annotations

import json
from typing import Any


def _loads(text: str) -> Any | None:
    """json.loads с проглатыванием пустого/битого ответа → None (а не исключение)."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def parse_xray_online(text: str) -> int | None:
    """Онлайн Xray из `xray api statsquery -pattern ">>>online"`.

    Ответ: {"stat":[{"name":"user>>>EMAIL>>>online","value":"2"},...]} либо {} (никого нет),
    либо пустая строка (бинарь/API недоступен). Каждая запись `>>>online` = один пользователь;
    её value = число его онлайн-IP. Онлайн-клиентов = число записей с value>0.

    - пустой/битый вывод → None (stats не включён / ошибка);
    - {} или {"stat":null}/{"stat":[]} → 0 (API ответил, но онлайн-записей нет);
    - иначе — число записей с положительным value.
    """
    doc = _loads(text)
    if not isinstance(doc, dict):
        return None
    stat = doc.get("stat")
    if stat is None:  # {} или {"stat":null} — API жив, но пусто
        return 0
    if not isinstance(stat, list):
        return None
    online = 0
    for entry in stat:
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("name", "")).endswith(">>>online"):
            continue
        try:
            if int(entry.get("value", 0)) > 0:
                online += 1
        except (TypeError, ValueError):
            continue
    return online


def parse_hysteria_online(text: str) -> int | None:
    """Онлайн Hysteria2 из GET /online traffic-stats API.

    Ответ: {"USER": N, ...} (N — число онлайн-устройств пользователя) либо {} (никого).
    Онлайн-клиентов = число ключей с N>0. Пустой/битый ответ → None (stats не включён / ошибка).
    """
    doc = _loads(text)
    if not isinstance(doc, dict):
        return None
    online = 0
    for value in doc.values():
        try:
            if int(value) > 0:
                online += 1
        except (TypeError, ValueError):
            continue
    return online


# заголовок секции CLIENT_LIST в OpenVPN status-логе (версия 2/3):
# в v2 строки начинаются с "Common Name,...", в v3 — с "CLIENT_LIST,...".
def parse_openvpn_online(text: str) -> int | None:
    """Онлайн OpenVPN из status-лога (`status <path>` в конфиге сервера).

    Поддержаны оба формата:
    - v3 (machine-readable): строки `CLIENT_LIST,<CN>,<real>,...` — считаем их число;
    - v2 (human-readable): секция между `OPENVPN CLIENT LIST` и `ROUTING TABLE`, после
      заголовка `Common Name,...` — по одной строке на клиента.

    Пустой ввод/нет секции CLIENT_LIST → None (status-лог не настроен / недоступен).
    Секция есть, но клиентов нет → 0.
    """
    if not (text or "").strip():
        return None

    lines = text.splitlines()

    # v3: явные CLIENT_LIST-строки (не заголовок HEADER,CLIENT_LIST,...)
    v3 = [ln for ln in lines if ln.startswith("CLIENT_LIST,")]
    if v3 or any(ln.startswith("HEADER,CLIENT_LIST,") or ln.startswith("TITLE,") for ln in lines):
        return len(v3)

    # v2: секция OpenVPN CLIENT LIST … до ROUTING TABLE, строки после "Common Name,"
    lower = [ln.strip().lower() for ln in lines]
    if not any(s.startswith("openvpn client list") for s in lower):
        return None
    count = 0
    in_clients = False
    for ln in lines:
        stripped = ln.strip()
        low = stripped.lower()
        if low.startswith("common name,"):
            in_clients = True
            continue
        if low.startswith("routing table") or low.startswith("global stats"):
            in_clients = False
            continue
        if in_clients and stripped:
            count += 1
    return count
