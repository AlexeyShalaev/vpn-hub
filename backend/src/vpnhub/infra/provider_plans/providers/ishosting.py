"""Динамический каталог тарифов ISHOSTING."""

from __future__ import annotations

import asyncio
import re
import urllib.error
import urllib.parse
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import structlog

from ..common import _int, _norm, _tariff_name
from ..http import _fetch_browser_url
from ..links import _IshostingLinkParser

log = structlog.get_logger(__name__)

_ISHOSTING_BASE = "https://ishosting.com"
_ISHOSTING_VPS_URL = f"{_ISHOSTING_BASE}/en/vps"
_ISHOSTING_TIMEOUT = 10.0
_ISHOSTING_FETCH_CONCURRENCY = 8
_ISHOSTING_COUNTRIES: Mapping[str, str] = {
    "ae": "UAE",
    "ar": "Argentina",
    "at": "Austria",
    "au": "Australia",
    "be": "Belgium",
    "bg": "Bulgaria",
    "br": "Brazil",
    "ca": "Canada",
    "ch": "Switzerland",
    "cl": "Chile",
    "co": "Colombia",
    "cz": "Czech Republic",
    "de": "Germany",
    "dk": "Denmark",
    "ee": "Estonia",
    "es": "Spain",
    "fi": "Finland",
    "fr": "France",
    "gb": "United Kingdom",
    "hk": "Hong Kong",
    "hu": "Hungary",
    "id": "Indonesia",
    "ie": "Ireland",
    "it": "Italy",
    "jp": "Japan",
    "kz": "Kazakhstan",
    "mx": "Mexico",
    "my": "Malaysia",
    "nl": "Netherlands",
    "no": "Norway",
    "pe": "Peru",
    "pl": "Poland",
    "ro": "Romania",
    "rs": "Serbia",
    "se": "Sweden",
    "sg": "Singapore",
    "th": "Thailand",
    "tr": "Turkey",
    "ua": "Ukraine",
    "us": "USA",
}
_ISHOSTING_PLAN_NAMES = {"Lite", "Start", "Medium", "Premium", "Elite", "Exclusive"}


@dataclass
class _IshostingPlanCard:
    name: str = ""
    region: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    price: float | None = None


