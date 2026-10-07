"""Динамический каталог тарифов Hetzner Cloud.

Hetzner отдаёт тарифы в двух местах, оба без авторизации:

- server-side HTML страниц линеек `hetzner.com/cloud/<линейка>/` — по строке `cloud-matrix-product` на
  тариф: имя (CX23, CPX22, CCX13…), vCPU, RAM, диск, пометка «not available», а в блоках локаций —
  коды ДЦ (`location="NBG1,HEL1"`), включённый трафик (ТБ) и ключ цены (`product-key="CLOUD_132+CLOUD_21"`);
- JSON-фид цен сайта `live_data_prices.json`: по каждому ключу — месячная цена в EUR/USD для каждого ДЦ
  (с ISO-кодом страны и флагом active). Ключи через «+» суммируются: CLOUD_21 — обязательная надбавка
  за публичный IPv4, без которого VPN-сервер не нужен.

Каждый тариф разворачивается по ДЦ, где он продаётся; цена — в EUR за месяц (потолок почасовой оплаты).
"""

from __future__ import annotations

import asyncio
import re
import urllib.error
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from ..common import _int, _norm, _quantity_gb, _storage_type_from_text, make_plan, sort_plans
from ..http import _fetch_browser_url, _fetch_json

log = structlog.get_logger(__name__)

_HETZNER_BASE = "https://www.hetzner.com"
_HETZNER_LINES: tuple[str, ...] = ("cost-optimized", "regular-performance", "general-purpose")
_HETZNER_PRICES_URL = f"{_HETZNER_BASE}/_resources/app/data/app/live_data_prices.json"
_HETZNER_TIMEOUT = 10.0

_HETZNER_DCS: Mapping[str, str] = {
    "FSN1": "Falkenstein",
    "NBG1": "Nuremberg",
    "HEL1": "Helsinki",
    "ASH1": "Ashburn",
    "HIL1": "Hillsboro",
    "SIN1": "Singapore",
}

_ROW_SPLIT_RE = re.compile(r'<div\s+class="cloud-matrix-product(?=[\s"])')
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_PRICE_TAG_RE = re.compile(r"<ho-price-container\b([^>]*)>", re.I)
_ATTR_RE = re.compile(r'([\w-]+)=(?:"([^"]*)"|([^\s>]+))')
_KEY_RE = re.compile(r"^CLOUD_\d+(?:\+CLOUD_\d+)*$")


def _cell(row: str, name: str) -> str:
    """Видимый текст ячейки `cell <name>` (до следующей ячейки)."""
    m = re.search(rf'class="cell {name}[^"]*"(.*?)(?=class="cell |class="label-cell|$)', row, re.S)
    return _norm(_TAG_RE.sub(" ", m.group(1))) if m else ""


def _attrs(tag_attrs: str) -> dict[str, str]:
    return {k.lower(): (v1 or v2) for k, v1, v2 in _ATTR_RE.findall(tag_attrs)}


def _row_name(row: str) -> str:
    m = re.search(r'class="cell name-cell".*?<div class="no-wrap[^"]*">\s*([^<]+?)\s*<', row, re.S)
    return _norm(m.group(1)) if m else ""


def _locations(row: str, key: str) -> list[tuple[str, float | None]]:
    """[(ДЦ, трафик ТБ)] из блоков локаций строки: ДЦ — из `location=` ценника тарифа (ключ `key`;
    в том же блоке есть ценник доп. трафика CLOUD_66 с location=ALL — его пропускаем), трафик — из блока."""
    out: list[tuple[str, float | None]] = []
    for box in row.split('class="location-box')[1:]:
        dcs: list[str] = []
        for m in _PRICE_TAG_RE.finditer(box):
            attrs = _attrs(m.group(1))
            if attrs.get("product-key") == key and attrs.get("location"):
                dcs = [d.strip().upper() for d in attrs["location"].split(",") if d.strip()]
                break
        traffic = re.search(r'traffic-info-amount">\s*([\d.,]+)\s*(TB|GB)', box)
        tb = None
        if traffic:
            tb = float(traffic.group(1).replace(",", "."))
            tb = tb / 1024 if traffic.group(2) == "GB" else tb
        out.extend((dc, tb) for dc in dcs)
    return out


