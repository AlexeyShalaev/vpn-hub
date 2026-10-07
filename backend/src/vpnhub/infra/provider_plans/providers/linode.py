"""Динамический каталог тарифов Akamai Cloud (Linode) — публичный API без токена.

`GET https://api.linode.com/v4/linode/types` и `/v4/regions` открыты без авторизации. У типа — vCPU,
RAM и диск (МБ), месячный трафик (ГБ), исходящий канал (Мбит/с), цена $/мес и надбавки по регионам
(`region_prices`, напр. Джакарта и Сан-Паулу дороже). Типы не привязаны к регионам, поэтому каждый
тариф разворачивается по всем «core»-регионам с Linodes — так работает фильтр локаций. Берём Nanode,
Shared (standard) и Dedicated CPU с месячной ценой; GPU/High Memory/Premium под VPN не нужны.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Mapping
from typing import Any

import structlog

from ..common import make_plan, sort_plans
from ..http import _fetch_json

log = structlog.get_logger(__name__)

_LINODE_API = "https://api.linode.com/v4"
_LINODE_PRICING_URL = "https://www.linode.com/pricing/"
_LINODE_TIMEOUT = 10.0
_LINODE_CLASSES = frozenset({"nanode", "standard", "dedicated"})


def _core_regions(regions_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in regions_payload.get("data") or []:
        if not isinstance(r, dict) or not r.get("id"):
            continue
        if r.get("site_type", "core") != "core" or r.get("status", "ok") != "ok":
            continue
        if "Linodes" not in (r.get("capabilities") or []):
            continue
        out.append(r)
    return out


def parse_linode_plans(types_payload: Mapping[str, Any], regions_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Тарифы Linode из ответов `/v4/linode/types` и `/v4/regions`, развёрнутые по регионам."""
    regions = _core_regions(regions_payload)
    out: list[dict[str, Any]] = []
    for t in types_payload.get("data") or []:
        if not isinstance(t, dict) or t.get("class") not in _LINODE_CLASSES:
            continue
        monthly = (t.get("price") or {}).get("monthly")
        cpu, ram_mb, disk_mb = t.get("vcpus"), t.get("memory"), t.get("disk")
        if not isinstance(monthly, (int, float)) or monthly <= 0 or not cpu or not ram_mb or not disk_mb:
            continue
        overrides: dict[str, float] = {
            str(rp.get("id")): float(rp["monthly"])
            for rp in t.get("region_prices") or []
            if isinstance(rp, dict) and isinstance(rp.get("monthly"), (int, float))
        }
        transfer_gb = t.get("transfer") or 0
        port = t.get("network_out") or 0
        label = str(t.get("label") or t["id"])
        for r in regions:
            rid = str(r["id"])
            region_label = str(r.get("label") or rid)
            out.append(
                make_plan(
                    plan_id=f"linode-{rid}-{t['id']}",
                    name=f"{label} · {region_label.split(',', maxsplit=1)[0]}",
                    region=region_label,
                    country=str(r.get("country") or ""),
                    cpu=int(cpu),
                    ram_gb=float(ram_mb) / 1024,
                    disk_gb=int(disk_mb) // 1024,
                    disk_type="SSD",
                    port_mbps=int(port),
                    traffic_tb=round(transfer_gb / 1000, 3) if transfer_gb else None,
                    price=overrides.get(rid, float(monthly)),
                    currency="USD",
                    source_url=_LINODE_PRICING_URL,
                )
            )
    return sort_plans(out)


async def fetch_linode_plans(timeout: float = _LINODE_TIMEOUT) -> list[dict[str, Any]]:
    """Загрузить типы и регионы Linode из публичного API."""
    try:
        types = await _fetch_json(f"{_LINODE_API}/linode/types?page_size=500", timeout)
        regions = await _fetch_json(f"{_LINODE_API}/regions?page_size=500", timeout)
    except (TimeoutError, OSError, ValueError, AttributeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="linode", url=_LINODE_API, error=str(exc))
        return []
    return parse_linode_plans(types, regions)
