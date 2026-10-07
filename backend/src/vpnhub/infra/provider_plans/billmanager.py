"""Общий парсер публичного прайс-листа ISPsystem BILLmanager — биллинга большинства российских хостеров.

BILLmanager отдаёт прайс без авторизации: `<billmgr>?func=pricelist.export&out=xml`. С `itemtype=vds` в
выгрузке остаются только виртуальные серверы, с `onlyavailable=on` — только то, что можно заказать.
У тарифа (`<pricelist>`) есть базовая цена по периодам (`price/period[type=month][length=1]`), список
дата-центров и аддоны с включённым в тариф объёмом (`addonlimit`): процессоры (`ncpu`), память (`mem`),
диск (`disc`), исходящий канал (`outbound`, Мбит/с) или трафик (в ГБ/ТБ). Поэтому новый провайдер на
BILLmanager — это только адрес его биллинга (`BillmanagerSource`), а разбор общий.

Тарифы-конструкторы (базовая цена 0 — сумма складывается из аддонов при заказе) пропускаем: «цены от»
у них нет. Тариф с несколькими дата-центрами разворачивается по каждому.
"""

from __future__ import annotations

import contextlib
import html as html_lib
import io
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, BinaryIO, Protocol, cast

import certifi
import structlog

from .common import _speed_mbps, _storage_type_from_text, make_plan, sort_plans
from .http import _USER_AGENT, run_io
from .whmcs import _parse_specs, _segments, _spec_lines

log = structlog.get_logger(__name__)

# выгрузка бывает на десятки мегабайт и собирается биллингом десятками секунд — ждём дольше обычного
_TIMEOUT = 60.0
_MAX_BYTES = 40_000_000
_HEAD_BYTES = 65_536
_TAG_RE = re.compile(r"<[^>]+>")
_DTD_RE = re.compile(r"<!DOCTYPE", re.I)


@dataclass(frozen=True)
class BillmanagerSource:
    """Биллинг провайдера и то, чего нет в самой выгрузке."""

    billmgr_url: str  # адрес `.../billmgr` (без параметров)
    site_url: str  # страница тарифов на сайте — туда ведёт кнопка «Купить»
    default_region: str = ""  # если у тарифа не указан дата-центр
    country: str = ""  # ISO-код, если все дата-центры провайдера в одной стране
    dc_countries: Mapping[str, str] = field(default_factory=dict)  # подстрока имени ДЦ → ISO-код
    disk_type: str = ""  # если тип диска не назван в имени/описании тарифа
    itemtype: str = "vds"


def export_url(source: BillmanagerSource) -> str:
    query = urllib.parse.urlencode(
        {"func": "pricelist.export", "out": "xml", "itemtype": source.itemtype, "onlyavailable": "on"}
    )
    return f"{source.billmgr_url}?{query}"


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    found = el.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _plain(raw: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG_RE.sub(" ", raw))).strip()


def _monthly_cost(price: ET.Element | None) -> float | None:
    if price is None:
        return None
    for period in price.findall("period"):
        if period.get("type") == "month" and period.get("length") == "1":
            try:
                return float(period.get("cost") or "")
            except ValueError:
                return None
    return None


_UNMETERED_RE = re.compile(r"unmet+ered|unlimited|безлимит", re.I)
_SPEED_UNITS = ("mbps", "mbit", "мбит", "gbps", "gbit", "гбит")
_VOLUME_UNITS = ("mb", "mib", "мб", "gb", "gib", "гб", "tb", "tib", "тб")
_UNLIMITED = 99_999  # 999999 в addonlimit — «без ограничения»


def _measure(addon: ET.Element) -> str:
    """Единица аддона: у него два тега measure — id скаляром и объект с именем; нужен второй."""
    for m in addon.findall("measure"):
        if name := _text(m, "name"):
            return name.lower()
    return ""


def _to_gb(value: float, unit: str) -> float:
    if unit.startswith(("mb", "mib", "мб")):
        return value / 1024
    if unit.startswith(("tb", "tib", "тб")):
        return value * 1024
    return value


@dataclass
class _Specs:
    cpu: int | None = None
    ram_gb: float | None = None
    disk_gb: float | None = None
    port_mbps: int = 0
    traffic_tb: float | None = None
    disk_hint: str = ""
    inbound_mbps: int = 0  # входящий канал — только если исходящий не указан
    traffic_known: bool = False  # квота указана или явно безлимитная


