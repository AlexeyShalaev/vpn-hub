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
from .keys import PLAN_SOURCES, PlanSource, _provider_key
from .providers import ahost, beget, firstbyte, ishosting, serverspace, timeweb, ufo, ultahost, yun62
from .providers.ahost import discover_ahost_plan_urls, fetch_ahost_plans, parse_ahost_plans
from .providers.beget import fetch_beget_plans, parse_beget_plans
from .providers.firstbyte import discover_firstbyte_plan_urls, fetch_firstbyte_plans, parse_firstbyte_plans
from .providers.ishosting import discover_ishosting_plan_urls, fetch_ishosting_plans, parse_ishosting_plans
from .providers.serverspace import fetch_serverspace_plans, parse_serverspace_plans
from .providers.timeweb import fetch_timeweb_plans, parse_timeweb_plans
from .providers.ufo import discover_ufo_countries, fetch_ufo_plans, parse_ufo_plans
from .providers.ultahost import fetch_ultahost_plans, parse_ultahost_plans
from .providers.yun62 import fetch_yun62_plans, parse_yun62_plans

_COMPAT_MODULES = {
    "ahost": ahost,
    "beget": beget,
    "firstbyte": firstbyte,
    "ishosting": ishosting,
    "serverspace": serverspace,
    "timeweb": timeweb,
    "ufo": ufo,
    "ultahost": ultahost,
    "yun62": yun62,
}
for _name, _module in _COMPAT_MODULES.items():
    sys.modules.setdefault(f"{__name__}.{_name}", _module)


# id источника (см. keys.PLAN_SOURCES) → загрузчик его тарифов. Резолвится на каждый вызов через
# глобальные имена модуля, чтобы monkeypatch `provider_plans.fetch_*` в тестах продолжал работать.
_FETCHER_NAMES: dict[str, str] = {
    "firstbyte": "fetch_firstbyte_plans",
    "ufo": "fetch_ufo_plans",
    "ishosting": "fetch_ishosting_plans",
    "ahost": "fetch_ahost_plans",
    "serverspace": "fetch_serverspace_plans",
    "ultahost": "fetch_ultahost_plans",
    "62yun": "fetch_yun62_plans",
    "timeweb": "fetch_timeweb_plans",
    "beget": "fetch_beget_plans",
}


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    module = sys.modules[__name__]
    return await _plans_for(
        provider_id,
        {pid: getattr(module, name) for pid, name in _FETCHER_NAMES.items()},
    )


__all__ = [
    "PLAN_SOURCES",
    "TIB",
    "PlanSource",
    "_cached_provider_plans",
    "_provider_key",
    "ahost",
    "beget",
    "cache",
    "clear_provider_plan_cache",
    "discover_ahost_plan_urls",
    "discover_firstbyte_plan_urls",
    "discover_ishosting_plan_urls",
    "discover_ufo_countries",
    "fetch_ahost_plans",
    "fetch_beget_plans",
    "fetch_firstbyte_plans",
    "fetch_ishosting_plans",
    "fetch_serverspace_plans",
    "fetch_timeweb_plans",
    "fetch_ufo_plans",
    "fetch_ultahost_plans",
    "fetch_yun62_plans",
    "firstbyte",
    "ishosting",
    "parse_ahost_plans",
    "parse_beget_plans",
    "parse_firstbyte_plans",
    "parse_ishosting_plans",
    "parse_serverspace_plans",
    "parse_timeweb_plans",
    "parse_ufo_plans",
    "parse_ultahost_plans",
    "parse_yun62_plans",
    "plan_bandwidth_bytes",
    "plans_for",
    "serverspace",
    "timeweb",
    "ufo",
    "ultahost",
    "yun62",
]
