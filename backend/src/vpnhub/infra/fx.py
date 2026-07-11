"""Курсы валют (для подбора тарифов в единой валюте). Источник — ЦБ РФ, с кэшем.

Кэш in-memory (cashews `mem://`) с TTL, чтобы не дёргать внешний API на каждый запрос дашборда.
При недоступности источника — отдаём последний кэш (stale) или зашитый fallback, чтобы UI работал
всегда. Курс нормализован к RUB: `rates[X]` = сколько RUB за 1 единицу валюты X (RUB → 1).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import structlog
from cashews import Cache

from vpnhub.infra.provider_plans.http import _fetch_url

log = structlog.get_logger(__name__)

_CBR_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
_TIMEOUT = 10.0
_FRESH_TTL_S = 12 * 60 * 60  # обновляем курс дважды в сутки
_STALE_TTL_S = 7 * 24 * 60 * 60  # держим последний удачный курс неделю как fallback
_FALLBACK_TTL_S = 5 * 60  # короткий негативный кэш: при холодном старте с недоступным ЦБ не долбим API
_CACHE_KEY = "fx:rates:rub"

# грубый зашитый fallback (используется только если и сеть, и stale-кэш недоступны)
_FALLBACK: dict[str, float] = {"RUB": 1.0, "USD": 90.0, "EUR": 98.0}

_cache = Cache()
_cache.setup("mem://")
_lock = asyncio.Lock()


def _parse_cbr(text: str) -> dict[str, float]:
    """Разобрать daily_json.js ЦБ → {код: RUB за 1 единицу}. RUB всегда 1."""
    doc = json.loads(text)
    valute = doc.get("Valute", {})
    rates: dict[str, float] = {"RUB": 1.0}
    for code, info in valute.items():
        try:
            value = float(info["Value"])
            nominal = float(info.get("Nominal", 1)) or 1.0
        except (KeyError, TypeError, ValueError):
            continue
        rates[code] = value / nominal
    return rates


async def get_rates() -> dict[str, Any]:
    """Курсы к RUB (кэш → сеть → stale → fallback). Возвращает {base, rates, at, source}."""
    fresh: dict[str, Any] | None = await _cache.get(f"{_CACHE_KEY}:fresh")
    if fresh:
        return fresh
    async with _lock:  # один сетевой запрос на всех, пока кэш пуст
        cached: dict[str, Any] | None = await _cache.get(f"{_CACHE_KEY}:fresh")
        if cached:
            return cached
        try:
            text = await _fetch_url(_CBR_URL, _TIMEOUT)
            rates = _parse_cbr(text)
        except Exception as e:  # сеть/парсинг: отдаём stale или fallback, UI не должен падать
            log.warning("fx rates fetch failed", error=str(e))
            stale: dict[str, Any] | None = await _cache.get(f"{_CACHE_KEY}:stale")
            if stale:
                return {**stale, "source": "cbr-stale"}
            fallback = {"base": "RUB", "rates": dict(_FALLBACK), "at": time.time(), "source": "fallback"}
            # кэшируем fallback ненадолго под fresh-ключ (не stale!) — чтобы холодный старт при недоступном
            # ЦБ не приводил к повторному сетевому запросу на каждый вызов; удачный фетч позже перезапишет.
            await _cache.set(f"{_CACHE_KEY}:fresh", fallback, expire=_FALLBACK_TTL_S)
            return fallback
        payload = {"base": "RUB", "rates": rates, "at": time.time(), "source": "cbr"}
        await _cache.set(f"{_CACHE_KEY}:fresh", payload, expire=_FRESH_TTL_S)
        await _cache.set(f"{_CACHE_KEY}:stale", payload, expire=_STALE_TTL_S)
        return payload