def _addon_specs(addons: Iterable[ET.Element]) -> _Specs:
    specs = _Specs()
    for addon in addons:
        info = addon.find("addon_itemtype_info")
        intname = (_text(info, "intname") or _text(addon, "intname")).lower()
        try:
            limit = float(_text(addon, "addonlimit") or "")
        except ValueError:
            continue
        unit = _measure(addon)
        name = f"{_text(addon, 'name')} {_text(addon, 'name_ru')}"
        if intname in {"ncpu", "cpu", "vcpu", "cores"}:
            specs.cpu = int(limit)
        elif intname in {"mem", "ram", "memory"}:
            # без единицы: сотни и больше — это МБ, единицы — ГБ
            specs.ram_gb = _to_gb(limit, unit or ("mb" if limit >= 128 else "gb"))
        elif intname in {"disc", "disk", "hdd", "ssd", "nvme", "disk_space"} or "disk" in intname:
            specs.disk_gb = _to_gb(limit, unit or "gb")
            specs.disk_hint = specs.disk_hint or _storage_type_from_text(f"{intname} {name}")
        elif intname in {"bandwidth", "outbound", "inbound", "traffic", "port", "channel"} or "traffic" in intname:
            if unit.startswith(_SPEED_UNITS) and 0 < limit < _UNLIMITED:
                mbps = int(limit * (1000 if unit.startswith("g") else 1))
                if intname == "inbound":
                    specs.inbound_mbps = mbps
                else:
                    specs.port_mbps = max(specs.port_mbps, mbps)
            elif unit.startswith(_VOLUME_UNITS) and 0 < limit < _UNLIMITED and specs.traffic_tb is None:
                specs.traffic_tb = round(_to_gb(limit, unit) / 1024, 3)
                specs.traffic_known = True
            if _UNMETERED_RE.search(name):  # «Unmetred traffic 100 Mbit/s», «Безлимитный трафик»
                specs.traffic_known = True
            # скорость порта часто только в названии аддона: «Port 1 Gbit/s, 32 Tb included»
            if (
                not specs.port_mbps
                and (speed := _speed_mbps(name))
                and re.search(r"[mg]bit|[мг]бит|[mg]bps", name, re.I)
            ):
                specs.port_mbps = speed
    specs.port_mbps = specs.port_mbps or specs.inbound_mbps
    return specs


def _description_specs(about: str, specs: _Specs) -> _Specs:
    """Добрать CPU/RAM/диск из названия и описания тарифа, если их нет в аддонах (как на витринах WHMCS)."""
    parsed = _parse_specs(_spec_lines(_segments(about)))
    specs.cpu = specs.cpu or parsed.cpu
    specs.ram_gb = specs.ram_gb or parsed.ram_gb
    specs.disk_gb = specs.disk_gb or parsed.disk_gb
    specs.disk_hint = specs.disk_hint or parsed.disk_type
    specs.port_mbps = specs.port_mbps or parsed.port_mbps or 0
    if specs.traffic_tb is None:
        specs.traffic_tb = parsed.traffic_tb
    specs.traffic_known = specs.traffic_known or parsed.traffic_seen
    return specs


_DC_CODE_RE = re.compile(r"[(\[]([A-Z]{2})[)\]]")


def _dc_country(source: BillmanagerSource, region: str) -> str:
    """Страна ДЦ: из конфига провайдера или кода в скобках в имени («Host-Telecom (CZ)»)."""
    for needle, code in source.dc_countries.items():
        if needle.lower() in region.lower():
            return code
    if m := _DC_CODE_RE.search(region):
        return m.group(1)
    return source.country


def _datacenters(pricelist: ET.Element, default_region: str) -> list[tuple[str, str]]:
    out = []
    for dc in pricelist.findall("datacenter"):
        name = _text(dc, "name_ru") or _text(dc, "name")
        if name:
            out.append((_text(dc, "id") or name, name))
    return out or ([("", default_region)] if default_region else [])


