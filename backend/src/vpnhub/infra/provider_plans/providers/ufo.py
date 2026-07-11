"""Динамический каталог тарифов UFO Hosting."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import structlog

from ..common import _int, _norm, _speed_mbps, _tariff_name
from ..http import _fetch_url, _post_form_url

log = structlog.get_logger(__name__)

_UFO_BASE = "https://ufo.hosting"
_UFO_PLANS_URL = f"{_UFO_BASE}/vps-vds"
_UFO_AJAX_URL = f"{_UFO_BASE}/wp-admin/admin-ajax.php"
_UFO_TIMEOUT = 8.0
_UFO_NONCE_RE = re.compile(r"\bnonce\s*:\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class _UfoCountry:
    slug: str
    name: str


@dataclass
class _UfoPlanCard:
    name: str = ""
    region: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    price: int | None = None


class _UfoLandingParser(HTMLParser):
    """Достаёт страны UFO из dropdown на странице VPS."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.countries: list[_UfoCountry] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "li":
            return
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())
        slug = attrs_d.get("data-value", "").strip()
        country = _norm(attrs_d.get("data-country", ""))
        if "dropdown-option" not in classes or not slug or not country or slug in self._seen:
            return
        self._seen.add(slug)
        self.countries.append(_UfoCountry(slug=slug, name=country))


