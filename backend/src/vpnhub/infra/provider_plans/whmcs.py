"""Общий парсер витрин WHMCS (`cart.php?gid=N`, `/store/<группа>`) — биллинга большинства хостеров.

Тема корзины `standard_cart` рендерит товары группы на сервере одинаково у всех: имя — `#productN-name`,
описание (характеристики списком или строками) — до `#productN-price`, цена и цикл — в `#productN-price`
(«Starting from $5.00 USD Monthly», «Начиная от 2383.00₸ ежемесячно», «Desde $6,000CLP Mensualmente»),
остаток — `<span class="qty">0 Available</span>`. Поэтому новый WHMCS-провайдер — это только конфиг
витрин (`WhmcsPage`: URL группы, её локация, валюта по умолчанию), а разбор общий.

Характеристики в описании пишут вольно («1 vCPU Core», «2 ядра», «1024MB» + «RAM» отдельной строкой,
«Traffic:» + «1 TB»), поэтому строки описания склеиваются в пары «значение + подпись» и разбираются по
ключевым словам на нескольких языках. Годовые/квартальные цены приводятся к месяцу (сервер в панели
тарифицируется помесячно), а цикл дописывается к имени тарифа.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import re
import urllib.error
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import structlog

from .common import _quantity_gb, _speed_mbps, _storage_type_from_text, _traffic_tb_any, make_plan, slugify, sort_plans
from .http import _fetch_browser_url

log = structlog.get_logger(__name__)

_TIMEOUT = 10.0
_CONCURRENCY = 6


@dataclass(frozen=True)
class WhmcsPage:
    """Витрина (группа товаров) WHMCS и то, чего нет в самой разметке."""

    url: str
    region: str  # локация группы, как её покажет панель («Vienna, Austria»)
    country: str = ""  # ISO-код страны локации
    currency: str = ""  # валюта, если в цене только символ («$» у чилийских хостеров — это CLP)
    disk_type: str = ""  # тип диска, если описание его не называет


_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"(?i)<\s*/?\s*(?:br|li|p|div|tr|td|h\d|ul)\b[^>]*>")
_NAME_RE = re.compile(r'id="product(\d+)-name"[^>]*>(.*?)</', re.S)
_DIGIT_RE = re.compile(r"\d")

_RAM_RE = re.compile(r"\b(?:ram|memory|mem[oó]ria|mem|ddr[345])\b|памят|озу|оперативн|arbeitsspeicher|mémoire", re.I)
_CPU_RE = re.compile(
    r"(\d+)\s*(?:x\s*)?(?:v?cpu|v?cores?|vcore|ядр|ядер|процессор|cpu virtual|n[uú]cleos?|kerne)"
    r"|\b(?:v?cpu|cores?)\s*[:\-]?\s*(\d+)\b"
    r"|(\d+)\s*x\s*\d+(?:[.,]\d+)?\s*ghz",  # «1x2.1Ghz - 3.9Ghz CPU»
    re.I,
)
_DISK_RE = re.compile(r"ssd|nvme|hdd|disk|storage|almacenamiento|espacio|hard drive|space|диск|накопител", re.I)
_TRAFFIC_RE = re.compile(r"bandwidth|traffic|transfer|transferencia|tr[aá]fego|tr[aá]fico|трафик", re.I)
_UNMETERED_RE = re.compile(r"unmetered|unlimited|ilimitad|безлимит|без огранич", re.I)
_PORT_RE = re.compile(r"\d\s*(?:[mg]bps|[mg]bit|[мг]бит)", re.I)
_GIGAS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*gigas?\b", re.I)

# валюта: явный код в тексте цены надёжнее символа
# код валюты может прилипать к числу («$6,000CLP»), поэтому границы — «не буква», а не \b
_CODE_RE = re.compile(
    r"(?<![A-Za-z])(USD|EUR|GBP|RUB|KZT|UAH|BYN|CLP|BRL|MXN|ARS|COP|PEN|INR|CNY|HKD|SGD|JPY|AUD|CAD|CHF|PLN|CZK|TRY)"
    r"(?![A-Za-z])"
)
_SYMBOLS: Mapping[str, str] = {
    "R$": "BRL",
    "€": "EUR",
    "£": "GBP",
    "₸": "KZT",
    "₽": "RUB",
    "₴": "UAH",
    "₹": "INR",
    "$": "USD",
}
_NUMBER_RE = re.compile(r"\d[\d\s.,]*\d|\d")

# цикл оплаты → во сколько месяцев он; «одноразовые»/бесплатные товары пропускаем
_CYCLES: tuple[tuple[re.Pattern[str], int, str], ...] = (
    (re.compile(r"triennial|3 years|трёхлет|трехлет", re.I), 36, "3y"),
    (re.compile(r"biennial|2 years|двухлет", re.I), 24, "2y"),
    (re.compile(r"semi-?annual|6 months|полугод|semestral", re.I), 6, "6m"),
    (re.compile(r"annual|yearly|/\s*yr|/\s*year|годов|ежегод|anual|jährlich", re.I), 12, "yearly"),
    (re.compile(r"quarter|3 months|квартал|trimestral", re.I), 3, "quarterly"),
    (re.compile(r"month|/\s*mo\b|ежемесяч|месяц|/\s*мес|mensual|mensal|monatlich", re.I), 1, ""),
)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _segments(fragment: str) -> list[str]:
    return [s for s in (_text(p) for p in _BREAK_RE.split(fragment)) if s]


def _value_then_label(cur: str, nxt: str) -> bool:  # «1024MB» + «RAM» (но не + «Traffic:» следующего значения)
    short = len(cur) <= 20 and len(nxt) <= 24
    return short and bool(_DIGIT_RE.search(cur)) and not _DIGIT_RE.search(nxt) and not nxt.endswith(":")


def _label_then_value(cur: str, nxt: str) -> bool:  # «Traffic:» + «1 TB»
    return cur.endswith(":") and len(cur) <= 24 and not _DIGIT_RE.search(cur) and bool(_DIGIT_RE.search(nxt))


def _spec_lines(segments: Sequence[str]) -> list[str]:
    """Склеить «значение» и «подпись», если тема разносит их по строкам: «1024MB»+«RAM», «Traffic:»+«1 TB».

    Клеим только короткое «голое» значение с короткой подписью без цифр (и подпись с двоеточием со
    следующим значением) — самодостаточные строки вроде «Almacenamiento 100 GB SSD» не трогаем.
    """
    out: list[str] = []
    i = 0
    while i < len(segments):
        cur = segments[i]
        nxt = segments[i + 1] if i + 1 < len(segments) else ""
        if nxt and (_value_then_label(cur, nxt) or _label_then_value(cur, nxt)):
            out.append(f"{cur} {nxt}")
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def _gb(line: str) -> float | None:
    if m := _GIGAS_RE.search(line):
        return float(m.group(1).replace(",", "."))
    return _quantity_gb(line)


@dataclass
class _Specs:
    cpu: int | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    disk_type: str = ""
    traffic_tb: float | None = None
    traffic_seen: bool = False
    port_mbps: int | None = None


def _parse_specs(lines: Sequence[str]) -> _Specs:
    specs = _Specs()
    for line in lines:
        if specs.ram_gb is None and _RAM_RE.search(line) and not _DISK_RE.search(line):
            specs.ram_gb = _gb(line)
            continue
        if specs.cpu is None and (m := _CPU_RE.search(line)):
            specs.cpu = int(next(g for g in m.groups() if g))
            continue
        if not specs.traffic_seen and _TRAFFIC_RE.search(line):
            specs.traffic_seen = True
            specs.traffic_tb = None if _UNMETERED_RE.search(line) else _traffic_tb_any(line)
            if specs.port_mbps is None and _PORT_RE.search(line):  # «200GB @ 100Mbps Bandwidth»
                specs.port_mbps = _speed_mbps(line)
            continue
        if specs.disk_gb is None and _DISK_RE.search(line) and (gb := _gb(line)):
            specs.disk_gb = gb
            specs.disk_type = _storage_type_from_text(line)
            continue
        if specs.port_mbps is None and _PORT_RE.search(line):
            specs.port_mbps = _speed_mbps(line)
    if specs.disk_gb and not specs.disk_type:  # «20GB Disk Space» + ниже «100% SSD RAID Storage»
        specs.disk_type = next((t for t in map(_storage_type_from_text, lines) if t), "")
    return specs


def _number(raw: str) -> float | None:
    s = raw.replace(" ", "").replace(" ", "")
    if "." in s and "," in s:  # последний разделитель — десятичный: 1,234.56 / 1.234,56
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        s = s.replace("," if dec == "." else ".", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    elif re.search(r"\.\d{3}$", s) and s.count(".") >= 1:
        s = s.replace(".", "")  # 9.990 — разделитель тысяч (CLP, KZT)
    try:
        return float(s)
    except ValueError:
        return None


def _parse_price(text: str, default_currency: str) -> tuple[float, str, int, str] | None:
    """(цена за месяц, валюта, месяцев в цикле, метка цикла) из текста блока цены."""
    m = _NUMBER_RE.search(text)
    if m is None:
        return None
    amount = _number(m.group(0))
    if not amount or amount <= 0:
        return None
    code = _CODE_RE.search(text)
    currency = code.group(1) if code else ""
    if not currency:
        currency = next((cur for sym, cur in _SYMBOLS.items() if sym in text), "")
        if default_currency and (not currency or currency == "USD"):
            currency = default_currency  # «$» без кода у местного хостера — местная валюта
    if not currency:
        return None
    rest = text[m.end() :]
    for pattern, months, label in _CYCLES:
        if pattern.search(rest):
            return round(amount / months, 2), currency, months, label
    if re.search(r"one ?time|free|бесплатно|единоразов", rest, re.I):
        return None
    return amount, currency, 1, ""  # цикл не подписан — считаем месячным


def parse_whmcs_page(provider_id: str, page: WhmcsPage, html: str) -> list[dict[str, Any]]:
    """Тарифы одной витрины WHMCS (`standard_cart`)."""
    plans: list[dict[str, Any]] = []
    matches = list(_NAME_RE.finditer(html))
    for idx, m in enumerate(matches):
        num, name = m.group(1), _text(m.group(2))
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
        block = html[html.find(">", m.end()) + 1 : end]  # m.end() стоит на «</» закрывающего тега имени
        price_m = re.search(rf'id="product{num}-price"[^>]*>(.*?)</div>', block, re.S)
        if not name or price_m is None:
            continue
        priced = _parse_price(_text(price_m.group(1)), page.currency)
        specs = _parse_specs(_spec_lines(_segments(block[: price_m.start()])))
        if priced is None or not specs.cpu or not specs.ram_gb or not specs.disk_gb:
            continue
        monthly, currency, _, cycle = priced
        qty = re.search(r'class="qty"[^>]*>\s*(\d+)', html[max(0, m.start() - 200) : m.end() + 400])
        plans.append(
            make_plan(
                plan_id=f"{provider_id}-{slugify(page.region)}-{slugify(name)}",
                name=f"{name}{f' ({cycle})' if cycle else ''} · {page.region.split(',')[0]}",
                region=page.region,
                country=page.country,
                cpu=specs.cpu,
                ram_gb=specs.ram_gb,
                disk_gb=int(specs.disk_gb),
                disk_type=specs.disk_type or page.disk_type,
                port_mbps=specs.port_mbps or 0,
                traffic_tb=specs.traffic_tb,
                traffic_known=specs.traffic_seen,
                price=monthly,
                currency=currency,
                source_url=page.url,
                available=not (qty and int(qty.group(1)) == 0),
            )
        )
    return plans


def parse_whmcs_plans(provider_id: str, pages: Mapping[str, str], config: Sequence[WhmcsPage]) -> list[dict[str, Any]]:
    """Тарифы провайдера по всем его витринам (HTML по URL витрины)."""
    by_url = {p.url: p for p in config}
    plans: list[dict[str, Any]] = []
    for url, html in pages.items():
        if (page := by_url.get(url)) is not None:
            plans.extend(parse_whmcs_page(provider_id, page, html))
    return sort_plans(plans)


async def fetch_whmcs_plans(
    provider_id: str, config: Sequence[WhmcsPage], timeout: float = _TIMEOUT
) -> list[dict[str, Any]]:
    """Скачать витрины WHMCS провайдера (с ограничением параллелизма) и вернуть тарифы."""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def load(page: WhmcsPage) -> tuple[str, str | None]:
        async with sem:
            try:
                return page.url, await _fetch_browser_url(page.url, timeout)
            except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
                log.warning("provider_plans_fetch_failed", provider=provider_id, url=page.url, error=str(exc))
                return page.url, None

    results = await asyncio.gather(*(load(p) for p in config))
    return parse_whmcs_plans(provider_id, {url: html for url, html in results if html}, config)
