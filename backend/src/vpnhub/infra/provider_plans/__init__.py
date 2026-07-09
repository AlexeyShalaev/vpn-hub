"""Динамический каталог тарифных планов провайдеров.

Для поддержанных провайдеров планы не хардкодятся: при запросе `/providers/{id}/plans`
панель открывает публичные страницы провайдера, собирает актуальные CPU/RAM, диск, порт,
месячную квоту трафика и цену. Это всё ещё справочник для автозаполнения цены/квоты:
владелец может скорректировать значения после создания сервера.
"""

from __future__ import annotations

from typing import Any

from . import ahost, cache, firstbyte, ishosting, serverspace, ufo
from .ahost import discover_ahost_plan_urls, fetch_ahost_plans, parse_ahost_plans
from .cache import _cached_provider_plans, _provider_key, clear_provider_plan_cache
from .common import TIB, plan_bandwidth_bytes
from .firstbyte import discover_firstbyte_plan_urls, fetch_firstbyte_plans, parse_firstbyte_plans
from .ishosting import discover_ishosting_plan_urls, fetch_ishosting_plans, parse_ishosting_plans
from .serverspace import fetch_serverspace_plans, parse_serverspace_plans
from .ufo import discover_ufo_countries, fetch_ufo_plans, parse_ufo_plans


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    """Планы провайдера по его id (пустой список, если каталога нет/сайт недоступен)."""
    provider = _provider_key(provider_id)
    if provider == "firstbyte":
        return await _cached_provider_plans("firstbyte", fetch_firstbyte_plans)
    if provider == "ufo":
        return await _cached_provider_plans("ufo", fetch_ufo_plans)
    if provider == "ishosting":
        return await _cached_provider_plans("ishosting", fetch_ishosting_plans)
    if provider == "ahost":
        return await _cached_provider_plans("ahost", fetch_ahost_plans)
    if provider == "serverspace":
        return await _cached_provider_plans("serverspace", fetch_serverspace_plans)
    return []


__all__ = [
    "TIB",
    "ahost",
    "cache",
    "clear_provider_plan_cache",
    "discover_ahost_plan_urls",
    "discover_firstbyte_plan_urls",
    "discover_ishosting_plan_urls",
    "discover_ufo_countries",
    "fetch_ahost_plans",
    "fetch_firstbyte_plans",
    "fetch_ishosting_plans",
    "fetch_serverspace_plans",
    "fetch_ufo_plans",
    "firstbyte",
    "ishosting",
    "parse_ahost_plans",
    "parse_firstbyte_plans",
    "parse_ishosting_plans",
    "parse_serverspace_plans",
    "parse_ufo_plans",
    "plan_bandwidth_bytes",
    "plans_for",
    "serverspace",
    "ufo",
]
