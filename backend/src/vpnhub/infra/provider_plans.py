"""Динамический каталог тарифных планов провайдеров.

Для поддержанных провайдеров планы не хардкодятся: при запросе `/providers/{id}/plans`
панель открывает публичные страницы провайдера, собирает актуальные CPU/RAM, диск, порт,
месячную квоту трафика и цену. Это всё ещё справочник для автозаполнения цены/квоты:
владелец может скорректировать значения после создания сервера.
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import certifi
import structlog
from cashews import Cache

log = structlog.get_logger(__name__)

TIB = 1024**4  # 1 ТБ (бинарно, как в UI: ГБ = 1024³)

_FIRSTBYTE_BASE = "https://firstbyte.ru"
_FIRSTBYTE_SITEMAP = f"{_FIRSTBYTE_BASE}/sitemap.xml"
_FIRSTBYTE_TIMEOUT = 5.0
_FIRSTBYTE_MAX_PAGES = 36
_UFO_BASE = "https://ufo.hosting"
_UFO_PLANS_URL = f"{_UFO_BASE}/vps-vds"
_UFO_AJAX_URL = f"{_UFO_BASE}/wp-admin/admin-ajax.php"
_UFO_TIMEOUT = 8.0
_ISHOSTING_BASE = "https://ishosting.com"
_ISHOSTING_VPS_URL = f"{_ISHOSTING_BASE}/en/vps"
_ISHOSTING_TIMEOUT = 10.0
_ISHOSTING_FETCH_CONCURRENCY = 8
_AHOST_BASE = "https://ahost.eu"
_AHOST_VDS_URL = f"{_AHOST_BASE}/ru/vds-linux"
_AHOST_TIMEOUT = 8.0
_AHOST_FETCH_CONCURRENCY = 8
_SERVERSPACE_PRICE_URL = "https://serverspace.ru/conditions/price/"
_SERVERSPACE_TIMEOUT = 8.0
_SERVERSPACE_CHALLENGE_MARKERS = ("__js_p_", "__jhash_", "ajaxload.info")
_SERVERSPACE_JS_COOKIE_RE = re.compile(r"__js_p_=([^;]+)")
_SERVERSPACE_HASH_COOKIE_RE = re.compile(r"(__hash_)=([^;]+)")
_PROVIDER_PLANS_CACHE_TTL_S = 30 * 60
_PROVIDER_PLANS_STALE_TTL_S = 6 * 60 * 60
_PROVIDER_PLANS_EMPTY_TTL_S = 5 * 60
_USER_AGENT = "vpnhub-provider-plans/0.1 (+https://github.com/AlexeyShalaev/vpn-hub)"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Seed-страницы из текущего меню FirstByte + страницы, которые пользователь явно попросил учесть.
# Сами тарифные данные с них не фиксируются: URL открываются заново при каждом запросе.
_FIRSTBYTE_SEEDS: tuple[str, ...] = (
    f"{_FIRSTBYTE_BASE}/vps-vds/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-ssd/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-ssd-eu/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-ssd-us/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-ssd-asia/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-sas/",
    f"{_FIRSTBYTE_BASE}/vps-vds/kvm-business/",
    f"{_FIRSTBYTE_BASE}/vps-vds/finland/",
    f"{_FIRSTBYTE_BASE}/vps-vds/france/",
    f"{_FIRSTBYTE_BASE}/vps-vds/bulgaria/",
    f"{_FIRSTBYTE_BASE}/vps-vds/spain/",
    f"{_FIRSTBYTE_BASE}/vps-vds/germany/",
    f"{_FIRSTBYTE_BASE}/vps-vds/netherlands/",
    f"{_FIRSTBYTE_BASE}/vps-vds/oae/",
    f"{_FIRSTBYTE_BASE}/vps-vds/japan/",
    f"{_FIRSTBYTE_BASE}/vps-vds/brazil/",
)

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

_LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?(.+?)(?:\]\]>)?\s*</loc>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"[\s\u00a0]+")
_UFO_NONCE_RE = re.compile(r"\bnonce\s*:\s*['\"]([^'\"]+)['\"]")
_PlanFetcher = Callable[[], Awaitable[list[dict[str, Any]]]]


_PROVIDER_PLANS_CACHE = Cache()
_PROVIDER_PLANS_CACHE.setup("mem://")
_PROVIDER_PLANS_CACHE_VERSION = 0
_PROVIDER_PLANS_PROVIDER_VERSIONS: dict[str, int] = {}
_PLANS_REFRESH_LOCKS: dict[str, asyncio.Lock] = {}
_PLANS_LOCK = asyncio.Lock()


class _PlanHtmlParser(HTMLParser):
    """Минимальный HTML-парсер под WordPress-таблицы FirstByte.

    BeautifulSoup не добавляем: структура таблиц простая, а проект уже использует stdlib urllib для
    внешних HTTP-запросов. В ячейки дополнительно кладём tooltip `data-title`, потому что регион
    часто спрятан именно там, а не в видимом тексте.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: set[str] = set()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        if tag == "a" and attrs_d.get("href"):
            self.links.add(urllib.parse.urljoin(self.base_url, attrs_d["href"]))

        cls = attrs_d.get("class", "")
        if tag == "table" and "table-transformer" in cls:
            self._in_table = True
            self._rows = []
            return

        if not self._in_table:
            return

        if tag == "tr":
            self._row = []
            return
        if tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._skip_stack = []
            if title := attrs_d.get("data-title"):
                self._cell_parts.append(title)
            return
        if self._cell_parts is None:
            return
        if tag == "br":
            self._cell_parts.append("\n")
        if title := attrs_d.get("data-title"):
            self._cell_parts.append(f" {title} ")
        if tag == "sup" or "strikedprice" in cls:
            self._skip_stack.append(tag)

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None and not self._skip_stack:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if self._skip_stack and tag == self._skip_stack[-1]:
            self._skip_stack.pop()
            return
        if tag in {"td", "th"} and self._cell_parts is not None:
            assert self._row is not None
            self._row.append(_norm("".join(self._cell_parts)))
            self._cell_parts = None
            self._skip_stack = []
            return
        if tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self._rows.append(self._row)
            self._row = None
            return
        if tag == "table":
            if self._rows:
                self.tables.append(self._rows)
            self._in_table = False
            self._rows = []
            self._row = None
            self._cell_parts = None
            self._skip_stack = []