class _IshostingPlanCardParser(HTMLParser):
    """Парсер основных VPS-карточек ISHOSTING из SSR-разметки Nuxt."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_IshostingPlanCard] = []
        self._card: _IshostingPlanCard | None = None
        self._card_depth = 0
        self._title_depth = 0
        self._location_depth = 0
        self._price_depth = 0
        self._price_parts: list[str] = []
        self._capture: str | None = None
        self._capture_parts: list[str] = []
        self._in_specs = False
        self._spec_value_parts: list[str] = []
        self._spec_type_parts: list[str] = []
        self._spec_capture: str | None = None
        self._tag_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())

        if self._card is None and tag == "div" and "services-list-cards-item" in classes:
            self._card = _IshostingPlanCard()
            self._card_depth = 1
            return

        if self._card is None:
            return

        if tag == "div":
            self._card_depth += 1
            if "title" in classes:
                self._title_depth = 1
            elif self._title_depth:
                self._title_depth += 1
            if "price" in classes:
                self._price_depth = 1
                self._price_parts = []
            elif self._price_depth:
                self._price_depth += 1

        if tag == "span" and "location" in classes:
            self._location_depth = 1
        elif tag == "span" and self._location_depth:
            self._location_depth += 1

        if tag == "a" and self._title_depth:
            self._capture = "title"
            self._capture_parts = []
        if tag == "ul" and "specs" in classes:
            self._in_specs = True
        if self._in_specs and tag == "li" and "specs-item" in classes:
            self._spec_value_parts = []
            self._spec_type_parts = []
        if self._in_specs and tag == "span" and "value" in classes:
            self._spec_capture = "value"
        if self._in_specs and tag == "span" and "type" in classes:
            self._spec_capture = "type"
        if (tag == "ul" and "tags" in classes) or (
            self._tag_parts is not None and tag == "li" and "tags-item" in classes
        ):
            self._tag_parts = []

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        if self._capture:
            self._capture_parts.append(data)
        if self._location_depth and _norm(data):
            self._card.region = _norm(f"{self._card.region} {data}")
        if self._price_depth:
            self._price_parts.append(data)
        if self._spec_capture == "value":
            self._spec_value_parts.append(data)
        elif self._spec_capture == "type":
            self._spec_type_parts.append(data)
        if self._tag_parts is not None and _norm(data):
            self._tag_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "a" and self._capture == "title":
            self._card.name = _norm("".join(self._capture_parts))
            self._capture = None
            self._capture_parts = []
            return
        if tag == "span" and self._location_depth:
            self._location_depth -= 1
            return
        if self._in_specs and tag == "span":
            self._spec_capture = None
            return
        if self._in_specs and tag == "li":
            spec_type = _norm("".join(self._spec_type_parts))
            spec_value = _norm("".join(self._spec_value_parts))
            if spec_type and spec_value:
                self._card.specs[spec_type.lower()] = spec_value
            self._spec_value_parts = []
            self._spec_type_parts = []
            return
        if self._in_specs and tag == "ul":
            self._in_specs = False
            return
        if self._tag_parts is not None and tag == "li":
            tag_text = _norm("".join(self._tag_parts))
            if tag_text:
                self._card.tags.append(tag_text)
            self._tag_parts = []
            return
        if self._tag_parts is not None and tag == "ul":
            self._tag_parts = None
            return
        if tag != "div":
            return
        if self._price_depth:
            self._price_depth -= 1
            if self._price_depth == 0:
                self._card.price = _price_usd(" ".join(self._price_parts))
                self._price_parts = []
        if self._title_depth:
            self._title_depth -= 1
        self._card_depth -= 1
        if self._card_depth <= 0:
            self.cards.append(self._card)
            self._card = None
            self._card_depth = 0
            self._title_depth = 0
            self._location_depth = 0
            self._price_depth = 0
            self._capture = None
            self._capture_parts = []
            self._in_specs = False
            self._spec_capture = None
            self._tag_parts = None


def _price_usd(text: str) -> float | None:
    if m := re.search(r"\$\s*(\d+(?:[.,]\d+)?)", text):
        return float(m.group(1).replace(",", "."))
    return None


def _ishosting_slug_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc and parsed.netloc.lower() not in {"ishosting.com", "www.ishosting.com"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 3 or parts[:2] != ["en", "vps"]:
        return None
    slug = parts[2].lower()
    if not re.fullmatch(r"[a-z]{2}", slug):
        return None
    return slug


def discover_ishosting_plan_urls(pages: Mapping[str, str]) -> list[str]:
    """Найти страницы VPS-локаций ISHOSTING из SSR-ссылок и статического fallback-списка."""
    slugs = set(_ISHOSTING_COUNTRIES)
    for source_url, html in pages.items():
        parser = _IshostingLinkParser(source_url)
        parser.feed(html)
        for href, _text in parser.links:
            if slug := _ishosting_slug_from_url(href):
                slugs.add(slug)
    return [f"{_ISHOSTING_VPS_URL}/{slug}" for slug in sorted(slugs)]


def _ishosting_plan_id(region: str, tariff: str) -> str:
    region_slug = re.sub(r"[^a-z0-9]+", "-", region.lower()).strip("-")
    tariff_slug = re.sub(r"[^a-z0-9]+", "-", tariff.lower()).strip("-")
    return f"ishosting-{region_slug}-{tariff_slug}"


def _ishosting_cpu(text: str) -> int | None:
    low = text.lower()
    if m := re.search(r"(\d+)\s*x\s*\d", low):
        return int(m.group(1))
    if "ghz" in low or "xeon" in low or "ryzen" in low:
        return 1
    return _int(text)


def _quantity_gb(text: str) -> float | None:
    low = text.lower().replace(",", ".")
    if not (m := re.search(r"(\d+(?:\.\d+)?)\s*(tb|тб|gb|гб|g\b|mb|мб)", low)):
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit in {"tb", "тб"}:
        value *= 1024
    elif unit in {"mb", "мб"}:
        value /= 1024
    return int(value) if value.is_integer() else round(value, 2)


def _storage_type_from_text(text: str) -> str:
    up = text.upper()
    if "NVME" in up:
        return "NVMe"
    if "SSD" in up:
        return "SSD"
    if "HDD" in up:
        return "HDD"
    if "SAS" in up:
        return "SAS"
    return ""


def _traffic_tb_any(text: str) -> float | None:
    low = text.lower()
    if "безлим" in low or "unmetered" in low or "unlimited" in low:
        return None
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(?:тб|tb)", low):
        tb = float(m.group(1).replace(",", "."))
        return int(tb) if tb.is_integer() else tb
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(?:gb|гб)", low):
        tb = float(m.group(1).replace(",", ".")) / 1024
        return int(tb) if tb.is_integer() else round(tb, 3)
    return None


def _speed_mbps(text: str) -> int | None:
    low = text.lower().replace(",", ".")
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:gbps|gbit|гбит|гб/с)", low):
        return int(float(m.group(1)) * 1000)
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:mbps|mbit|мбит|мб/с|мб|mb)", low):
        return int(float(m.group(1)))
    return None


def _ishosting_port_mbps(tags: Iterable[str]) -> int | None:
    for tag in tags:
        if "port" in tag.lower() and (port := _speed_mbps(tag)):
            return port
    return None


def _ishosting_card_to_plan(card: _IshostingPlanCard, source_url: str) -> dict[str, Any] | None:
    tariff = _tariff_name(card.name)
    region = _norm(card.region)
    if tariff not in _ISHOSTING_PLAN_NAMES:
        return None
    cpu = _ishosting_cpu(card.specs.get("cpu", ""))
    ram = _quantity_gb(card.specs.get("ram", ""))
    disk_text = card.specs.get("drive", "")
    disk = _quantity_gb(disk_text)
    port = _ishosting_port_mbps(card.tags)
    if not region or cpu is None or ram is None or disk is None or port is None or card.price is None:
        return None
    return {
        "id": _ishosting_plan_id(region, tariff),
        "name": f"{tariff} · {region}",
        "region": region,
        "cpu": cpu,
        "ramGb": ram,
        "diskGb": int(disk),
        "diskType": _storage_type_from_text(disk_text),
        "portMbps": port,
        "trafficTb": _traffic_tb_any(card.specs.get("bandwidth", "")),
        "price": card.price,
        "currency": "USD",
        "period": "month",
        "available": True,
        "sourceUrl": source_url,
    }


def parse_ishosting_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить основные VPS-тарифы ISHOSTING из SSR HTML страниц стран."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        parser = _IshostingPlanCardParser()
        parser.feed(html)
        for card in parser.cards:
            if plan := _ishosting_card_to_plan(card, url):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


async def _fetch_ishosting_pages(urls: Iterable[str], timeout: float) -> dict[str, str]:
    sem = asyncio.Semaphore(_ISHOSTING_FETCH_CONCURRENCY)

    async def one(url: str) -> tuple[str, str]:
        async with sem:
            try:
                html = await _fetch_browser_url(url, timeout)
            except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
                log.warning("provider_plans_fetch_failed", provider="ishosting", url=url, error=str(exc))
                return url, ""
            if "cf-mitigated" in html.lower() or "just a moment" in html.lower():
                log.warning(
                    "provider_plans_fetch_failed",
                    provider="ishosting",
                    url=url,
                    error="cloudflare_challenge",
                )
                return url, ""
            return url, html

    pairs = await asyncio.gather(*(one(u) for u in sorted(set(urls))))
    return {url: html for url, html in pairs if html}


async def fetch_ishosting_plans(timeout: float = _ISHOSTING_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать сайт ISHOSTING и вернуть текущие VPS-тарифы по странам."""
    try:
        landing = await _fetch_browser_url(_ISHOSTING_VPS_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="ishosting", url=_ISHOSTING_VPS_URL, error=str(exc))
        landing = ""
    urls = discover_ishosting_plan_urls({_ISHOSTING_VPS_URL: landing})
    pages = await _fetch_ishosting_pages(urls, timeout)
    return parse_ishosting_plans(pages)
