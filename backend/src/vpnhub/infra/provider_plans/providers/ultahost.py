"""Динамический каталог тарифов UltaHost.

Живые/волатильные данные (тарифы, месячная цена, характеристики) снимаются с публичной витрины
магазина WHMCS `bill.ultahost.com/store/linux-vps-hosting` — это server-side HTML, который надёжно
парсится stdlib-ом (в отличие от JS-корзины `cart.php`, где выбор локации/ОС живёт за сессией).

Цена берётся за платёжный цикл «Monthly» (месяц), в USD (`currency=1`). Полоса безлимитная
(«Unmetered»), поэтому квота трафика не задаётся. Список локаций у UltaHost один и тот же для всех
тарифов (ЦОД выбирается опцией конфигурации при заказе, цена базового тарифа от локации не зависит),
поэтому он курируется здесь константой и каждый тариф разворачивается по локациям — так фильтр по
локации в подборе работает и для UltaHost. ОС по умолчанию — чистая Ubuntu (среди Debian/AlmaLinux/…).
"""

from __future__ import annotations

import re
import urllib.error
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any

import structlog

from ..common import _int, _norm, _quantity_gb, _storage_type_from_text, _traffic_tb_any
from ..http import _fetch_browser_url

log = structlog.get_logger(__name__)

_ULTAHOST_STORE_URL = "https://bill.ultahost.com/store/linux-vps-hosting?currency=1"
_ULTAHOST_TIMEOUT = 8.0

# ЦОД UltaHost (витрина /data-center). Базовая цена тарифа от локации не зависит — локация выбирается
# опцией конфигурации при заказе, поэтому список курируется здесь, а не парсится из JS-корзины.
_ULTAHOST_LOCATIONS: tuple[str, ...] = (
    "London, United Kingdom",
    "Amsterdam, Netherlands",
    "Frankfurt, Germany",
    "Paris, France",
    "Madrid, Spain",
    "Milan, Italy",
    "Zurich, Switzerland",
    "Oslo, Norway",
    "Stockholm, Sweden",
    "Warsaw, Poland",
    "New York, USA",
    "Chicago, USA",
    "Dallas, USA",
    "Seattle, USA",
    "Los Angeles, USA",
    "Toronto, Canada",
    "Mexico City, Mexico",
    "Sao Paulo, Brazil",
    "Bogota, Colombia",
    "Dubai, UAE",
    "Riyadh, Saudi Arabia",
    "Johannesburg, South Africa",
    "Lagos, Nigeria",
    "Istanbul, Turkey",
    "New Delhi, India",
    "Singapore",
    "Kuala Lumpur, Malaysia",
    "Hong Kong",
    "Seoul, South Korea",
    "Tokyo, Japan",
    "Sydney, Australia",
)


class _UltaTier:
    """Базовый тариф UltaHost до разворота по локациям."""

    __slots__ = ("cpu", "cycle", "disk_gb", "disk_type", "name", "price", "ram_gb", "traffic_tb")

    def __init__(self) -> None:
        self.name: str = ""
        self.price: float | None = None
        self.cycle: str = ""
        self.cpu: int | None = None
        self.ram_gb: float | None = None
        self.disk_gb: int | None = None
        self.disk_type: str = ""
        self.traffic_tb: float | None = None


