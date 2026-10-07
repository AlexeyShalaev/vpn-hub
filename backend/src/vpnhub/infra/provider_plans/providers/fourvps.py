"""Динамический каталог тарифов 4VPS (4vps.su).

Сайт подгружает тарифы страны публичным POST `apitest/v1/tariffs/getTariffs` (без авторизации) с
параметрами панели и кластера; период 720 ч — это месяц, цена в рублях. Список стран и их кластеров
берётся с главной: у каждой кнопки страны есть `data-country`, `data-panel-id` и `data-cluster`.
В ответе — vCPU, RAM (ГБ, хоть поле и зовётся `ram_mib`), диск (ГБ), порт и признак `sold_out`.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from ..common import _speed_mbps, make_plan, slugify, sort_plans
from ..http import _fetch_browser_url, _post_form_url

log = structlog.get_logger(__name__)

_FOURVPS_URL = "https://4vps.su/"
_FOURVPS_API = "https://4vps.su/apitest/v1/tariffs/getTariffs"
_FOURVPS_TIMEOUT = 10.0
_FOURVPS_CONCURRENCY = 6
_FOURVPS_PERIOD_HOURS = "720"

_TAG_RE = re.compile(r"<[a-z]+\b[^>]*\bdata-cluster=\"[^\"]*\"[^>]*>", re.I)
_ATTR_RE = re.compile(r'data-(country|panel-id|cluster)="([^"]*)"')


@dataclass(frozen=True)
class _Cluster:
    country: str
    panel_id: str
    cluster: str


def discover_fourvps_clusters(html: str) -> list[_Cluster]:
    """Страны и их кластеры с главной 4VPS."""
    out: dict[tuple[str, str], _Cluster] = {}
    for tag in _TAG_RE.findall(html):
        attrs = dict(_ATTR_RE.findall(tag))
        country, panel, cluster = attrs.get("country", "").strip(), attrs.get("panel-id", ""), attrs.get("cluster", "")
        if country and panel.isdigit() and cluster.isdigit():
            out.setdefault((panel, cluster), _Cluster(country, panel, cluster))
    return list(out.values())


def parse_fourvps_tariffs(cluster: _Cluster, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Тарифы одного кластера из ответа getTariffs."""
    if payload.get("error"):
        return []
    plans: list[dict[str, Any]] = []
    for t in payload.get("data") or []:
        if not isinstance(t, dict):
            continue
        cpu, ram, disk, price = t.get("cpu_number"), t.get("ram_mib"), t.get("rom"), t.get("price")
        if not cpu or not ram or not disk or not isinstance(price, (int, float)) or price <= 0:
            continue
        ram_gb = ram / 1024 if ram >= 64 else ram  # поле зовётся ram_mib, но приходят гигабайты
        name = str(t.get("name") or t.get("id"))
        plans.append(
            make_plan(
                plan_id=f"4vps-{cluster.cluster}-{slugify(name)}",
                name=f"{name} · {cluster.country}",
                region=cluster.country,
                cpu=int(cpu),
                ram_gb=float(ram_gb),
                disk_gb=int(disk),
                disk_type="NVMe",
                port_mbps=_speed_mbps(str(t.get("eth") or "")) or 0,
                traffic_tb=None,  # квота трафика в ответе не указана
                price=float(price),
                currency="RUB",
                source_url=_FOURVPS_URL,
                available=not t.get("sold_out"),
            )
        )
    return plans


async def _load_cluster(cluster: _Cluster, sem: asyncio.Semaphore, timeout: float) -> list[dict[str, Any]]:
    form = {"panelId": cluster.panel_id, "cluster": cluster.cluster, "period": _FOURVPS_PERIOD_HOURS}
    async with sem:
        try:
            payload = json.loads(await _post_form_url(_FOURVPS_API, form, timeout))
        except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
            log.warning("provider_plans_fetch_failed", provider="4vps", url=_FOURVPS_API, error=str(exc))
            return []
    return parse_fourvps_tariffs(cluster, payload) if isinstance(payload, dict) else []


async def fetch_fourvps_plans(timeout: float = _FOURVPS_TIMEOUT) -> list[dict[str, Any]]:
    """Список стран с главной 4VPS, затем тарифы каждой страны."""
    try:
        html = await _fetch_browser_url(_FOURVPS_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="4vps", url=_FOURVPS_URL, error=str(exc))
        return []
    clusters: Sequence[_Cluster] = discover_fourvps_clusters(html)
    sem = asyncio.Semaphore(_FOURVPS_CONCURRENCY)
    results = await asyncio.gather(*(_load_cluster(c, sem, timeout) for c in clusters))
    return sort_plans(p for plans in results for p in plans)