def _norm(text: str) -> str:
    return _SPACE_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _normalize_firstbyte_url(url: str) -> str | None:
    full = urllib.parse.urljoin(_FIRSTBYTE_BASE, url)
    parsed = urllib.parse.urlparse(full)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in {"firstbyte.ru", "www.firstbyte.ru"}:
        return None
    path = parsed.path
    if not path.endswith("/"):
        path = f"{path}/"
    return urllib.parse.urlunparse(("https", "firstbyte.ru", path, "", "", ""))


def _is_firstbyte_plan_url(url: str) -> bool:
    normalized = _normalize_firstbyte_url(url)
    if normalized is None:
        return False
    path = urllib.parse.urlparse(normalized).path
    if not path.startswith("/vps-vds/"):
        return False
    # Страницы ОС и служебные страницы перечислены в robots.txt как нецелевые; архивы не смешиваем
    # с актуальными тарифами.
    excluded = (
        "/vps-vds/vds-",
        "/vps-vds/dopuslugi/",
        "/vps-vds/archive",
        "/vps-vds/arhiv",
        "/vps-vds/backup",
        "/vps-vds/tariffs-archive/",
    )
    if any(path.startswith(x) for x in excluded):
        return False
    # Берём только верхний уровень /vps-vds/<slug>/, чтобы не уходить в блог/мануалы/параметры.
    return len([p for p in path.split("/") if p]) <= 2


def _sitemap_urls(xml: str) -> set[str]:
    urls: set[str] = set()
    for raw in _LOC_RE.findall(xml):
        if normalized := _normalize_firstbyte_url(raw):
            urls.add(normalized)
    return urls


def discover_firstbyte_plan_urls(pages: Mapping[str, str], sitemap_xml: str = "") -> list[str]:
    """Найти релевантные страницы тарифов FirstByte из seed-страниц и sitemap."""
    urls = {_normalize_firstbyte_url(u) for u in _FIRSTBYTE_SEEDS}
    urls.update(_sitemap_urls(sitemap_xml))
    for url, html in pages.items():
        parser = _PlanHtmlParser(url)
        parser.feed(html)
        urls.update(_normalize_firstbyte_url(link) for link in parser.links)
    filtered = [u for u in urls if u and _is_firstbyte_plan_url(u)]
    return sorted(set(filtered))[:_FIRSTBYTE_MAX_PAGES]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


