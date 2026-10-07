"""Динамический каталог тарифов VPS Beget (beget.com).

Страница VPS — Nuxt 3 с SSR: тарифы лежат в pinia-состоянии payload `__NUXT_DATA__`
(`services.planList.vpsPlans`): ядра, память и диск в МБ, канал в Мбит/с, цена ₽/мес и код региона.
Коды регионов переводим в город константой: `ru1` — Санкт-Петербург (подписан на самой странице),
`ru2` — Москва (вторая российская площадка Beget), `kz1` — Казахстан. Диски у VPS Beget — NVMe.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from typing import Any

import structlog

from ..common import make_plan, sort_plans
from ..http import _fetch_browser_url
from ..nuxt import find_dict_list, parse_nuxt_payload

log = structlog.get_logger(__name__)

_BEGET_URL = "https://beget.com/ru/vps"
_BEGET_TIMEOUT = 10.0

_BEGET_REGIONS: Mapping[str, str] = {
    "ru1": "Санкт-Петербург, Россия",
    "ru2": "Москва, Россия",
    "kz1": "Казахстан",
}
_BEGET_COUNTRY_BY_PREFIX: Mapping[str, str] = {"ru": "Россия", "kz": "Казахстан", "lv": "Латвия"}


def _region(code: str) -> str:
    return _BEGET_REGIONS.get(code) or _BEGET_COUNTRY_BY_PREFIX.get(code[:2], code)


def _positive(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _is_vps_plan(item: dict[str, Any]) -> bool:
    specs = item.get("specs")
    return {"name", "specs", "prices", "region"} <= item.keys() and isinstance(specs, dict) and "cpu_cores" in specs


def parse_beget_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить VPS-тарифы Beget из HTML страницы VPS (Nuxt payload)."""
    plans: list[dict[str, Any]] = []
    for url, html in pages.items():
        state = parse_nuxt_payload(html)
        if state is None:
            continue
        for item in find_dict_list(state, _is_vps_plan):
            specs = item.get("specs") or {}
            price = _positive(((item.get("prices") or {}).get("no_discount") or {}).get("month_amount"))
            cpu = _positive(specs.get("cpu_cores"))
            ram_mb = _positive(specs.get("memory_size"))
            disk_mb = _positive(specs.get("disk_size"))
            if price is None or cpu is None or ram_mb is None or disk_mb is None:
                continue
            region = _region(str(item.get("region", "")))
            port = specs.get("bandwidth_public")
            plans.append(
                make_plan(
                    plan_id=f"beget-{item['name']}",
                    name=f"{item.get('display_name') or item['name']} · {region.split(',')[0]}",
                    region=region,
                    cpu=int(cpu),
                    ram_gb=ram_mb / 1024,
                    disk_gb=int(disk_mb // 1024),
                    disk_type="NVMe",
                    port_mbps=int(port) if isinstance(port, (int, float)) else 0,
                    traffic_tb=None,  # квота трафика на странице не указана
                    price=price,
                    currency="RUB",
                    source_url=url,
                )
            )
    return sort_plans(plans)


async def fetch_beget_plans(timeout: float = _BEGET_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать страницу VPS Beget и вернуть текущие тарифы по регионам."""
    try:
        html = await _fetch_browser_url(_BEGET_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="beget", url=_BEGET_URL, error=str(exc))
        return []
    return parse_beget_plans({_BEGET_URL: html})
