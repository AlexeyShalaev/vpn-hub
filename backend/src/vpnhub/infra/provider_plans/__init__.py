"""Динамический каталог тарифных планов провайдеров.

Для поддержанных провайдеров планы не хардкодятся: при запросе `/providers/{id}/plans`
панель открывает публичные страницы провайдера, собирает актуальные CPU/RAM, диск, порт,
месячную квоту трафика и цену. Это всё ещё справочник для автозаполнения цены/квоты:
владелец может скорректировать значения после создания сервера.
"""

from __future__ import annotations

import sys
from typing import Any

from . import cache
from .cache import _cached_provider_plans, clear_provider_plan_cache
from .catalog import plans_for as _plans_for
from .common import TIB, plan_bandwidth_bytes
from .keys import _provider_key
from .providers import ahost, firstbyte, ishosting, serverspace, ufo, ultahost, yun62
from .providers.ahost import discover_ahost_plan_urls, fetch_ahost_plans, parse_ahost_plans
from .providers.firstbyte import discover_firstbyte_plan_urls, fetch_firstbyte_plans, parse_firstbyte_plans
from .providers.ishosting import discover_ishosting_plan_urls, fetch_ishosting_plans, parse_ishosting_plans
from .providers.serverspace import fetch_serverspace_plans, parse_serverspace_plans
from .providers.ufo import discover_ufo_countries, fetch_ufo_plans, parse_ufo_plans
from .providers.ultahost import fetch_ultahost_plans, parse_ultahost_plans
from .providers.yun62 import fetch_yun62_plans, parse_yun62_plans

_COMPAT_MODULES = {
    "ahost": ahost,
    "firstbyte": firstbyte,
    "ishosting": ishosting,
    "serverspace": serverspace,
    "ufo": ufo,
    "ultahost": ultahost,
    "yun62": yun62,
}
for _name, _module in _COMPAT_MODULES.items():
    sys.modules.setdefault(f"{__name__}.{_name}", _module)


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    return await _plans_for(
        provider_id,
        {
            "firstbyte": fetch_firstbyte_plans,
            "ufo": fetch_ufo_plans,
            "ishosting": fetch_ishosting_plans,
            "ahost": fetch_ahost_plans,
            "serverspace": fetch_serverspace_plans,
            "ultahost": fetch_ultahost_plans,
            "62yun": fetch_yun62_plans,
        },
    )


__all__ = [
    "TIB",
    "_cached_provider_plans",
    "_provider_key",
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
    "fetch_ultahost_plans",
    "fetch_yun62_plans",
    "firstbyte",
    "ishosting",
    "parse_ahost_plans",
    "parse_firstbyte_plans",
    "parse_ishosting_plans",
    "parse_serverspace_plans",
    "parse_ufo_plans",
    "parse_ultahost_plans",
    "parse_yun62_plans",
    "plan_bandwidth_bytes",
    "plans_for",
    "serverspace",
    "ufo",
    "ultahost",
    "yun62",
]