async def _fetch_url(url: str, timeout: float) -> str:
    def _get() -> str:
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await asyncio.to_thread(_get)


async def _fetch_browser_url(url: str, timeout: float) -> str:
    def _get() -> str:
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            headers={
                "User-Agent": _BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await asyncio.to_thread(_get)


async def _post_form_url(url: str, form: Mapping[str, str], timeout: float) -> str:
    def _post() -> str:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json,text/javascript,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await asyncio.to_thread(_post)


async def _fetch_many(urls: Iterable[str], timeout: float) -> dict[str, str]:
    async def one(url: str) -> tuple[str, str]:
        try:
            return url, await _fetch_url(url, timeout)
        except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
            log.warning("provider_plans_fetch_failed", provider="firstbyte", url=url, error=str(exc))
            return url, ""

    pairs = await asyncio.gather(*(one(u) for u in sorted(set(urls))))
    return {url: html for url, html in pairs if html}


async def _fetch_sitemap(timeout: float) -> str:
    try:
        return await _fetch_url(_FIRSTBYTE_SITEMAP, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_sitemap_failed", provider="firstbyte", error=str(exc))
        return ""


def _find_idx(headers: list[str], needle: str) -> int | None:
    for i, header in enumerate(headers):
        if needle in header.lower():
            return i
    return None


def _cell(row: list[str], idx: int | None) -> str:
    return row[idx] if idx is not None and idx < len(row) else ""


def _int(text: str) -> int | None:
    if m := re.search(r"\d+", text.replace(" ", "")):
        return int(m.group(0))
    return None


def _ram_gb(text: str, header: str) -> float | None:
    raw = _int(text)
    if raw is None:
        return None
    if "mb" in header.lower() or "мб" in header.lower():
        gb = raw / 1024
        return int(gb) if gb.is_integer() else round(gb, 2)
    return float(raw)


def _disk_type(header: str) -> str:
    up = header.upper().replace(" ", "")
    if "SAS+SSD" in up:
        return "SAS+SSD"
    if "SAS" in up:
        return "SAS"
    if "SSD" in up:
        return "SSD"
    return ""


def _traffic_tb(channel: str) -> float | None:
    low = channel.lower()
    if "безлим" in low:
        return None
    if m := re.search(r"(\d+(?:[.,]\d+)?)\s*тб", low):
        raw = m.group(1).replace(",", ".")
        tb = float(raw)
        return int(tb) if tb.is_integer() else tb
    return None


def _port_mbps(channel: str) -> int | None:
    low = channel.lower()
    if m := re.search(r"(\d+)\s*(?:мб|mb|mbit|мбит)", low):
        return int(m.group(1))
    return None


def _price_rub(text: str) -> int | None:
    prices = re.findall(r"(\d[\d\s]*)\s*(?:₽|руб)", text.lower())
    if not prices:
        return None
    return int(prices[-1].replace(" ", ""))


def _region(text: str) -> str:
    region = _norm(re.sub(r"Data\s*Center.*", "", text, flags=re.IGNORECASE))
    region = region.replace("TIER3", "").strip(" ,")
    return region or "—"


def _tariff_name(text: str) -> str:
    name = _norm(text).replace("- ", "-").replace(" -", "-")
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def _plan_id(tariff: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", tariff.lower()).strip("-")
    return f"fb-{slug}"


def _available(action_cell: str) -> bool:
    low = action_cell.lower()
    if "распрод" in low or "ожида" in low:
        return False
    return "заказать" in low


def _plans_from_table(table: list[list[str]], source_url: str) -> list[dict[str, Any]]:
    if not table:
        return []
    headers = [_norm(h).lower() for h in table[0]]
    idx_tariff = _find_idx(headers, "тариф")
    idx_cpu = _find_idx(headers, "процессор")
    idx_ram = _find_idx(headers, "оператив")
    idx_disk = _find_idx(headers, "диск")
    idx_channel = _find_idx(headers, "канал")
    idx_region = _find_idx(headers, "страна")
    idx_price = _find_idx(headers, "цена")
    if (
        idx_tariff is None
        or idx_cpu is None
        or idx_ram is None
        or idx_disk is None
        or idx_channel is None
        or idx_region is None
        or idx_price is None
    ):
        return []

    out: list[dict[str, Any]] = []
    disk_type = _disk_type(headers[idx_disk])
    for row in table[1:]:
        tariff = _tariff_name(_cell(row, idx_tariff))
        cpu = _int(_cell(row, idx_cpu))
        ram = _ram_gb(_cell(row, idx_ram), headers[idx_ram])
        disk = _int(_cell(row, idx_disk))
        channel = _cell(row, idx_channel)
        port = _port_mbps(channel)
        price = _price_rub(_cell(row, idx_price))
        if not tariff or cpu is None or ram is None or disk is None or port is None or price is None:
            continue
        region = _region(_cell(row, idx_region))
        out.append(
            {
                "id": _plan_id(tariff),
                "name": f"{tariff} · {region}",
                "region": region,
                "cpu": cpu,
                "ramGb": ram,
                "diskGb": disk,
                "diskType": disk_type,
                "portMbps": port,
                "trafficTb": _traffic_tb(channel),
                "price": price,
                "currency": "RUB",
                "period": "month",
                "available": _available(row[-1] if row else ""),
                "sourceUrl": source_url,
            }
        )
    return out


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


@dataclass
class _IshostingPlanCard:
    name: str = ""
    region: str = ""
    specs: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    price: float | None = None


@dataclass
class _AhostPlanCard:
    name: str = ""
    specs: list[tuple[str, str]] = field(default_factory=list)
    price: float | None = None


@dataclass
class _ServerspaceFixedPlanRow:
    ram: str = ""
    cpu: str = ""
    disk: str = ""
    bandwidth: str = ""
    price_values: list[float] = field(default_factory=list)
    currency: str = ""


class _IshostingLinkParser(HTMLParser):
    """Достаёт ссылки вида /en/vps/<country> из SSR-страниц ISHOSTING."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        attrs_d = {k: (v or "") for k, v in attrs}
        href = attrs_d.get("href")
        if not href:
            return
        self._href = urllib.parse.urljoin(self.base_url, href)
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        self.links.append((self._href, _norm("".join(self._text_parts))))
        self._href = None
        self._text_parts = []


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


class _ServerspaceFixedPlanParser(HTMLParser):
    """Парсер фиксированных тарифов Serverspace с блока `Fixed plans`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ServerspaceFixedPlanRow] = []
        self.region = ""
        self._first_region = ""
        self._row: _ServerspaceFixedPlanRow | None = None
        self._row_depth = 0
        self._capture: str | None = None
        self._capture_end_tag = ""
        self._capture_parts: list[str] = []
        self._in_fixed_dc_select = False
        self._option_selected = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())

        if tag == "select" and attrs_d.get("id") == "fixedDc":
            self._in_fixed_dc_select = True
            return
        if self._in_fixed_dc_select and tag == "option":
            self._option_selected = "selected" in attrs_d
            self._start_capture("fixed_region", "option")
            return

        if self._row is None and tag == "div" and "plans-row" in classes:
            self._row = _ServerspaceFixedPlanRow()
            self._row_depth = 1
            return
        if self._row is None:
            return

        if tag == "div":
            self._row_depth += 1
            if "cell-ram" in classes:
                self._start_capture("ram", "div")
            elif "cell-cpu" in classes:
                self._start_capture("cpu", "div")
            elif "cell-ssd" in classes:
                self._start_capture("disk", "div")
            elif "cell-bandwidth" in classes:
                self._start_capture("bandwidth", "div")
        elif tag == "span" and "price__value" in classes:
            self._start_capture("price_value", "span")
        elif tag == "span" and "price__symbol" in classes:
            self._start_capture("price_symbol", "span")

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag == self._capture_end_tag:
            self._finish_capture()

        if self._in_fixed_dc_select and tag == "select":
            self._in_fixed_dc_select = False
            return

        if self._row is None or tag != "div":
            return
        self._row_depth -= 1
        if self._row_depth <= 0:
            if self._row.ram or self._row.cpu or self._row.disk or self._row.bandwidth:
                self.rows.append(self._row)
            self._row = None
            self._row_depth = 0

    def _start_capture(self, name: str, end_tag: str) -> None:
        self._capture = name
        self._capture_end_tag = end_tag
        self._capture_parts = []

    def _finish_capture(self) -> None:
        text = _norm("".join(self._capture_parts))
        capture = self._capture
        self._capture = None
        self._capture_end_tag = ""
        self._capture_parts = []

        if capture == "fixed_region":
            if text and not self._first_region:
                self._first_region = text
            if text and self._option_selected:
                self.region = text
            self._option_selected = False
            return

        if self._row is None:
            return
        if capture == "ram":
            self._row.ram = text
        elif capture == "cpu":
            self._row.cpu = text
        elif capture == "disk":
            self._row.disk = text
        elif capture == "bandwidth":
            self._row.bandwidth = text
        elif capture == "price_value":
            if (price := _number_value(text)) is not None:
                self._row.price_values.append(price)
        elif capture == "price_symbol":
            self._row.currency = _currency_code(text) or self._row.currency

    @property
    def selected_region(self) -> str:
        return self.region or self._first_region or "Serverspace"


def parse_firstbyte_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить тарифы FirstByte из уже скачанных HTML-страниц."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        parser = _PlanHtmlParser(url)
        parser.feed(html)
        for table in parser.tables:
            for plan in _plans_from_table(table, url):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), str(p["id"])))


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
    return _port_mbps(text)


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


