"""Проверка обновлений: тянет JSON-фид релизов и сравнивает версии.

Фид (`VPNHUB_UPDATE_FEED_URL`) — JSON вида:
  {"latest": "1.2.3", "releases": [{"v": "1.2.3", "date": "01.07.2026", "notes": ["…"]}, …]}

Без внешних зависимостей: stdlib urllib в отдельном потоке (сеть не блокирует event-loop).
"""

from __future__ import annotations

import asyncio
import json
import urllib.request


def parse_version(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in (v or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


async def fetch_feed(url: str, timeout: float = 6.0) -> dict:
    def _get() -> dict:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("feed URL must be http(s)")
        req = urllib.request.Request(url, headers={"User-Agent": "vpnhub-update-check"})  # noqa: S310 — схема проверена выше
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("feed is not an object")  # noqa: TRY004 — контракт фида: невалидный ответ = ValueError
        return data

    return await asyncio.to_thread(_get)
