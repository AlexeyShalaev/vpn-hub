"""Динамические каталоги тарифов BinaryLane и Mammoth Cloud (Австралия) — публичный API без токена.

Оба бренда одной компании отдают одинаковый API: `GET /v2/sizes` (vCPU, RAM в МБ, диск в ГБ, месячный
трафик в ТБ, цена AUD/мес, список регионов и регионы без остатка) и `GET /v2/regions` (код → город).
Выделенные серверы (`size_type=ded`) под VPN избыточны — пропускаем; остальные тарифы разворачиваем
по регионам, где они продаются.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from functools import partial
from typing import Any

import structlog

from ..common import make_plan, sort_plans
from ..http import _fetch_json

log = structlog.get_logger(__name__)

_TIMEOUT = 10.0
_SKIP_TYPES = frozenset({"ded"})
_REGION_COUNTRY: Mapping[str, str] = {"sin": "SG"}  # остальные регионы — в Австралии


def parse_binarylane_sizes(
    provider_id: str, pricing_url: str, sizes: Mapping[str, Any], regions: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Тарифы из ответов `/v2/sizes` и `/v2/regions` (одинаковых у BinaryLane и Mammoth)."""
    cities = {str(r.get("slug")): str(r.get("name") or r.get("slug")) for r in regions.get("regions") or []}
    plans: list[dict[str, Any]] = []
    for size in sizes.get("sizes") or []:
        if not isinstance(size, dict):
            continue
        size_type = size.get("size_type") or {}
        kind = str(size_type.get("slug", "")) if isinstance(size_type, dict) else str(size_type)
        cpu, ram_mb, disk, price = size.get("vcpus"), size.get("memory"), size.get("disk"), size.get("price_monthly")
        if kind in _SKIP_TYPES or not cpu or not ram_mb or not disk or not isinstance(price, (int, float)):
            continue
        sold_out = set(size.get("regions_out_of_stock") or [])
        transfer = size.get("transfer")
        label = f"{size_type.get('name', kind) if isinstance(size_type, dict) else kind} {size.get('slug')}"
        for slug in size.get("regions") or []:
            city = cities.get(str(slug), str(slug))
            country = _REGION_COUNTRY.get(str(slug), "AU")
            plans.append(
                make_plan(
                    plan_id=f"{provider_id}-{slug}-{size.get('slug')}",
                    name=f"{label} · {city}",
                    region=f"{city}, {country}",
                    country=country,
                    cpu=int(cpu),
                    ram_gb=float(ram_mb) / 1024,
                    disk_gb=int(disk),
                    disk_type="HDD" if kind == "hdd" else "",
                    port_mbps=0,  # скорость порта в API не публикуется
                    traffic_tb=float(transfer) if isinstance(transfer, (int, float)) and transfer > 0 else None,
                    price=round(float(price), 2),
                    currency="AUD",
                    source_url=pricing_url,
                    available=slug not in sold_out and size.get("available", True) is not False,
                )
            )
    return sort_plans(plans)


async def _fetch(provider_id: str, api: str, pricing_url: str, timeout: float = _TIMEOUT) -> list[dict[str, Any]]:
    try:
        sizes = await _fetch_json(f"{api}/v2/sizes", timeout)
        regions = await _fetch_json(f"{api}/v2/regions", timeout)
    except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider=provider_id, url=api, error=str(exc))
        return []
    if not isinstance(sizes, dict) or not isinstance(regions, dict):
        return []
    return parse_binarylane_sizes(provider_id, pricing_url, sizes, regions)


fetch_binarylane_plans = partial(
    _fetch, "binarylane", "https://api.binarylane.com.au", "https://www.binarylane.com.au/pricing"
)
fetch_mammoth_plans = partial(
    _fetch, "mammoth-cloud", "https://api.mammoth.com.au", "https://www.mammoth.com.au/pricing"
)