def _number_value(text: str) -> float | None:
    compact = _norm(text).replace(" ", "").replace(",", ".")
    if m := re.search(r"\d+(?:\.\d+)?", compact):
        value = float(m.group(0))
        return int(value) if value.is_integer() else value
    return None


def _currency_code(text: str) -> str:
    low = text.lower()
    if "₽" in text or "руб" in low or "rub" in low:
        return "RUB"
    if "€" in text or "eur" in low:
        return "EUR"
    if "$" in text or "usd" in low:
        return "USD"
    return ""


def _serverspace_currency(source_url: str, row_currency: str) -> str:
    if row_currency:
        return row_currency
    host = urllib.parse.urlparse(source_url).netloc.lower()
    if host.endswith(".ru"):
        return "RUB"
    if host.endswith(".io"):
        return "EUR"
    return ""


def _serverspace_label_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "p")


def _serverspace_plan_id(cpu: int, ram: float, disk: float) -> str:
    return (
        f"serverspace-fixed-{cpu}c-"
        f"{_serverspace_label_number(ram)}gb-"
        f"{_serverspace_label_number(disk)}gb"
    )


def _serverspace_challenge(html: str) -> bool:
    low = html.lower()
    return "plans-row" not in low and any(marker in low for marker in _SERVERSPACE_CHALLENGE_MARKERS)


