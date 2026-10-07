"""Динамический каталог тарифных планов провайдеров.

Для поддержанных провайдеров планы не хардкодятся: при запросе `/providers/{id}/plans`
панель открывает публичные страницы провайдера, собирает актуальные CPU/RAM, диск, порт,
месячную квоту трафика и цену. Это всё ещё справочник для автозаполнения цены/квоты:
владелец может скорректировать значения после создания сервера.
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

from . import billmanager, cache, whmcs
from .billmanager import BillmanagerSource, fetch_billmanager_plans, parse_billmanager_export
from .cache import _cached_provider_plans, clear_provider_plan_cache
from .catalog import plans_for as _plans_for
from .common import TIB, plan_bandwidth_bytes
from .keys import PLAN_SOURCES, PlanSource, _provider_key
from .providers import (
    ahost,
    beget,
    binarylane,
    cherry,
    firstbyte,
    fourvps,
    hetzner,
    ishosting,
    linode,
    serverspace,
    timeweb,
    ufo,
    ultahost,
    vultr,
    yun62,
)
from .providers.ahost import discover_ahost_plan_urls, fetch_ahost_plans, parse_ahost_plans
from .providers.beget import fetch_beget_plans, parse_beget_plans
from .providers.billmanager_sources import BILLMANAGER_SOURCES
from .providers.binarylane import fetch_binarylane_plans, fetch_mammoth_plans, parse_binarylane_sizes
from .providers.cherry import fetch_cherry_plans, parse_cherry_plans
from .providers.firstbyte import discover_firstbyte_plan_urls, fetch_firstbyte_plans, parse_firstbyte_plans
from .providers.fourvps import discover_fourvps_clusters, fetch_fourvps_plans, parse_fourvps_tariffs
from .providers.hetzner import fetch_hetzner_plans, parse_hetzner_plans
from .providers.ishosting import discover_ishosting_plan_urls, fetch_ishosting_plans, parse_ishosting_plans
from .providers.linode import fetch_linode_plans, parse_linode_plans
from .providers.serverspace import fetch_serverspace_plans, parse_serverspace_plans
from .providers.timeweb import fetch_timeweb_plans, parse_timeweb_plans
from .providers.ufo import discover_ufo_countries, fetch_ufo_plans, parse_ufo_plans
from .providers.ultahost import fetch_ultahost_plans, parse_ultahost_plans
from .providers.vultr import fetch_vultr_plans, parse_vultr_plans
from .providers.whmcs_stores import WHMCS_STORES
from .providers.yun62 import fetch_yun62_plans, parse_yun62_plans
from .whmcs import WhmcsPage, fetch_whmcs_plans, parse_whmcs_page, parse_whmcs_plans

_COMPAT_MODULES = {
    "ahost": ahost,
    "beget": beget,
    "cherry": cherry,
    "firstbyte": firstbyte,
    "hetzner": hetzner,
    "ishosting": ishosting,
    "linode": linode,
    "serverspace": serverspace,
    "timeweb": timeweb,
    "ufo": ufo,
    "ultahost": ultahost,
    "vultr": vultr,
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
    "hetzner": "fetch_hetzner_plans",
    "vultr": "fetch_vultr_plans",
    "linode": "fetch_linode_plans",
    "cherry-servers": "fetch_cherry_plans",
    "4vps": "fetch_fourvps_plans",
    "binarylane": "fetch_binarylane_plans",
    "mammoth-cloud": "fetch_mammoth_plans",
}


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    module = sys.modules[__name__]
    fetchers: dict[str, Callable[[], Awaitable[list[dict[str, Any]]]]] = {
        pid: getattr(module, name) for pid, name in _FETCHER_NAMES.items()
    }
    # провайдеры на WHMCS: общий загрузчик + конфиг витрин (providers/whmcs_stores.py)
    fetchers.update({pid: partial(fetch_whmcs_plans, pid, pages) for pid, pages in WHMCS_STORES.items()})
    # провайдеры на BILLmanager: общий загрузчик публичного прайса (providers/billmanager_sources.py)
    fetchers.update({pid: partial(fetch_billmanager_plans, pid, src) for pid, src in BILLMANAGER_SOURCES.items()})
    return await _plans_for(provider_id, fetchers)


__all__ = [
    "BILLMANAGER_SOURCES",
    "PLAN_SOURCES",
    "TIB",
    "WHMCS_STORES",
    "BillmanagerSource",
    "PlanSource",
    "WhmcsPage",
    "_cached_provider_plans",
    "_provider_key",
    "ahost",
    "beget",
    "billmanager",
    "binarylane",
    "cache",
    "cherry",
    "clear_provider_plan_cache",
    "discover_ahost_plan_urls",
    "discover_firstbyte_plan_urls",
    "discover_fourvps_clusters",
    "discover_ishosting_plan_urls",
    "discover_ufo_countries",
    "fetch_ahost_plans",
    "fetch_beget_plans",
    "fetch_billmanager_plans",
    "fetch_binarylane_plans",
    "fetch_cherry_plans",
    "fetch_firstbyte_plans",
    "fetch_fourvps_plans",
    "fetch_hetzner_plans",
    "fetch_ishosting_plans",
    "fetch_linode_plans",
    "fetch_mammoth_plans",
    "fetch_serverspace_plans",
    "fetch_timeweb_plans",
    "fetch_ufo_plans",
    "fetch_ultahost_plans",
    "fetch_vultr_plans",
    "fetch_whmcs_plans",
    "fetch_yun62_plans",
    "firstbyte",
    "fourvps",
    "hetzner",
    "ishosting",
    "linode",
    "parse_ahost_plans",
    "parse_beget_plans",
    "parse_billmanager_export",
    "parse_binarylane_sizes",
    "parse_cherry_plans",
    "parse_firstbyte_plans",
    "parse_fourvps_tariffs",
    "parse_hetzner_plans",
    "parse_ishosting_plans",
    "parse_linode_plans",
    "parse_serverspace_plans",
    "parse_timeweb_plans",
    "parse_ufo_plans",
    "parse_ultahost_plans",
    "parse_vultr_plans",
    "parse_whmcs_page",
    "parse_whmcs_plans",
    "parse_yun62_plans",
    "plan_bandwidth_bytes",
    "plans_for",
    "serverspace",
    "timeweb",
    "ufo",
    "ultahost",
    "vultr",
    "whmcs",
    "yun62",
]