class _UfoPlanCardParser(HTMLParser):
    """Парсер карточек тарифов UFO (`serv-card-v`) из стартового HTML и AJAX-фрагментов."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_UfoPlanCard] = []
        self._card: _UfoPlanCard | None = None
        self._card_depth = 0
        self._in_h3 = False
        self._spec_label: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())

        if self._card is None and tag == "div" and {"serv-card", "serv-card-v"}.issubset(classes):
            self._card = _UfoPlanCard()
            self._card_depth = 1
            self._spec_label = None
            return

        if self._card is None:
            return

        if tag == "div":
            self._card_depth += 1
        if tag == "h3":
            self._in_h3 = True
        if price := attrs_d.get("data-base-price"):
            self._card.price = _int(price)

    def handle_data(self, data: str) -> None:
        if self._card is None:
            return
        text = _norm(data)
        if not text:
            return

        if self._in_h3:
            self._card.name = _norm(f"{self._card.name} {text}")
            return

        if text.lower().startswith("страна "):
            self._card.region = _norm(re.sub(r"^страна\s+", "", text, flags=re.IGNORECASE))
            self._spec_label = None
            return

        label = _ufo_spec_label(text)
        if label is not None:
            self._spec_label = label
            return

        if self._spec_label:
            self._card.specs.setdefault(self._spec_label, text)
            self._spec_label = None

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "h3":
            self._in_h3 = False
            return
        if tag != "div":
            return
        self._card_depth -= 1
        if self._card_depth <= 0:
            self.cards.append(self._card)
            self._card = None
            self._card_depth = 0
            self._in_h3 = False
            self._spec_label = None


def _ufo_spec_label(text: str) -> str | None:
    label = _norm(text).rstrip(":").lower()
    return {
        "cpu": "cpu",
        "ram": "ram",
        "ssd": "disk",
        "hdd": "disk",
        "nvme": "disk",
        "сеть": "network",
        "network": "network",
    }.get(label)


def _ufo_tariff_name(text: str) -> str:
    name = re.sub(r"^тариф\s+", "", _norm(text), flags=re.IGNORECASE)
    return _tariff_name(name)


def _ufo_slug(text: str) -> str:
    known = {
        "россия": "russia",
        "индия": "india",
        "казахстан": "kazakhstan",
    }
    low = _norm(text).lower()
    if low in known:
        return known[low]
    slug = re.sub(r"[^a-z0-9]+", "-", low).strip("-")
    if slug:
        return slug
    return text.encode("utf-8").hex()


def _ufo_plan_id(region: str, tariff: str) -> str:
    tariff_slug = re.sub(r"[^a-z0-9]+", "-", tariff.lower()).strip("-")
    return f"ufo-{_ufo_slug(region)}-{tariff_slug}"


def _ufo_quantity_gb(text: str) -> float | None:
    low = text.lower().replace(",", ".")
    if not (m := re.search(r"(\d+(?:\.\d+)?)\s*(tb|тб|gb|гб|mb|мб)", low)):
        return None
    value = float(m.group(1))
    unit = m.group(2)
    if unit in {"tb", "тб"}:
        value *= 1024
    elif unit in {"mb", "мб"}:
        value /= 1024
    return int(value) if value.is_integer() else round(value, 2)


def _ufo_disk_type(text: str) -> str:
    up = text.upper()
    if "NVME" in up:
        return "NVMe"
    if "SSD" in up:
        return "SSD"
    if "HDD" in up:
        return "HDD"
    return ""


def _ufo_port_mbps(text: str) -> int | None:
    low = text.lower().replace(",", ".")
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:gbps|gbit|гбит|гб/с)", low):
        return int(float(m.group(1)) * 1000)
    return _speed_mbps(text)


def _ufo_card_to_plan(card: _UfoPlanCard, source_url: str) -> dict[str, Any] | None:
    tariff = _ufo_tariff_name(card.name)
    region = card.region
    cpu = _int(card.specs.get("cpu", ""))
    ram = _ufo_quantity_gb(card.specs.get("ram", ""))
    disk_text = card.specs.get("disk", "")
    disk = _ufo_quantity_gb(disk_text)
    port = _ufo_port_mbps(card.specs.get("network", ""))
    if not tariff or not region or cpu is None or ram is None or disk is None or port is None or card.price is None:
        return None
    return {
        "id": _ufo_plan_id(region, tariff),
        "name": f"{tariff} · {region}",
        "region": region,
        "cpu": cpu,
        "ramGb": ram,
        "diskGb": int(disk),
        "diskType": _ufo_disk_type(disk_text),
        "portMbps": port,
        "trafficTb": None,
        "price": card.price,
        "currency": "RUB",
        "period": "month",
        "available": True,
        "sourceUrl": source_url,
    }


def discover_ufo_countries(html: str) -> list[tuple[str, str]]:
    """Найти страны UFO, доступные в dropdown на странице VPS."""
    parser = _UfoLandingParser()
    parser.feed(html)
    return [(c.slug, c.name) for c in parser.countries]


def _ufo_nonce(html: str) -> str | None:
    if m := _UFO_NONCE_RE.search(html):
        return m.group(1)
    return None


def parse_ufo_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить тарифы UFO Hosting из стартового HTML и AJAX-фрагментов."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        parser = _UfoPlanCardParser()
        parser.feed(html)
        for card in parser.cards:
            if plan := _ufo_card_to_plan(card, url):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), int(p["price"]), str(p["id"])))


async def _fetch_ufo_country_pages(
    countries: Iterable[tuple[str, str]],
    nonce: str,
    timeout: float,
) -> dict[str, str]:
    async def one(country: tuple[str, str]) -> tuple[str, str]:
        slug, name = country
        source_url = f"{_UFO_PLANS_URL}#country={slug}"
        try:
            raw = await _post_form_url(
                _UFO_AJAX_URL,
                {
                    "action": "fetch_services_by_city",
                    "nonce": nonce,
                    "cities": slug,
                    "sort": "popular",
                },
                timeout,
            )
            payload = json.loads(raw)
            if payload.get("success") is not True:
                log.warning("provider_plans_fetch_failed", provider="ufo", country=slug, error=str(payload.get("data")))
                return source_url, ""
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            return source_url, str(data.get("vds") or "")
        except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError, json.JSONDecodeError) as exc:
            log.warning("provider_plans_fetch_failed", provider="ufo", country=slug, country_name=name, error=str(exc))
            return source_url, ""

    pairs = await asyncio.gather(*(one(c) for c in countries))
    return {url: html for url, html in pairs if html}


async def fetch_ufo_plans(timeout: float = _UFO_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать сайт UFO Hosting и вернуть текущие VPS-тарифы."""
    landing = await _fetch_url(_UFO_PLANS_URL, timeout)
    pages = {_UFO_PLANS_URL: landing}
    countries = discover_ufo_countries(landing) or [("russia", "Россия")]
    if nonce := _ufo_nonce(landing):
        pages.update(await _fetch_ufo_country_pages(countries, nonce, timeout))
    else:
        log.warning("provider_plans_nonce_missing", provider="ufo")
    return parse_ufo_plans(pages)