def _serverspace_jhash(code: int) -> int:
    x = 123456789
    k = 0
    for i in range(1_677_696):
        x = ((x + code) ^ (x + (x % 3) + (x % 17) + code) ^ i) % 16_776_960
        if x % 117 == 0:
            k = (k + 1) % 1111
    return k


def _fixed_encode_uri_component(text: str) -> str:
    encoded = urllib.parse.quote(text, safe="-_.!~*'()")
    for char in "!'()*":
        encoded = encoded.replace(char, f"%{ord(char):x}")
    return encoded


def _serverspace_cookie_header(cookies: Mapping[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


async def _fetch_serverspace_price_page(timeout: float) -> str:
    def _read_response(resp: Any) -> str:
        charset = resp.headers.get_content_charset() or "utf-8"
        body: bytes = resp.read(2_500_000)
        return body.decode(charset, "replace")

    def _get() -> str:
        headers = {
            "User-Agent": _BROWSER_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        ctx = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(_SERVERSPACE_PRICE_URL, headers=headers)  # noqa: S310
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:  # noqa: S310
            first_html = _read_response(resp)
            js_cookie = resp.headers.get("Set-Cookie", "")

        if not _serverspace_challenge(first_html):
            return first_html

        js_match = _SERVERSPACE_JS_COOKIE_RE.search(js_cookie)
        if not js_match:
            return first_html
        js_cookie_value = js_match.group(1)
        try:
            code = int(js_cookie_value.split(",", 1)[0])
        except ValueError:
            return first_html

        cookies = {
            "__js_p_": js_cookie_value,
            "__jhash_": str(_serverspace_jhash(code)),
            "__jua_": _fixed_encode_uri_component(_BROWSER_USER_AGENT),
        }
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), _NoRedirect)
        # Serverspace JS waits one second before setting the cookies and reloading the page.
        time.sleep(1.05)
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-константы
            _SERVERSPACE_PRICE_URL,
            headers={**headers, "Cookie": _serverspace_cookie_header(cookies)},
        )
        try:
            with opener.open(req, timeout=timeout) as resp:
                return _read_response(resp)
        except urllib.error.HTTPError as exc:
            if exc.code not in {301, 302, 303, 307, 308}:
                raise
            if hash_match := _SERVERSPACE_HASH_COOKIE_RE.search(exc.headers.get("Set-Cookie", "")):
                cookies[hash_match.group(1)] = hash_match.group(2)

        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-константы
            _SERVERSPACE_PRICE_URL,
            headers={**headers, "Cookie": _serverspace_cookie_header(cookies)},
        )
        with opener.open(req, timeout=timeout) as resp:
            return _read_response(resp)

    return await asyncio.to_thread(_get)