class _Readable(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class _CappedStream:
    """Поток ответа «голова + остаток» с потолком размера: выгрузку читаем потоково, не держа её целиком."""

    def __init__(self, head: bytes, rest: BinaryIO, cap: int) -> None:
        self._head = head
        self._rest = rest
        self._left = cap - len(head)

    def read(self, size: int = -1) -> bytes:
        if self._head:
            chunk, self._head = self._head, b""
            return chunk
        if self._left <= 0:
            return b""
        chunk = self._rest.read(self._left if size < 0 else min(size, self._left))
        self._left -= len(chunk)
        return chunk


def _iter_pricelists(stream: _Readable) -> Iterator[ET.Element]:
    """Тарифы верхнего уровня потоком: выгрузка бывает на 10+ МБ, целиком в дерево её не строим —
    каждый обработанный `<pricelist>` очищается, и память держит только текущий тариф."""
    depth = 0
    for event, elem in ET.iterparse(stream, events=("start", "end")):  # noqa: S314 — DTD отсечён заранее
        if event == "start":
            depth += 1
            continue
        depth -= 1
        if depth == 1 and elem.tag == "pricelist":
            yield elem
            elem.clear()


def _pricelist_plans(provider_id: str, source: BillmanagerSource, pl: ET.Element) -> list[dict[str, Any]]:
    if _text(pl, "active") != "on" or "on" in {_text(pl, "hideinorder"), _text(pl, "archived")}:
        return []
    intname = _text(pl.find("itemtype_info"), "intname")
    if intname and intname != source.itemtype:
        return []
    price_el = pl.find("price")
    cost = _monthly_cost(price_el)
    currency = (price_el.get("currency") if price_el is not None else "") or ""
    name = _text(pl, "name_ru") or _text(pl, "name")
    description = _text(pl, "description_ru") or _text(pl, "description")
    specs = _addon_specs(pl.findall("addon"))
    if not (specs.cpu and specs.ram_gb and specs.disk_gb):
        specs = _description_specs(f"{name}<br>{description}", specs)
    if not name or not cost or cost <= 0 or not currency or not specs.cpu or not specs.ram_gb or not specs.disk_gb:
        return []
    about = _plain(f"{name} {description}")
    disk_type = _storage_type_from_text(about) or specs.disk_hint or source.disk_type
    return [
        make_plan(
            plan_id=f"{provider_id}-{_text(pl, 'id')}" + (f"-{dc_id}" if dc_id else ""),
            name=f"{name} · {region}",
            region=region,
            country=_dc_country(source, region),
            cpu=specs.cpu,
            ram_gb=round(specs.ram_gb, 2),
            disk_gb=round(specs.disk_gb),
            disk_type=disk_type,
            port_mbps=specs.port_mbps,
            traffic_tb=specs.traffic_tb,
            traffic_known=specs.traffic_known,
            price=cost,
            currency=currency.upper(),
            source_url=source.site_url,
        )
        for dc_id, region in _datacenters(pl, source.default_region)
    ]


def _parse_stream(provider_id: str, source: BillmanagerSource, stream: BinaryIO) -> list[dict[str, Any]]:
    # Выгрузка приходит со стороннего сервера. DTD в ней не бывает, а через DTD (внутренние сущности)
    # идут XML-атаки вроде billion laughs. DTD допустим только в прологе, до корневого элемента, —
    # поэтому достаточно проверить начало документа; DTD дальше — уже не well-formed XML.
    head = stream.read(_HEAD_BYTES)
    if _DTD_RE.search(head.decode("utf-8", "replace")):
        log.warning("provider_plans_billmanager_dtd_rejected", provider=provider_id)
        return []
    plans: list[dict[str, Any]] = []
    try:
        for pl in _iter_pricelists(_CappedStream(head, stream, _MAX_BYTES)):
            plans.extend(_pricelist_plans(provider_id, source, pl))
    except ET.ParseError:
        return []
    return sort_plans(plans)


def parse_billmanager_export(provider_id: str, source: BillmanagerSource, xml_text: str) -> list[dict[str, Any]]:
    """Тарифы VDS из XML-выгрузки прайс-листа BILLmanager."""
    return _parse_stream(provider_id, source, io.BytesIO(xml_text.encode("utf-8")))


def _open_export(url: str, timeout: float) -> BinaryIO:
    req = urllib.request.Request(  # noqa: S310 — адрес биллинга из конфига провайдеров
        url, headers={"User-Agent": _USER_AGENT, "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8"}
    )
    ctx = ssl.create_default_context(cafile=certifi.where())
    return cast(BinaryIO, urllib.request.urlopen(req, timeout=timeout, context=ctx))  # noqa: S310


def _download_plans(provider_id: str, source: BillmanagerSource, timeout: float) -> list[dict[str, Any]]:
    with contextlib.closing(_open_export(export_url(source), timeout)) as resp:
        return _parse_stream(provider_id, source, resp)


async def fetch_billmanager_plans(
    provider_id: str, source: BillmanagerSource, timeout: float = _TIMEOUT
) -> list[dict[str, Any]]:
    """Скачать (потоково) публичный прайс BILLmanager провайдера и вернуть VDS-тарифы."""
    try:
        return await run_io(_download_plans, provider_id, source, timeout)
    except (TimeoutError, OSError, UnicodeDecodeError, urllib.error.URLError) as exc:
        log.warning("provider_plans_fetch_failed", provider=provider_id, url=export_url(source), error=str(exc))
        return []
