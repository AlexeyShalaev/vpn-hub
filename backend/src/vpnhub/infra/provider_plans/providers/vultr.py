"""Динамический каталог тарифов Vultr (публичный API без токена).

`GET https://api.vultr.com/v2/plans` и `/v2/regions` открыты без авторизации: у плана — vCPU, RAM (МБ),
диск (ГБ), месячная квота трафика (ГБ), цена $/мес, список кодов локаций и поправки цены по локациям
(`location_cost`). У региона — город и ISO-код страны. Берём классические VPS-линейки (Regular,
High Frequency, High Performance) — GPU, выделенные и bare-metal под VPN не нужны — и разворачиваем
каждый план по его локациям, чтобы фильтр по стране в подборе работал и для Vultr. Планы только с IPv6
(`…-v6`) пропускаем: без публичного IPv4 VPN-сервер недоступен большинству клиентов.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from typing import Any

import structlog

from ..common import make_plan, sort_plans
from ..http import _fetch_json

log = structlog.get_logger(__name__)

_VULTR_API = "https://api.vultr.com/v2"
_VULTR_PRICING_URL = "https://www.vultr.com/pricing/"
_VULTR_TIMEOUT = 10.0
_VULTR_MAX_PAGES = 5

# линейка → (название продукта, тип диска)
_VULTR_TYPES: Mapping[str, tuple[str, str]] = {
    "vc2": ("Regular Performance", "SSD"),
    "vhf": ("High Frequency", "NVMe"),
    "vhp": ("High Performance", "NVMe"),
}


def _product(plan: Mapping[str, Any]) -> str:
    name, _ = _VULTR_TYPES[str(plan["type"])]
    pid = str(plan.get("id", "")).lower()
    if pid.endswith("-amd"):
        return f"{name} AMD"
    if pid.endswith("-intel"):
        return f"{name} Intel"
    return name


def _ram_label(ram_mb: float) -> str:
    gb = ram_mb / 1024
    return f"{int(gb)}GB" if gb.is_integer() else f"{gb:g}GB"


def parse_vultr_plans(plans_payload: Mapping[str, Any], regions_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Тарифы Vultr из ответов `/v2/plans` и `/v2/regions`, развёрнутые по локациям."""
    regions = {str(r["id"]): r for r in regions_payload.get("regions") or [] if isinstance(r, dict) and r.get("id")}
    out: list[dict[str, Any]] = []
    for plan in plans_payload.get("plans") or []:
        if not isinstance(plan, dict) or plan.get("type") not in _VULTR_TYPES:
            continue
        if str(plan.get("id", "")).endswith("-v6"):
            continue  # только IPv6
        cpu, ram_mb, disk = plan.get("vcpu_count"), plan.get("ram"), plan.get("disk")
        monthly = plan.get("monthly_cost")
        if not cpu or not ram_mb or not disk or not isinstance(monthly, (int, float)) or monthly <= 0:
            continue  # бесплатный/неполный план
        _, disk_type = _VULTR_TYPES[str(plan["type"])]
        bandwidth_gb = plan.get("bandwidth") or 0
        location_cost = plan.get("location_cost") or {}
        title = f"{_product(plan)} {int(cpu)}C/{_ram_label(float(ram_mb))}"
        for loc in plan.get("locations") or []:
            region = regions.get(str(loc))
            if region is None:
                continue
            city = str(region.get("city") or loc)
            country = str(region.get("country") or "")
            price = (location_cost.get(loc) or {}).get("monthly_cost", monthly)
            out.append(
                make_plan(
                    plan_id=f"vultr-{loc}-{plan['id']}",
                    name=f"{title} · {city}",
                    region=f"{city}, {country}" if country else city,
                    country=country,
                    cpu=int(cpu),
                    ram_gb=float(ram_mb) / 1024,
                    disk_gb=int(disk),
                    disk_type=disk_type,
                    port_mbps=0,  # скорость порта в API не публикуется
                    traffic_tb=round(bandwidth_gb / 1024, 3) if bandwidth_gb else None,
                    price=float(price),
                    currency="USD",
                    source_url=_VULTR_PRICING_URL,
                )
            )
    return sort_plans(out)


async def _fetch_all_plans(timeout: float) -> dict[str, Any]:
    plans: list[Any] = []
    cursor = ""
    for _ in range(_VULTR_MAX_PAGES):
        url = f"{_VULTR_API}/plans?per_page=500" + (f"&cursor={cursor}" if cursor else "")
        page = await _fetch_json(url, timeout)
        plans.extend(page.get("plans") or [])
        cursor = ((page.get("meta") or {}).get("links") or {}).get("next") or ""
        if not cursor:
            break
    return {"plans": plans}


async def fetch_vultr_plans(timeout: float = _VULTR_TIMEOUT) -> list[dict[str, Any]]:
    """Загрузить планы и регионы Vultr из публичного API."""
    try:
        plans = await _fetch_all_plans(timeout)
        regions = await _fetch_json(f"{_VULTR_API}/regions?per_page=500", timeout)
    except (TimeoutError, OSError, ValueError, AttributeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="vultr", url=_VULTR_API, error=str(exc))
        return []
    return parse_vultr_plans(plans, regions)