def _serverspace_row_to_plan(
    row: _ServerspaceFixedPlanRow,
    source_url: str,
    region: str,
) -> dict[str, Any] | None:
    cpu = _int(row.cpu)
    ram = _quantity_gb(row.ram)
    disk = _quantity_gb(row.disk)
    port = _speed_mbps(row.bandwidth)
    price = row.price_values[1] if len(row.price_values) >= 2 else None
    disk_type = _storage_type_from_text(row.disk) or "SSD"
    if cpu is None or ram is None or disk is None or port is None or price is None:
        return None
    ram_label = _serverspace_label_number(ram)
    disk_label = _serverspace_label_number(disk)
    return {
        "id": _serverspace_plan_id(cpu, ram, disk),
        "name": f"Fixed {cpu}C/{ram_label}GB/{disk_label}GB {disk_type} · {region}",
        "region": region,
        "cpu": cpu,
        "ramGb": ram,
        "diskGb": int(disk),
        "diskType": disk_type,
        "portMbps": port,
        "trafficTb": None,
        "price": price,
        "currency": _serverspace_currency(source_url, row.currency),
        "period": "month",
        "available": True,
        "sourceUrl": source_url,
    }


def parse_serverspace_plans(pages: Mapping[str, str]) -> list[dict[str, Any]]:
    """Распарсить фиксированные VPS-тарифы Serverspace из страницы цен."""
    by_id: dict[str, dict[str, Any]] = {}
    for url, html in pages.items():
        if not html or _serverspace_challenge(html):
            continue
        parser = _ServerspaceFixedPlanParser()
        parser.feed(html)
        for row in parser.rows:
            if plan := _serverspace_row_to_plan(row, url, parser.selected_region):
                by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


def clear_provider_plan_cache(provider_id: str | None = None) -> None:
    """Инвалидировать in-memory кэш тарифов (используется тестами и будущей ручной инвалидацией)."""
    global _PROVIDER_PLANS_CACHE_VERSION  # noqa: PLW0603 — синхронная инвалидация через namespace версии.
    if provider_id is None:
        _PROVIDER_PLANS_CACHE_VERSION += 1
        _PROVIDER_PLANS_PROVIDER_VERSIONS.clear()
        _PLANS_REFRESH_LOCKS.clear()
        return
    key = _provider_key(provider_id)
    _PROVIDER_PLANS_PROVIDER_VERSIONS[key] = _PROVIDER_PLANS_PROVIDER_VERSIONS.get(key, 0) + 1
    _PLANS_REFRESH_LOCKS.pop(key, None)


def _clone_plans(plans: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(p) for p in plans]


