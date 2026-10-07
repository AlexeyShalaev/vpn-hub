"""Динамический каталог тарифов Cherry Servers (публичный API без токена).

`GET https://api.cherryservers.com/v1/plans` открыт без авторизации и отдаёт все продукты: у плана —
ядра, RAM и диск (ГБ), порт и месячный трафик строками («1Gbps», «5TB»), цены по циклам оплаты (берём
`Monthly`, EUR) и регионы с ISO-кодом страны и живым остатком (`stock_qty`; 0 — нет в наличии). Берём
виртуальные линейки (VPS/VDS), выделенные bare-metal-серверы под VPN избыточны.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Sequence
from typing import Any

import structlog

from ..common import _speed_mbps, _storage_type_from_text, _traffic_tb_any, make_plan, sort_plans
from ..http import _fetch_json

log = structlog.get_logger(__name__)

_CHERRY_PLANS_URL = "https://api.cherryservers.com/v1/plans"
_CHERRY_PRICING_URL = "https://www.cherryservers.com/pricing/virtual-servers"
_CHERRY_TIMEOUT = 15.0
_CHERRY_TYPES = frozenset({"vps", "vds", "arm-vds", "storage-vps", "premium-vds", "performance-vds"})


def _monthly(pricing: Any) -> float | None:
    for p in pricing if isinstance(pricing, list) else []:
        if isinstance(p, dict) and str(p.get("unit", "")).lower() == "monthly" and p.get("currency") == "EUR":
            price = p.get("price")
            if isinstance(price, (int, float)) and price > 0:
                return float(price)
    return None


def _region(location: str) -> str:
    """«Lithuania, Šiauliai» → «Šiauliai, Lithuania» (город первым, как у остальных провайдеров)."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return f"{parts[1]}, {parts[0]}" if len(parts) == 2 else location


def parse_cherry_plans(payload: Sequence[Any]) -> list[dict[str, Any]]:
    """Тарифы Cherry Servers из ответа `/v1/plans`, развёрнутые по регионам."""
    plans: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict) or item.get("type") not in _CHERRY_TYPES:
            continue
        specs = item.get("specs") or {}
        cpu = (specs.get("cpus") or {}).get("cores")
        ram = (specs.get("memory") or {}).get("total")
        disks = [d for d in specs.get("storage") or [] if isinstance(d, dict)]
        disk = sum(float(d.get("size") or 0) * int(d.get("count") or 1) for d in disks)
        price = _monthly(item.get("pricing"))
        if not cpu or not ram or not disk or price is None:
            continue
        disk_type = _storage_type_from_text(" ".join(str(d.get("type", "")) for d in disks))
        port = _speed_mbps(str((specs.get("nics") or {}).get("name", ""))) or 0
        traffic = _traffic_tb_any(str((specs.get("bandwidth") or {}).get("name", "")))
        name = str(item.get("name") or item.get("slug"))
        for reg in item.get("available_regions") or []:
            if not isinstance(reg, dict):
                continue
            region = _region(str(reg.get("location") or reg.get("region_iso_2") or ""))
            plans.append(
                make_plan(
                    plan_id=f"cherry-{str(reg.get('region_iso_2', '')).lower()}-{item.get('slug', name).lower()}",
                    name=f"{name} · {region.split(',')[0]}",
                    region=region,
                    country=str(reg.get("region_iso_2") or ""),
                    cpu=int(cpu),
                    ram_gb=float(ram),
                    disk_gb=int(disk),
                    disk_type=disk_type,
                    port_mbps=port,
                    traffic_tb=traffic,
                    price=price,
                    currency="EUR",
                    source_url=_CHERRY_PRICING_URL,
                    available=(reg.get("stock_qty") or 0) > 0,
                )
            )
    return sort_plans(plans)


async def fetch_cherry_plans(timeout: float = _CHERRY_TIMEOUT) -> list[dict[str, Any]]:
    """Загрузить планы Cherry Servers из публичного API."""
    try:
        payload = await _fetch_json(_CHERRY_PLANS_URL, timeout)
    except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="cherry-servers", url=_CHERRY_PLANS_URL, error=str(exc))
        return []
    return parse_cherry_plans(payload) if isinstance(payload, list) else []
