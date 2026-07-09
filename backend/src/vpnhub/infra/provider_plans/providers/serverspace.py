"""Динамический каталог фиксированных тарифов Serverspace."""

from __future__ import annotations

import asyncio
import hashlib
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

import certifi
import structlog

from ..common import _int, _norm, _quantity_gb, _speed_mbps, _storage_type_from_text
from ..http import _BROWSER_USER_AGENT, _NoRedirect

log = structlog.get_logger(__name__)

_SERVERSPACE_PRICE_URL = "https://serverspace.ru/conditions/price/"
_SERVERSPACE_TIMEOUT = 8.0
_SERVERSPACE_CHALLENGE_MARKERS = ("__js_p_", "__jhash_", "ajaxload.info")
_SERVERSPACE_JS_COOKIE_RE = re.compile(r"__js_p_=([^;]+)")
_SERVERSPACE_HASH_COOKIE_RE = re.compile(r"(__hash_)=([^;]+)")


@dataclass
class _ServerspaceFixedPlanRow:
    ram: str = ""
    cpu: str = ""
    disk: str = ""
    bandwidth: str = ""
    price_values: list[float] = field(default_factory=list)
    currency: str = ""
    available: bool = True


@dataclass(frozen=True)
class _ServerspaceDataCenter:
    id: str
    name: str
    available: bool = True


class _ServerspaceFixedPlanParser(HTMLParser):
    """Парсер фиксированных тарифов Serverspace с блока `Fixed plans`."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[_ServerspaceFixedPlanRow] = []
        self.data_centers: list[_ServerspaceDataCenter] = []
        self.region = ""
        self._first_region = ""
        self._selected_data_center_id = ""
        self._row: _ServerspaceFixedPlanRow | None = None
        self._row_depth = 0
        self._capture: str | None = None
        self._capture_end_tag = ""
        self._capture_parts: list[str] = []
        self._in_fixed_dc_select = False
        self._option_value = ""
        self._option_selected = False
        self._option_available = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set(attrs_d.get("class", "").split())

        if tag == "select" and attrs_d.get("id") == "fixedDc":
            self._in_fixed_dc_select = True
            return
        if self._in_fixed_dc_select and tag == "option":
            badge = attrs_d.get("data-select-badge", "").lower()
            self._option_value = attrs_d.get("value", "")
            self._option_selected = "selected" in attrs_d
            self._option_available = "disabled" not in attrs_d and "sold out" not in badge
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
        elif tag == "button" and "disabled" in attrs_d:
            self._row.available = False

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
            data_center_id = _serverspace_data_center_id(self._option_value, text)
            if text and not any(dc.id == data_center_id for dc in self.data_centers):
                self.data_centers.append(
                    _ServerspaceDataCenter(id=data_center_id, name=text, available=self._option_available)
                )
            if text and self._option_selected:
                self.region = text
                self._selected_data_center_id = data_center_id
            self._option_value = ""
            self._option_selected = False
            self._option_available = True
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

    @property
    def selected_data_center(self) -> _ServerspaceDataCenter:
        if self._selected_data_center_id:
            for data_center in self.data_centers:
                if data_center.id == self._selected_data_center_id:
                    return data_center
        if self.data_centers:
            return self.data_centers[0]
        return _ServerspaceDataCenter(id="", name=self.selected_region)

    @property
    def plan_data_centers(self) -> list[_ServerspaceDataCenter]:
        return self.data_centers or [self.selected_data_center]


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


def _serverspace_data_center_id(value: str, name: str) -> str:
    clean_value = _norm(value).lower()
    if clean_value:
        slug = re.sub(r"[^a-z0-9]+", "-", clean_value).strip("-")
        if slug:
            return f"dc-{slug}"
    digest = hashlib.sha256(_norm(name).encode("utf-8")).hexdigest()[:8]
    return f"dc-{digest}"


def _serverspace_plan_id(cpu: int, ram: float, disk: float, data_center_id: str = "") -> str:
    data_center_prefix = f"{data_center_id}-" if data_center_id else ""
    return (
        f"serverspace-{data_center_prefix}"
        f"fixed-{cpu}c-{_serverspace_label_number(ram)}gb-{_serverspace_label_number(disk)}gb"
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
    data_center: _ServerspaceDataCenter,
    *,
    include_data_center_id: bool,
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
    data_center_id = data_center.id if include_data_center_id else ""
    available = data_center.available if include_data_center_id else data_center.available and row.available
    return {
        "id": _serverspace_plan_id(cpu, ram, disk, data_center_id),
        "name": f"Fixed {cpu}C/{ram_label}GB/{disk_label}GB {disk_type} · {data_center.name}",
        "region": data_center.name,
        "cpu": cpu,
        "ramGb": ram,
        "diskGb": int(disk),
        "diskType": disk_type,
        "portMbps": port,
        "trafficTb": None,
        "price": price,
        "currency": _serverspace_currency(source_url, row.currency),
        "period": "month",
        "available": available,
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
        include_data_center_id = len(parser.plan_data_centers) > 1
        for row in parser.rows:
            for data_center in parser.plan_data_centers:
                if plan := _serverspace_row_to_plan(
                    row,
                    url,
                    data_center,
                    include_data_center_id=include_data_center_id,
                ):
                    by_id.setdefault(str(plan["id"]), plan)
    return sorted(by_id.values(), key=lambda p: (str(p["region"]).lower(), float(p["price"]), str(p["id"])))


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
