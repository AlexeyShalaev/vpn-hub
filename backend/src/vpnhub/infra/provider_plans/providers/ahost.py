"""Динамический каталог тарифов AHost."""

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

from ..common import _int, _norm, _quantity_gb, _storage_type_from_text, _tariff_name, _traffic_tb_any
from ..http import _fetch_url
from ..links import _IshostingLinkParser
from .ufo import _ufo_slug

log = structlog.get_logger(__name__)

_AHOST_BASE = "https://ahost.eu"
_AHOST_VDS_URL = f"{_AHOST_BASE}/ru/vds-linux"
_AHOST_TIMEOUT = 8.0
_AHOST_FETCH_CONCURRENCY = 8
_AHOST_COUNTRIES: Mapping[str, str] = {
    "northmacedonia": "Cеверная Македония",
    "australia": "Австралия",
    "austria-vienna": "Австрия (Вена)",
    "austria-graz": "Австрия (Грац)",
    "united-arab-emirates": "Арабские Эмираты",
    "belgium": "Бельгия",
    "bulgaria": "Болгария",
    "unitedkingdom": "Великобритания",
    "hungary": "Венгрия",
    "germany": "Германия",
    "hongkong": "Гонконг",
    "greece": "Греция",
    "denmark": "Дания",
    "israel": "Израиль",
    "iceland": "Исландия",
    "spain": "Испания",
    "italy-milan": "Италия (Милан)",
    "italy-palermo": "Италия (Палермо)",
    "canada": "Канада",
    "latvia": "Латвия",
    "lithuania": "Литва",
    "moldova": "Молдова",
    "netherlands": "Нидерланды",
    "norway": "Норвегия",
    "poland": "Польша",
    "russia-moscow": "Россия (Москва)",
    "russia-stpetersburg": "Россия (Санкт-Петербург)",
    "romania": "Румыния",
    "serbia": "Сербия",
    "singapore": "Сингапур",
    "slovenia": "Словения",
    "usa": "США",
    "finland": "Финляндия",
    "france": "Франция",
    "croatia": "Хорватия",
    "czechrepublic": "Чехия",
    "switzerland": "Швейцария",
    "sweden": "Швеция",
    "japan": "Япония",
}
_AHOST_PLAN_NAMES = {"KVM SMART", "KVM STARTER", "KVM BASIC", "KVM ADVANCED", "KVM PREMIUM"}
_AHOST_EXCLUDED_SLUGS = {"linux"}


@dataclass
class _AhostPlanCard:
    name: str = ""
    specs: list[tuple[str, str]] = field(default_factory=list)
    price: float | None = None


class _AhostPlanCardParser(HTMLParser):
    """Парсер карточек AHost (`rate-item`) со страниц `/ru/vds-linux/<country>`."""

    def __init__(self, fallback_region: str) -> None:
        super().__init__(convert_charrefs=True)
        self.region = fallback_region
        self.cards: list[_AhostPlanCard] = []
        self._card: _AhostPlanCard | None = None
        self._card_depth = 0
        self._capture: str | None = None
        self._capture_parts: list[str] = []
        self._li_quantity = ""
        self._li_info = ""
        self._in_li = False
        self._country_title_depth = 0
        self._country_name_block_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())

        if tag == "div":
            if self._country_title_depth:
                self._country_title_depth += 1
            if self._country_name_block_depth:
                self._country_name_block_depth += 1
            if "country-description-title" in classes:
                self._country_title_depth = 1
            elif self._country_title_depth and "country-name-block" in classes:
                self._country_name_block_depth = 1
            elif self._country_name_block_depth and "name" in classes:
                self._capture = "region"
                self._capture_parts = []

        if self._card is None and tag == "div" and "rate-item" in classes:
            self._card = _AhostPlanCard()
            self._card_depth = 1
            self._in_li = False
            return

        if self._card is None:
            return

        if tag == "div":
            self._card_depth += 1
            if "rate-item_title" in classes:
                self._capture = "title"
                self._capture_parts = []
            elif "rate-item_price" in classes:
                self._capture = "price"
                self._capture_parts = []
            elif self._in_li and "quantity" in classes:
                self._capture = "quantity"
                self._capture_parts = []
            elif self._in_li and "info" in classes:
                self._capture = "info"
                self._capture_parts = []

        if tag == "li":
            self._in_li = True
            self._li_quantity = ""
            self._li_info = ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag == "div":
            text = _norm("".join(self._capture_parts))
            if self._capture == "region" and text:
                self.region = text
            elif self._card is not None and self._capture == "title":
                self._card.name = text
            elif self._card is not None and self._capture == "price":
                self._card.price = _price_eur(text)
            elif self._card is not None and self._capture == "quantity":
                self._li_quantity = text
            elif self._card is not None and self._capture == "info":
                self._li_info = text
            self._capture = None
            self._capture_parts = []

        if self._card is not None and tag == "li":
            if self._li_quantity and self._li_info:
                self._card.specs.append((self._li_quantity, self._li_info))
            self._in_li = False
            self._li_quantity = ""
            self._li_info = ""
            return

        if tag != "div":
            return

        if self._card is not None:
            self._card_depth -= 1
            if self._card_depth <= 0:
                self.cards.append(self._card)
                self._card = None
                self._card_depth = 0
                self._in_li = False
                self._li_quantity = ""
                self._li_info = ""

        if self._country_name_block_depth:
            self._country_name_block_depth -= 1
        if self._country_title_depth:
            self._country_title_depth -= 1