def _price_key(row: str) -> str:
    for m in _PRICE_TAG_RE.finditer(row):
        key = _attrs(m.group(1)).get("product-key", "")
        if _KEY_RE.match(key) and key != "CLOUD_66":
            return key
    return ""


def _dc_entry(prices: Mapping[str, Any], key: str, dc: str) -> dict[str, Any] | None:
    product = (prices.get("products") or {}).get(key) or {}
    entries = [e for e in product.get("locations") or [] if isinstance(e, dict)]
    return next((e for e in entries if e.get("datacenter") == dc), None) or next(
        (e for e in entries if e.get("datacenter") == "ALL"), None
    )


def _monthly_eur(prices: Mapping[str, Any], keys: Sequence[str], dc: str) -> tuple[float, str, bool] | None:
    """(цена EUR/мес по всем ключам, страна ДЦ, активен ли) или None, если для ДЦ нет цены."""
    total = 0.0
    country = ""
    active = True
    for key in keys:
        entry = _dc_entry(prices, key, dc)
        eur = (((entry or {}).get("prices") or {}).get("monthly") or {}).get("EUR")
        if entry is None or eur is None:
            return None
        total += float(eur)
        country = country or str(entry.get("countryCode") or "")
        active = active and entry.get("active", True) is not False
    return round(total, 2), country, active


def parse_hetzner_plans(pages: Mapping[str, str], prices: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Тарифы Hetzner Cloud из HTML страниц линеек и фида цен, развёрнутые по ДЦ."""
    plans: list[dict[str, Any]] = []
    for url, html in pages.items():
        for raw in _ROW_SPLIT_RE.split(html)[1:]:
            row = _SVG_RE.sub("", raw)
            name = _row_name(row)
            cpu = _int(_cell(row, "cpu-cell"))
            ram = _quantity_gb(_cell(row, "ram-cell"))
            drive = _cell(row, "drive-cell")
            disk = _quantity_gb(drive)
            key = _price_key(row)
            if not name or not cpu or not ram or not disk or not key:
                continue
            listed = "not-available" not in row[: row.find(">")]
            keys = key.split("+")
            for dc, traffic_tb in _locations(row, key):
                priced = _monthly_eur(prices, keys, dc)
                if priced is None:
                    continue
                price, country, active = priced
                city = _HETZNER_DCS.get(dc, dc)
                plans.append(
                    make_plan(
                        plan_id=f"hetzner-{dc.lower()}-{name.lower()}",
                        name=f"{name} · {city}",
                        region=f"{city}, {country.upper()}" if country else city,
                        country=country,
                        cpu=cpu,
                        ram_gb=ram,
                        disk_gb=int(disk),
                        disk_type=_storage_type_from_text(drive) or "NVMe",
                        port_mbps=0,  # скорость порта не публикуется
                        traffic_tb=traffic_tb,
                        price=price,
                        currency="EUR",
                        source_url=url,
                        available=listed and active,
                    )
                )
    return sort_plans(plans)


async def fetch_hetzner_plans(timeout: float = _HETZNER_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать страницы линеек Hetzner Cloud и фид цен, вернуть тарифы по ДЦ."""
    urls = [f"{_HETZNER_BASE}/cloud/{line}/" for line in _HETZNER_LINES]
    try:
        prices = await _fetch_json(_HETZNER_PRICES_URL, timeout)
    except (TimeoutError, OSError, ValueError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="hetzner", url=_HETZNER_PRICES_URL, error=str(exc))
        return []
    results = await asyncio.gather(*(_fetch_browser_url(u, timeout) for u in urls), return_exceptions=True)
    pages: dict[str, str] = {}
    for url, result in zip(urls, results, strict=True):
        if isinstance(result, BaseException):
            log.warning("provider_plans_fetch_failed", provider="hetzner", url=url, error=str(result))
        else:
            pages[url] = result
    return parse_hetzner_plans(pages, prices) if isinstance(prices, dict) else []