def _freeze_plans(plans: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(_clone_plans(plans))


def _cache_key(provider_id: str, bucket: str) -> str:
    provider_version = _PROVIDER_PLANS_PROVIDER_VERSIONS.get(provider_id, 0)
    return f"provider-plans:v{_PROVIDER_PLANS_CACHE_VERSION}:{provider_id}:v{provider_version}:{bucket}"


async def _store_provider_plans(
    provider_id: str,
    plans: Iterable[Mapping[str, Any]],
    *,
    fresh_ttl: int,
    stale: bool,
) -> tuple[dict[str, Any], ...]:
    frozen = _freeze_plans(plans)
    if fresh_ttl > 0:
        await _PROVIDER_PLANS_CACHE.set(_cache_key(provider_id, "fresh"), frozen, expire=fresh_ttl)
    if stale:
        await _PROVIDER_PLANS_CACHE.set(
            _cache_key(provider_id, "stale"),
            frozen,
            expire=_PROVIDER_PLANS_STALE_TTL_S,
        )
    return frozen


async def _extend_stale_cache(provider_id: str, cached: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    frozen = await _store_provider_plans(
        provider_id,
        cached,
        fresh_ttl=_PROVIDER_PLANS_CACHE_TTL_S,
        stale=True,
    )
    return _clone_plans(frozen)


async def _refresh_lock(provider_id: str) -> asyncio.Lock:
    async with _PLANS_LOCK:
        return _PLANS_REFRESH_LOCKS.setdefault(provider_id, asyncio.Lock())


async def _cached_provider_plans(provider_id: str, fetcher: _PlanFetcher) -> list[dict[str, Any]]:
    """TTL-кэш в памяти процесса, чтобы UI не парсил сайт провайдера на каждый запрос."""
    key = provider_id.strip().lower()
    cached = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "fresh"))
    if cached is not None:
        return _clone_plans(cached)

    async with await _refresh_lock(key):
        cached = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "fresh"))
        if cached is not None:
            return _clone_plans(cached)
        stale = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "stale"))

        try:
            fresh = await fetcher()
        except Exception as exc:
            if stale is not None:
                log.warning("provider_plans_cache_stale", provider=key, error=str(exc))
                return await _extend_stale_cache(key, stale)
            raise

        if not fresh:
            if stale is not None:
                log.warning("provider_plans_cache_stale_empty", provider=key)
                return await _extend_stale_cache(key, stale)
            await _store_provider_plans(key, (), fresh_ttl=_PROVIDER_PLANS_EMPTY_TTL_S, stale=False)
            return []

        frozen = await _store_provider_plans(
            key,
            fresh,
            fresh_ttl=_PROVIDER_PLANS_CACHE_TTL_S,
            stale=True,
        )
        return _clone_plans(frozen)


async def fetch_firstbyte_plans(timeout: float = _FIRSTBYTE_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать сайт FirstByte и вернуть текущие тарифы."""
    seeds, sitemap = await asyncio.gather(_fetch_many(_FIRSTBYTE_SEEDS, timeout), _fetch_sitemap(timeout))
    urls = discover_firstbyte_plan_urls(seeds, sitemap)
    pages = {**seeds, **await _fetch_many((u for u in urls if u not in seeds), timeout)}
    return parse_firstbyte_plans(pages)


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


async def fetch_serverspace_plans(timeout: float = _SERVERSPACE_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать страницу цен Serverspace и вернуть фиксированные VPS-тарифы."""
    try:
        html = await _fetch_serverspace_price_page(timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider="serverspace", url=_SERVERSPACE_PRICE_URL, error=str(exc))
        return []
    if _serverspace_challenge(html):
        log.warning(
            "provider_plans_fetch_failed",
            provider="serverspace",
            url=_SERVERSPACE_PRICE_URL,
            error="js_challenge",
        )
        return []
    return parse_serverspace_plans({_SERVERSPACE_PRICE_URL: html})


def _provider_key(provider_id: str) -> str:
    raw = (provider_id or "").strip().lower()
    compact = re.sub(r"[\s_-]+", "", raw)
    if compact == "firstbyte":
        return "firstbyte"
    if compact in {"ufo", "ufohosting"}:
        return "ufo"
    if compact in {"ishosting", "ishostingcom"}:
        return "ishosting"
    if compact in {"ahost", "ahosteu"}:
        return "ahost"
    if compact in {"serverspace", "serverspaceru", "serverspaceio"}:
        return "serverspace"
    return raw


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    """Планы провайдера по его id (пустой список, если каталога нет/сайт недоступен)."""
    provider = _provider_key(provider_id)
    if provider == "firstbyte":
        return await _cached_provider_plans("firstbyte", fetch_firstbyte_plans)
    if provider == "ufo":
        return await _cached_provider_plans("ufo", fetch_ufo_plans)
    if provider == "ishosting":
        return await _cached_provider_plans("ishosting", fetch_ishosting_plans)
    if provider == "ahost":
        return await _cached_provider_plans("ahost", fetch_ahost_plans)
    if provider == "serverspace":
        return await _cached_provider_plans("serverspace", fetch_serverspace_plans)
    return []


def plan_bandwidth_bytes(plan: dict) -> int | None:
    """Квота трафика плана в байтах (None = безлимит/не указано)."""
    tb = plan.get("trafficTb")
    return int(tb * TIB) if tb else None