def _price_eur(text: str) -> float | None:
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*(?:€|eur)", text, flags=re.IGNORECASE):
        value = float(m.group(1).replace(",", "."))
        return int(value) if value.is_integer() else value
    return None


def _ahost_slug_from_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(_AHOST_BASE, url))
    if parsed.netloc.lower() not in {"ahost.eu", "www.ahost.eu"}:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 3 or parts[:2] != ["ru", "vds-linux"]:
        return None
    slug = parts[2].lower()
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        return None
    return slug


def discover_ahost_plan_urls(pages: Mapping[str, str]) -> list[str]:
    """Найти страницы VDS-локаций AHost из ссылок и статического fallback-списка."""
    slugs = set(_AHOST_COUNTRIES)
    for source_url, html in pages.items():
        parser = _IshostingLinkParser(source_url)
        parser.feed(html)
        for href, _text in parser.links:
            if (slug := _ahost_slug_from_url(href)) and slug not in _AHOST_EXCLUDED_SLUGS:
                slugs.add(slug)
    return [f"{_AHOST_VDS_URL}/{slug}" for slug in sorted(slugs)]


def _ahost_plan_id(source_url: str, region: str, tariff: str) -> str:
    region_slug = _ahost_slug_from_url(source_url) or _ufo_slug(region)
    tariff_slug = re.sub(r"[^a-z0-9]+", "-", tariff.lower()).strip("-")
    return f"ahost-{region_slug}-{tariff_slug}"


def _ahost_card_to_plan(card: _AhostPlanCard, source_url: str, region: str) -> dict[str, Any] | None:
    tariff = _tariff_name(card.name)
    if tariff not in _AHOST_PLAN_NAMES:
        return None

    cpu: int | None = None
    ram: float | None = None
    disk: float | None = None
    disk_type = ""
    traffic: float | None = None
    for quantity, info in card.specs:
        low = info.lower()
        if "процессор" in low or "cpu" in low:
            cpu = _int(quantity)
        elif "оператив" in low or "ram" in low:
            ram = _quantity_gb(quantity)
        elif "диск" in low or "drive" in low or "storage" in low:
            disk = _quantity_gb(quantity)
            disk_type = _storage_type_from_text(f"{quantity} {info}")
        elif "траф" in low or "traffic" in low or "bandwidth" in low:
            traffic = _traffic_tb_any(quantity)

    if not region or cpu is None or ram is None or disk is None or card.price is None:
        return None
    return {
        "id": _ahost_plan_id(source_url, region, tariff),
        "name": f"{tariff} · {region}",
        "region": region,
        "cpu": cpu,
        "ramGb": ram,
        "diskGb": int(disk),
        "diskType": disk_type,
        "portMbps": 0,
        "trafficTb": traffic,
        "price": card.price,
        "currency": "EUR",
        "period": "month",
        "available": True,
        "sourceUrl": source_url,
    }


def parse_ahost_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить VPS-тарифы AHost из HTML страниц стран."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        source_slug = _ahost_slug_from_url(url)
        parser = _AhostPlanCardParser(_AHOST_COUNTRIES.get(source_slug or "", ""))
        parser.feed(html)
        for card in parser.cards:
            if plan := _ahost_card_to_plan(card, url, parser.region):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


async def _fetch_ahost_pages(urls: Iterable[str], timeout: float) -> dict[str, str]:
    sem = asyncio.Semaphore(_AHOST_FETCH_CONCURRENCY)

    async def one(url: str) -> tuple[str, str]:
        async with sem:
            try:
                return url, await _fetch_url(url, timeout)
            except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
                log.warning("provider_plans_fetch_failed", provider="ahost", url=url, error=str(exc))
                return url, ""

    pairs = await asyncio.gather(*(one(u) for u in sorted(set(urls))))
    return {url: html for url, html in pairs if html}


async def fetch_ahost_plans(timeout: float = _AHOST_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать сайт AHost и вернуть текущие VPS-тарифы по странам."""
    try:
        landing = await _fetch_url(_AHOST_VDS_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="ahost", url=_AHOST_VDS_URL, error=str(exc))
        landing = ""
    urls = discover_ahost_plan_urls({_AHOST_VDS_URL: landing})
    pages = await _fetch_ahost_pages(urls, timeout)
    return parse_ahost_plans(pages)
