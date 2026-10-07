"""Динамический каталог тарифов Timeweb Cloud (timeweb.cloud).

Страница VPS — Nuxt 3 с SSR: в payload `__NUXT_DATA__` лежат все готовые тарифы (`vds/fetchTariffs`:
имя, `cpu` вида «2 x 3.3 ГГц», память, диски, канал в Мбит/с, цена ₽/мес) и данные конфигуратора
(`configurator/servers`), где каждому тегу тарифа сопоставлен код локации (`ru-1`, `nl-1`, …). Локацию
тарифа берём из этой связки «тег → локация» со страницы, а код локации переводим в город константой
ниже (коды из документации Timeweb Cloud API). Трафик у Timeweb безлимитный — квоту не задаём.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from typing import Any

import structlog

from ..common import _int, _quantity_gb, _storage_type_from_text, make_plan, sort_plans
from ..http import _fetch_browser_url
from ..nuxt import find_dict_list, parse_nuxt_payload

log = structlog.get_logger(__name__)

_TIMEWEB_URL = "https://timeweb.cloud/services/vds-vps"
_TIMEWEB_TIMEOUT = 10.0

_TIMEWEB_LOCATIONS: Mapping[str, str] = {
    "ru-1": "Санкт-Петербург, Россия",
    "ru-2": "Новосибирск, Россия",
    "ru-3": "Москва, Россия",
    "ru-4": "Екатеринбург, Россия",
    "ru-5": "Казань, Россия",
    "kz-1": "Алматы, Казахстан",
    "pl-1": "Гданьск, Польша",
    "nl-1": "Амстердам, Нидерланды",
    "de-1": "Франкфурт, Германия",
    "us-4": "Нью-Йорк, США",
}
# новая локация, которой ещё нет в константе: хотя бы страна по префиксу кода
_TIMEWEB_COUNTRY_BY_PREFIX: Mapping[str, str] = {
    "ru": "Россия",
    "kz": "Казахстан",
    "pl": "Польша",
    "nl": "Нидерланды",
    "de": "Германия",
    "us": "США",
    "fi": "Финляндия",
    "tr": "Турция",
}
_SERVICE_TAGS = frozenset({"site", "cp"})


def _region(location: str) -> str:
    if location in _TIMEWEB_LOCATIONS:
        return _TIMEWEB_LOCATIONS[location]
    return _TIMEWEB_COUNTRY_BY_PREFIX.get(location.split("-", 1)[0], location)


def _is_tariff(item: dict[str, Any]) -> bool:
    return {"name", "cpu", "memory", "storage", "price", "tags"} <= item.keys()


def _tag_locations(state: Any) -> dict[str, str]:
    configurator = find_dict_list(state, lambda c: {"location", "tags", "requirements"} <= c.keys())
    out: dict[str, str] = {}
    for conf in configurator:
        for tag in conf.get("tags") or []:
            out.setdefault(str(tag), str(conf["location"]))
    return out


def _disks(storage: Any) -> tuple[int, str]:
    total = 0.0
    kind = ""
    for disk in storage if isinstance(storage, list) else []:
        if not isinstance(disk, dict):
            continue
        total += _quantity_gb(str(disk.get("size", ""))) or 0
        kind = kind or _storage_type_from_text(str(disk.get("type", "")))
    return int(total), kind


def parse_timeweb_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить тарифы Timeweb Cloud из HTML страницы VPS (Nuxt payload)."""
    plans: list[dict[str, Any]] = []
    for url, html in pages.items():
        state = parse_nuxt_payload(html)
        if state is None:
            continue
        locations = _tag_locations(state)
        for tariff in find_dict_list(state, _is_tariff):
            tags = [str(t) for t in tariff.get("tags") or [] if str(t) not in _SERVICE_TAGS]
            location = next((locations[t] for t in tags if t in locations), None)
            cpu = _int(str(tariff.get("cpu", "")))
            ram = _quantity_gb(str(tariff.get("memory", "")))
            disk_gb, disk_type = _disks(tariff.get("storage"))
            price = tariff.get("price")
            if location is None or not cpu or not ram or not disk_gb or not isinstance(price, (int, float)):
                continue
            region = _region(location)
            bandwidth = tariff.get("bandwidth")
            plans.append(
                make_plan(
                    plan_id=f"timeweb-{tariff.get('id', tariff['name'])}",
                    name=f"{tariff['name']} · {region.split(',')[0]}",
                    region=region,
                    cpu=cpu,
                    ram_gb=ram,
                    disk_gb=disk_gb,
                    disk_type=disk_type,
                    port_mbps=int(bandwidth) if isinstance(bandwidth, (int, float)) else 0,
                    traffic_tb=None,  # трафик безлимитный
                    price=float(price),
                    currency="RUB",
                    source_url=url,
                )
            )
    return sort_plans(plans)


async def fetch_timeweb_plans(timeout: float = _TIMEWEB_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать страницу VPS Timeweb Cloud и вернуть текущие тарифы по локациям."""
    try:
        html = await _fetch_browser_url(_TIMEWEB_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="timeweb", url=_TIMEWEB_URL, error=str(exc))
        return []
    return parse_timeweb_plans({_TIMEWEB_URL: html})
