"""Динамический каталог тарифных планов провайдеров.

Для FirstByte планы не хардкодятся: при запросе `/providers/firstbyte/plans` панель открывает
публичные страницы firstbyte.ru/vps-vds/*, находит тарифные таблицы и собирает актуальные CPU/RAM,
диск, порт, месячную квоту трафика и цену. Это всё ещё справочник для автозаполнения цены/квоты:
владелец может скорректировать значения после создания сервера.
"""

from __future__ import annotations

import asyncio
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import certifi
import structlog

log = structlog.get_logger(__name__)

TIB = 1024**4  # 1 ТБ (бинарно, как в UI: ГБ = 1024³)

_FIRSTBYTE_BASE = "https://firstbyte.ru"
_FIRSTBYTE_SITEMAP = f"{_FIRSTBYTE_BASE}/sitemap.xml"
_FIRSTBYTE_TIMEOUT = 5.0
_FIRSTBYTE_MAX_PAGES = 36
_PROVIDER_PLANS_CACHE_TTL_S = 30 * 60
_USER_AGENT = "vpnhub-provider-plans/0.1 (+https://github.com/AlexeyShalaev/vpn-hub)"

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

_LOC_RE = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?(.+?)(?:\]\]>)?\s*</loc>", re.IGNORECASE | re.DOTALL)
_SPACE_RE = re.compile(r"[\s\u00a0]+")
_PlanFetcher = Callable[[], Awaitable[list[dict[str, Any]]]]


@dataclass(frozen=True)
class _PlansCacheEntry:
    plans: tuple[dict[str, Any], ...]
    expires_at: float


_PLANS_CACHE: dict[str, _PlansCacheEntry] = {}
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


async def _fetch_url(url: str, timeout: float) -> str:
    def _get() -> str:
        req = urllib.request.Request(  # noqa: S310 — URL нормализуется/берётся из whitelist FirstByte
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


def clear_provider_plan_cache(provider_id: str | None = None) -> None:
    """Очистить in-memory кэш тарифов (используется тестами и будущей ручной инвалидацией)."""
    if provider_id is None:
        _PLANS_CACHE.clear()
        return
    _PLANS_CACHE.pop(provider_id.strip().lower(), None)


def _clone_plans(plans: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(p) for p in plans]


def _extend_stale_cache(provider_id: str, cached: _PlansCacheEntry) -> list[dict[str, Any]]:
    entry = _PlansCacheEntry(cached.plans, time.monotonic() + _PROVIDER_PLANS_CACHE_TTL_S)
    _PLANS_CACHE[provider_id] = entry
    return _clone_plans(entry.plans)


async def _refresh_lock(provider_id: str) -> asyncio.Lock:
    async with _PLANS_LOCK:
        return _PLANS_REFRESH_LOCKS.setdefault(provider_id, asyncio.Lock())


async def _cached_provider_plans(provider_id: str, fetcher: _PlanFetcher) -> list[dict[str, Any]]:
    """TTL-кэш в памяти процесса, чтобы UI не парсил сайт провайдера на каждый запрос."""
    key = provider_id.strip().lower()
    now = time.monotonic()
    cached = _PLANS_CACHE.get(key)
    if cached and cached.expires_at > now:
        return _clone_plans(cached.plans)

    async with await _refresh_lock(key):
        now = time.monotonic()
        cached = _PLANS_CACHE.get(key)
        if cached and cached.expires_at > now:
            return _clone_plans(cached.plans)

        try:
            fresh = await fetcher()
        except Exception as exc:
            if cached:
                log.warning("provider_plans_cache_stale", provider=key, error=str(exc))
                return _extend_stale_cache(key, cached)
            raise

        if not fresh:
            if cached:
                log.warning("provider_plans_cache_stale_empty", provider=key)
                return _extend_stale_cache(key, cached)
            return []

        entry = _PlansCacheEntry(tuple(_clone_plans(fresh)), time.monotonic() + _PROVIDER_PLANS_CACHE_TTL_S)
        _PLANS_CACHE[key] = entry
        return _clone_plans(entry.plans)


async def fetch_firstbyte_plans(timeout: float = _FIRSTBYTE_TIMEOUT) -> list[dict[str, Any]]:
    """Скачать сайт FirstByte и вернуть текущие тарифы."""
    seeds, sitemap = await asyncio.gather(_fetch_many(_FIRSTBYTE_SEEDS, timeout), _fetch_sitemap(timeout))
    urls = discover_firstbyte_plan_urls(seeds, sitemap)
    pages = {**seeds, **await _fetch_many((u for u in urls if u not in seeds), timeout)}
    return parse_firstbyte_plans(pages)


async def plans_for(provider_id: str) -> list[dict[str, Any]]:
    """Планы провайдера по его id (пустой список, если каталога нет/сайт недоступен)."""
    if (provider_id or "").strip().lower() != "firstbyte":
        return []
    return await _cached_provider_plans("firstbyte", fetch_firstbyte_plans)


def plan_bandwidth_bytes(plan: dict) -> int | None:
    """Квота трафика плана в байтах (None = безлимит/не указано)."""
    tb = plan.get("trafficTb")
    return int(tb * TIB) if tb else None
