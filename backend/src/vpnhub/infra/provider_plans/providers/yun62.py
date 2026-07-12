"""Динамический каталог тарифов 62YUN (62yun.ru).

Провайдер отдаёт страницу заказа `62yun.ru/servers/order` server-side: характеристики и цена каждого
тарифа зашиты прямо в обработчик `onClick` кнопки тарифа (`orderingServerInner(...)` + месячная цена в
рублях `orderingServerSetPrice(N)`), а код локации — во втором css-классе кнопки (`tarifs fra`). Placeholder
«0 vCPU» в разметке заполняется JS-ом при клике, но нам нужны именно значения из onClick.

ВАЖНО: у каждой локации СВОЙ набор тарифов (напр. в Гонконге только promo-B, в США нет ultra-S) —
поэтому мы НЕ размножаем один набор по всем локациям (как UltaHost), а парсим ровно те кнопки, что есть.
Коды локаций непрозрачны (frm=США, fra=Германия), поэтому карта «код→страна» снимается со страницы
(кнопки выбора локации, `$('#loc').val('...')`), а не хардкодится. Трафик/скорость порта на странице не
публикуются (None/0). ОС — чистая Ubuntu (18.04–24.04) среди Debian/CentOS.
"""

from __future__ import annotations

import re
import urllib.error
from collections.abc import Mapping
from typing import Any

import structlog

from ..common import _int, _norm, _quantity_gb, _storage_type_from_text
from ..http import _fetch_browser_url

log = structlog.get_logger(__name__)

_YUN62_URL = "https://62yun.ru/servers/order"
_YUN62_TIMEOUT = 8.0

_BUTTON_RE = re.compile(r"<button\b(?P<attrs>[^>]*)>(?P<inner>.*?)</button>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_LOC_VAL_RE = re.compile(r"\$\('#loc'\)\.val\('([a-z0-9]+)'\)", re.I)
_INNER_RE = re.compile(r"orderingServerInner\('([^']*)',\s*'([^']*)',\s*'([^']*)'")
_PRICE_RE = re.compile(r"orderingServerSetPrice\((\d+(?:\.\d+)?)\)")


def _attr(attrs: str, name: str) -> str:
    if m := re.search(rf'{name}="([^"]*)"', attrs, re.I):
        return m.group(1)
    return ""


def _text(inner: str) -> str:
    return _norm(_TAG_RE.sub(" ", inner))


def _loc_map(html: str) -> dict[str, str]:
    """Снять карту «код локации → название страны» с кнопок выбора локации."""
    mapping: dict[str, str] = {}
    for m in _BUTTON_RE.finditer(html):
        attrs = m.group("attrs")
        if "tarifs" in _attr(attrs, "class"):
            continue  # кнопки тарифов сюда не относятся — у них #plan, а не #loc
        onclick = _attr(attrs, "onclick") or _attr(attrs, "onClick")
        loc = _LOC_VAL_RE.search(onclick)
        name = _text(m.group("inner"))
        if loc and name and len(name) <= 40:
            mapping.setdefault(loc.group(1).lower(), name)
    return mapping


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or text.encode("utf-8").hex()


def _loc_class(class_attr: str) -> str:
    tokens = [t for t in class_attr.split() if t != "tarifs"]
    return tokens[0].lower() if tokens else ""


def parse_yun62_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить тарифы 62YUN из скачанной страницы заказа (по кнопке на тариф+локацию)."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        loc_names = _loc_map(html)
        for m in _BUTTON_RE.finditer(html):
            attrs = m.group("attrs")
            class_attr = _attr(attrs, "class")
            if "tarifs" not in class_attr:
                continue
            onclick = _attr(attrs, "onclick") or _attr(attrs, "onClick")
            inner = _INNER_RE.search(onclick)
            price_m = _PRICE_RE.search(onclick)
            if inner is None or price_m is None:
                continue
            loc_code = _loc_class(class_attr)
            region = loc_names.get(loc_code)
            name = _text(m.group("inner"))
            cpu = _int(inner.group(1))
            ram = _quantity_gb(inner.group(2))
            disk = _quantity_gb(inner.group(3))
            if not region or not name or cpu is None or ram is None or disk is None:
                continue
            plan = {
                "id": f"62yun-{loc_code}-{_slug(name)}",
                "name": f"{name} · {region}",
                "region": region,
                "cpu": cpu,
                "ramGb": ram,
                "diskGb": int(disk),
                "diskType": _storage_type_from_text(inner.group(3)),
                "portMbps": 0,  # скорость порта не публикуется
                "trafficTb": None,  # квота трафика на странице не указана
                "price": float(price_m.group(1)),
                "currency": "RUB",
                "period": "month",
                "available": True,
                "sourceUrl": url,
            }
            by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


async def fetch_yun62_plans(timeout: float = _YUN62_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать страницу заказа 62YUN и вернуть текущие VPS-тарифы (по локациям)."""
    try:
        html = await _fetch_browser_url(_YUN62_URL, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="62yun", url=_YUN62_URL, error=str(exc))
        return []
    return parse_yun62_plans({_YUN62_URL: html})