class _UltaStoreParser(HTMLParser):
    """Парсер карточек тарифов витрины WHMCS UltaHost (тема Twenty-One).

    Карточка начинается с `<h3 class="package-title">`; первые следующие за ней `price-amount`,
    `price-cycle` и блок `package-content` относятся к ней (правая колонка `package-side-right`
    лишь дублирует цену — берём первое значение и не перезаписываем).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tiers: list[_UltaTier] = []
        self._tier: _UltaTier | None = None
        self._capture: str | None = None  # title | price | cycle | content
        self._parts: list[str] = []

    def _start_capture(self, kind: str) -> None:
        self._capture = kind
        self._parts = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "h3" and "package-title" in classes:
            # новая карточка
            if self._tier is not None:
                self.tiers.append(self._tier)
            self._tier = _UltaTier()
            self._start_capture("title")
            return
        if self._tier is None:
            return
        if tag == "div" and "price-amount" in classes and self._tier.price is None:
            self._start_capture("price")
        elif tag == "div" and "price-cycle" in classes and not self._tier.cycle:
            self._start_capture("cycle")
        elif tag == "div" and "package-content" in classes and self._tier.cpu is None:
            self._start_capture("content")
        elif self._capture == "content" and tag == "br":
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture is None or self._tier is None:
            return
        # заголовок/цена/цикл закрываются своим же тегом; контент — закрывающим div,
        # но <p>/<b>/<br> внутри контента не должны его завершать.
        if self._capture == "title" and tag == "h3":
            self._tier.name = _norm("".join(self._parts))
            self._capture = None
        elif self._capture == "price" and tag == "div":
            self._tier.price = _ulta_price("".join(self._parts))
            self._capture = None
        elif self._capture == "cycle" and tag == "div":
            self._tier.cycle = _norm("".join(self._parts)).lower()
            self._capture = None
        elif self._capture == "content" and tag == "div":
            _apply_specs(self._tier, "".join(self._parts))
            self._capture = None

    def close(self) -> None:
        super().close()
        if self._tier is not None:
            self.tiers.append(self._tier)
            self._tier = None


def _ulta_price(text: str) -> float | None:
    # WHMCS (currency=1, USD) отдаёт цену в формате "$1,234.56": запятая — разделитель тысяч, точка —
    # десятичная. Нельзя слепо менять запятую на точку — иначе "$1,299.00" распарсится как 1.299.
    if m := re.search(r"\d[\d,]*(?:\.\d+)?", text):
        return float(m.group(0).replace(",", ""))
    return None


def _apply_specs(tier: _UltaTier, content: str) -> None:
    for raw in content.split("\n"):
        line = _norm(raw)
        if not line:
            continue
        low = line.lower()
        if tier.cpu is None and ("cpu" in low or "vcpu" in low or "core" in low):
            tier.cpu = _int(line)
        elif tier.ram_gb is None and "ram" in low:
            tier.ram_gb = _quantity_gb(line)
        elif tier.disk_gb is None and ("ssd" in low or "nvme" in low or "hdd" in low or "disk" in low):
            gb = _quantity_gb(line)
            if gb is not None:
                tier.disk_gb = int(gb)
                tier.disk_type = _storage_type_from_text(line) or "NVMe"
        elif "bandwidth" in low or "traffic" in low or "трафик" in low:
            tier.traffic_tb = _traffic_tb_any(line)


def _ulta_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or text.encode("utf-8").hex()


def _tier_to_plans(tier: _UltaTier, source_url: str) -> list[dict[str, Any]]:
    # берём только тарифы с месячным циклом и полным набором характеристик
    if "month" not in tier.cycle:
        return []
    if not tier.name or tier.price is None or tier.cpu is None or tier.ram_gb is None or tier.disk_gb is None:
        return []
    tier_slug = _ulta_slug(tier.name)
    plans: list[dict[str, Any]] = []
    for region in _ULTAHOST_LOCATIONS:
        plans.append(
            {
                "id": f"ulta-{_ulta_slug(region)}-{tier_slug}",
                "name": f"{tier.name} · {region}",
                "region": region,
                "cpu": tier.cpu,
                "ramGb": tier.ram_gb,
                "diskGb": tier.disk_gb,
                "diskType": tier.disk_type or "NVMe",
                "portMbps": 0,  # полоса безлимитная, скорость порта не публикуется
                "trafficTb": tier.traffic_tb,  # «Unmetered» → None (безлимит)
                "price": tier.price,
                "currency": "USD",
                "period": "month",
                "available": True,
                "sourceUrl": source_url,
            }
        )
    return plans


def parse_ultahost_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить тарифы UltaHost из уже скачанного HTML витрины магазина."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        parser = _UltaStoreParser()
        parser.feed(html)
        parser.close()
        for tier in parser.tiers:
            for plan in _tier_to_plans(tier, url):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


async def fetch_ultahost_plans(timeout: float = _ULTAHOST_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать витрину UltaHost и вернуть текущие VPS-тарифы (развёрнутые по локациям)."""
    try:
        html = await _fetch_browser_url(_ULTAHOST_STORE_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="ultahost", url=_ULTAHOST_STORE_URL, error=str(exc))
        return []
    return parse_ultahost_plans({_ULTAHOST_STORE_URL: html})
