"""Динамический каталог тарифных планов провайдеров."""

from __future__ import annotations

import json
from typing import Any

import pytest

from vpnhub.infra import provider_plans
from vpnhub.infra.provider_plans import (
    TIB,
    discover_ahost_plan_urls,
    discover_firstbyte_plan_urls,
    discover_ishosting_plan_urls,
    discover_ufo_countries,
    parse_ahost_plans,
    parse_firstbyte_plans,
    parse_ishosting_plans,
    parse_serverspace_plans,
    parse_ufo_plans,
    plan_bandwidth_bytes,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clear_provider_plan_cache() -> None:
    provider_plans.clear_provider_plan_cache()


FIRSTBYTE_TABLE = """
<html><body>
<a href="/vps-vds/japan/">Japan</a>
<a href="/vps-vds/vds-ubuntu/">Ubuntu</a>
<a href="/dedicated/">Dedicated</a>
<table class="table-transformer">
  <thead><tr>
    <th>Тариф</th><th>Процессор</th><th>Оперативная память, MB</th>
    <th>Диск SSD, GB</th><th>Канал</th><th>Страна</th><th>Цена, руб./мес.</th><th></th>
  </tr></thead>
  <tbody>
    <tr>
      <td>MSK-KVM-SSD-2<sup>2</sup></td>
      <td>3vCPU</td>
      <td>1024</td>
      <td>40</td>
      <td>200 Мб/с<br>5 Тб/мес</td>
      <td><span class="tooltipd" data-title="Россия, Москва, Data Center TIER3"><img src="ru.png"></span></td>
      <td><div class="reprices"><span class="strikedprice">399 ₽</span>349 ₽</div></td>
      <td><a>заказать</a></td>
    </tr>
    <tr>
      <td>MSK-
highhdd-KVM-SAS-1</td>
      <td>1vCPU</td>
      <td>1024</td>
      <td>120</td>
      <td>трафик безлимитный 200Mb/s</td>
      <td><span class="tooltipd" data-title="Россия, Москва, Data Center TIER3"></span></td>
      <td><span class="price-dollar">415 ₽</span></td>
      <td><a>заказать</a></td>
    </tr>
    <tr>
      <td>KVM-SSD-1-DB<sup>1</sup></td>
      <td>1vCPU</td>
      <td>1024</td>
      <td>10</td>
      <td>200 Мб/с<br>4 Тб/мес</td>
      <td><div class="tooltipd" data-title="ОАЭ"></div></td>
      <td><div class="reprices"><span class="strikedprice">598 ₽</span>429 ₽</div></td>
      <td><p>Ожидается</p></td>
    </tr>
  </tbody>
</table>
</body></html>
"""

UFO_LANDING = """
<html><body>
<script>
 window.wp_ajax = {
   ajax_url: "https://ufo.hosting/wp-admin/admin-ajax.php",
   nonce: "nonce-123"
 };
</script>
<ul id="country-list">
  <li class="dropdown-option" data-value="india" data-country="Индия">Индия</li>
  <li class="dropdown-option" data-value="kazakhstan" data-country="Казахстан">Казахстан</li>
  <li class="dropdown-option" data-value="russia" data-country="Россия">Россия</li>
</ul>
</body></html>
"""

UFO_RUSSIA_CARDS = """
<div class="serv-card serv-card-v animate-fade-in flex" data-cat="VPS/VDS">
  <div>
    <h3>Тариф Naos</h3>
    <span>Страна Россия</span>
    <div class="price-item" data-base-price="577"><span class="current-price">577₽</span></div>
    <div><span>CPU:</span><span>vCore x1</span></div>
    <div><span>RAM:</span><span>1 GB ECC</span></div>
    <div><span>SSD:</span><span>25 GB NVMe</span></div>
    <div><span>Сеть:</span><span>10 Gbps*</span></div>
    <button>Выбрать</button>
  </div>
</div>
"""

UFO_INDIA_CARDS = """
<div class="serv-card serv-card-v animate-fade-in flex" data-cat="VPS/VDS">
  <div>
    <h3>Тариф Brachium</h3>
    <span>Страна Индия</span>
    <div class="price-item" data-base-price="977"><span class="current-price">977₽</span></div>
    <div><span>CPU:</span><span>vCore x2</span></div>
    <div><span>RAM:</span><span>4 GB ECC</span></div>
    <div><span>SSD:</span><span>60 GB NVMe</span></div>
    <div><span>Сеть:</span><span>1 Gbps*</span></div>
    <button>Выбрать</button>
  </div>
</div>
"""

ISHOSTING_LANDING = """
<html><body>
<a href="/en/vps/at">Austria</a>
<a href="/en/vps/ae">UAE</a>
<a href="/en/vps/linux">Linux VPS</a>
<a href="/en/vps/1011_1y">Start</a>
</body></html>
"""

ISHOSTING_AT_CARDS = """
<html><body>
<ul>
  <li><div class="services-list-cards-item">
    <div class="title"><span class="main"><a href="/en/vps/879_1y">Lite</a></span></div>
    <div class="labels"><span class="location"><span class="fi fi-at"></span> Austria </span></div>
    <div class="price"><span class="value"><span class="from text">From</span>$5.94</span>
      <span class="period">/ 1 month</span></div>
    <ul class="specs">
      <li class="specs-item"><span class="value">Xeon 2.90 GHz</span><span class="type">CPU</span></li>
      <li class="specs-item"><span class="value">1 Gb</span><span class="type">RAM</span></li>
      <li class="specs-item"><span class="value">20GB NVMe</span><span class="type">Drive</span></li>
      <li class="specs-item"><span class="value">2 Tb</span><span class="type">Bandwidth</span></li>
    </ul>
    <ul class="tags"><li class="tags-item"><span>1Gbps Port</span></li></ul>
  </div></li>
  <li><div class="services-list-cards-item">
    <div class="title"><span class="main"><a href="/en/vps/1012_1y">Medium</a></span></div>
    <div class="labels"><span class="location"><span class="fi fi-at"></span> Austria </span></div>
    <div class="price"><span class="value"><span class="from text">From</span>$21.24</span>
      <span class="period">/ 1 month</span></div>
    <ul class="specs">
      <li class="specs-item"><span class="value">Xeon 3x2.90 GHz</span><span class="type">CPU</span></li>
      <li class="specs-item"><span class="value">4 Gb</span><span class="type">RAM</span></li>
      <li class="specs-item"><span class="value">40GB NVMe</span><span class="type">Drive</span></li>
      <li class="specs-item"><span class="value">Unmetered</span><span class="type">Bandwidth</span></li>
    </ul>
    <ul class="tags"><li class="tags-item"><span>1Gbps Port</span></li></ul>
  </div></li>
  <li><div class="services-list-cards-item">
    <div class="title"><span class="main"><a href="/en/vps/1046_1y">Lite - Linux NVMe</a></span></div>
    <div class="labels"><span class="location"><span class="fi fi-ee"></span> Estonia </span></div>
    <div class="price"><span class="value">$12.00</span></div>
  </div></li>
</ul>
</body></html>
"""

AHOST_LANDING = """
<html><body>
  <a href="/ru/vds-linux/germany#section-title"><div class="country-title">Германия</div></a>
  <a href="/ru/vds-linux/netherlands#section-title"><div class="country-title">Нидерланды</div></a>
  <a href="/ru/vds-windows/germany#section-title"><div class="country-title">Windows Германия</div></a>
  <a href="/ru/vds-linux/linux">Linux VPS</a>
</body></html>
"""

AHOST_GERMANY_CARDS = """
<html><body>
<div class="country-description-title">
  <div class="title">Тарифы</div>
  <div class="d-flex align-items-center country-name-block">
    <div class="flag"></div><div class="name">Германия</div>
  </div>
</div>
<div class="rates-items-list">
  <div class="item-price-block-col col-12 rate-item" data-id="218">
    <div class="rate-item_container">
      <div class="rate-item_title">KVM SMART</div>
      <div class="rate-item_price">5<span>€</span></div>
      <ul class="rate-item_list">
        <li><div class="quantity">1 ядро</div><div class="info">процессор Intel Xeon 2,4 ГГц</div></li>
        <li><div class="quantity">1024 Мб</div><div class="info">оперативной памяти</div></li>
        <li><div class="quantity">10 Гб</div><div class="info">SSD диска</div></li>
        <li><div class="quantity">1.00 Тб</div><div class="info">Трафика в месяц</div></li>
      </ul>
    </div>
  </div>
  <div class="item-price-block-col col-12 rate-item" data-id="38">
    <div class="rate-item_container">
      <div class="rate-item_title">KVM BASIC</div>
      <div class="rate-item_price">15<span>€</span></div>
      <ul class="rate-item_list">
        <li><div class="quantity">2 ядра</div><div class="info">процессор Intel Xeon 2,4 ГГц</div></li>
        <li><div class="quantity">4096 Мб</div><div class="info">оперативной памяти</div></li>
        <li><div class="quantity">50 Гб</div><div class="info">SSD диска</div></li>
        <li><div class="quantity">4.00 Тб</div><div class="info">Трафика в месяц</div></li>
      </ul>
    </div>
  </div>
  <div class="item-price-block-col col-12 rate-item">
    <div class="rate-item_title">Windows START</div>
    <div class="rate-item_price">9<span>€</span></div>
  </div>
</div>
</body></html>
"""

SERVERSPACE_PRICE_PAGE = """
<html><body>
<select id="fixedDc">
  <option value="239">Ташкент</option>
  <option value="2" selected data-select-badge="Sold out" disabled>Москва, 5th Gen Intel</option>
</select>
<div class="table">
  <div class="table__row plans-row show">
    <div class="table__cell cell-ram"><span>1 ГБ</span></div>
    <div class="table__cell cell-cpu"><span>1 Core</span></div>
    <div class="table__cell cell-ssd"><span>25 ГБ</span></div>
    <div class="table__cell cell-bandwidth"><span>50 Мбит/c</span></div>
    <div class="table__cell">
      <div class="price">
        <span class="price__value">0.609</span>
        <span class="price__symbol">₽</span>
        <span class="price__period">/час</span>
      </div>
    </div>
    <div class="table__cell">
      <div class="price">
        <span class="price__value">438.21</span>
        <span class="price__symbol">₽</span>
        <span class="price__period">/мес</span>
      </div>
    </div>
  </div>
  <div class="table__row plans-row show">
    <div class="table__cell cell-ram"><span>2 ГБ</span></div>
    <div class="table__cell cell-cpu"><span>2 Core</span></div>
    <div class="table__cell cell-ssd"><span>60 ГБ</span></div>
    <div class="table__cell cell-bandwidth"><span>50 Мбит/c</span></div>
    <div class="table__cell"><div class="price"><span class="price__value">2.165</span><span>₽</span></div></div>
    <div class="table__cell"><div class="price"><span class="price__value">1 559.13</span><span>₽</span></div></div>
  </div>
</div>
</body></html>
"""

SERVERSPACE_CHALLENGE_PAGE = "<html><script>var __js_p_ = 1; var __jhash_ = 2;</script>ajaxload.info</html>"


def test__parse_firstbyte_plans__extracts_current_price_specs_region_and_availability() -> None:
    plans = parse_firstbyte_plans({"https://firstbyte.ru/vps-vds/kvm-ssd/": FIRSTBYTE_TABLE})
    by_id = {p["id"]: p for p in plans}

    assert by_id["fb-msk-kvm-ssd-2"] == {
        "id": "fb-msk-kvm-ssd-2",
        "name": "MSK-KVM-SSD-2 · Россия, Москва",
        "region": "Россия, Москва",
        "cpu": 3,
        "ramGb": 1,
        "diskGb": 40,
        "diskType": "SSD",
        "portMbps": 200,
        "trafficTb": 5,
        "price": 349,
        "currency": "RUB",
        "period": "month",
        "available": True,
        "sourceUrl": "https://firstbyte.ru/vps-vds/kvm-ssd/",
    }
    assert by_id["fb-msk-highhdd-kvm-sas-1"]["trafficTb"] is None
    assert by_id["fb-msk-highhdd-kvm-sas-1"]["portMbps"] == 200
    assert by_id["fb-kvm-ssd-1-db"]["region"] == "ОАЭ"
    assert by_id["fb-kvm-ssd-1-db"]["available"] is False


def test__discover_firstbyte_plan_urls__uses_seed_links_and_sitemap_but_skips_robots_os_pages() -> None:
    sitemap = """
    <urlset>
      <url><loc><![CDATA[https://firstbyte.ru/vps-vds/kvm-business/]]></loc></url>
      <url><loc><![CDATA[https://firstbyte.ru/vps-vds/vds-ubuntu/]]></loc></url>
      <url><loc><![CDATA[https://firstbyte.ru/vps-vds/tariffs-archive/]]></loc></url>
    </urlset>
    """

    urls = discover_firstbyte_plan_urls({"https://firstbyte.ru/vps-vds/kvm-ssd/": FIRSTBYTE_TABLE}, sitemap)

    assert "https://firstbyte.ru/vps-vds/japan/" in urls
    assert "https://firstbyte.ru/vps-vds/kvm-business/" in urls
    assert "https://firstbyte.ru/vps-vds/vds-ubuntu/" not in urls
    assert "https://firstbyte.ru/vps-vds/tariffs-archive/" not in urls
    assert "https://firstbyte.ru/dedicated/" not in urls


def test__discover_ufo_countries__extracts_country_dropdown() -> None:
    assert discover_ufo_countries(UFO_LANDING) == [
        ("india", "Индия"),
        ("kazakhstan", "Казахстан"),
        ("russia", "Россия"),
    ]


def test__parse_ufo_plans__extracts_cards_from_landing_and_ajax_fragments() -> None:
    plans = parse_ufo_plans(
        {
            "https://ufo.hosting/vps-vds#country=russia": UFO_RUSSIA_CARDS,
            "https://ufo.hosting/vps-vds#country=india": UFO_INDIA_CARDS,
        }
    )
    by_id = {p["id"]: p for p in plans}

    assert by_id["ufo-russia-naos"] == {
        "id": "ufo-russia-naos",
        "name": "Naos · Россия",
        "region": "Россия",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 25,
        "diskType": "NVMe",
        "portMbps": 10000,
        "trafficTb": None,
        "price": 577,
        "currency": "RUB",
        "period": "month",
        "available": True,
        "sourceUrl": "https://ufo.hosting/vps-vds#country=russia",
    }
    assert by_id["ufo-india-brachium"]["region"] == "Индия"
    assert by_id["ufo-india-brachium"]["portMbps"] == 1000


def test__discover_ishosting_plan_urls__uses_country_links_and_static_fallback() -> None:
    urls = discover_ishosting_plan_urls({"https://ishosting.com/en/vps": ISHOSTING_LANDING})

    assert "https://ishosting.com/en/vps/at" in urls
    assert "https://ishosting.com/en/vps/ae" in urls
    assert "https://ishosting.com/en/vps/nl" in urls  # fallback list if landing page is partial
    assert "https://ishosting.com/en/vps/linux" not in urls
    assert "https://ishosting.com/en/vps/1011_1y" not in urls


def test__parse_ishosting_plans__extracts_cards_and_skips_special_offers() -> None:
    plans = parse_ishosting_plans({"https://ishosting.com/en/vps/at": ISHOSTING_AT_CARDS})
    by_id = {p["id"]: p for p in plans}

    assert by_id["ishosting-austria-lite"] == {
        "id": "ishosting-austria-lite",
        "name": "Lite · Austria",
        "region": "Austria",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 20,
        "diskType": "NVMe",
        "portMbps": 1000,
        "trafficTb": 2,
        "price": 5.94,
        "currency": "USD",
        "period": "month",
        "available": True,
        "sourceUrl": "https://ishosting.com/en/vps/at",
    }
    assert by_id["ishosting-austria-medium"]["cpu"] == 3
    assert by_id["ishosting-austria-medium"]["trafficTb"] is None
    assert "ishosting-estonia-lite-linux-nvme" not in by_id


def test__discover_ahost_plan_urls__uses_country_links_and_static_fallback() -> None:
    urls = discover_ahost_plan_urls({"https://ahost.eu/ru/vds-linux": AHOST_LANDING})

    assert "https://ahost.eu/ru/vds-linux/germany" in urls
    assert "https://ahost.eu/ru/vds-linux/netherlands" in urls
    assert "https://ahost.eu/ru/vds-linux/japan" in urls  # fallback list if landing page is partial
    assert "https://ahost.eu/ru/vds-windows/germany" not in urls
    assert "https://ahost.eu/ru/vds-linux/linux" not in urls


def test__parse_ahost_plans__extracts_cards_without_port() -> None:
    plans = parse_ahost_plans({"https://ahost.eu/ru/vds-linux/germany": AHOST_GERMANY_CARDS})
    by_id = {p["id"]: p for p in plans}

    assert by_id["ahost-germany-kvm-smart"] == {
        "id": "ahost-germany-kvm-smart",
        "name": "KVM SMART · Германия",
        "region": "Германия",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 10,
        "diskType": "SSD",
        "portMbps": 0,
        "trafficTb": 1,
        "price": 5,
        "currency": "EUR",
        "period": "month",
        "available": True,
        "sourceUrl": "https://ahost.eu/ru/vds-linux/germany",
    }
    assert by_id["ahost-germany-kvm-basic"]["cpu"] == 2
    assert by_id["ahost-germany-kvm-basic"]["ramGb"] == 4
    assert by_id["ahost-germany-kvm-basic"]["trafficTb"] == 4
    assert "ahost-germany-windows-start" not in by_id


def test__parse_serverspace_plans__extracts_fixed_plans_for_all_dcs() -> None:
    plans = parse_serverspace_plans({"https://serverspace.ru/conditions/price/": SERVERSPACE_PRICE_PAGE})
    by_id = {p["id"]: p for p in plans}

    assert by_id["serverspace-dc-2-fixed-1c-1gb-25gb"] == {
        "id": "serverspace-dc-2-fixed-1c-1gb-25gb",
        "name": "Fixed 1C/1GB/25GB SSD · Москва, 5th Gen Intel",
        "region": "Москва, 5th Gen Intel",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 25,
        "diskType": "SSD",
        "portMbps": 50,
        "trafficTb": None,
        "price": 438.21,
        "currency": "RUB",
        "period": "month",
        "available": False,
        "sourceUrl": "https://serverspace.ru/conditions/price/",
    }
    assert by_id["serverspace-dc-239-fixed-1c-1gb-25gb"]["region"] == "Ташкент"
    assert by_id["serverspace-dc-239-fixed-1c-1gb-25gb"]["available"] is True
    assert by_id["serverspace-dc-239-fixed-2c-2gb-60gb"]["price"] == 1559.13
    assert by_id["serverspace-dc-239-fixed-2c-2gb-60gb"]["currency"] == "RUB"
    assert set(by_id) == {
        "serverspace-dc-2-fixed-1c-1gb-25gb",
        "serverspace-dc-2-fixed-2c-2gb-60gb",
        "serverspace-dc-239-fixed-1c-1gb-25gb",
        "serverspace-dc-239-fixed-2c-2gb-60gb",
    }


def test__parse_serverspace_plans__skips_js_challenge() -> None:
    assert parse_serverspace_plans({"https://serverspace.ru/conditions/price/": SERVERSPACE_CHALLENGE_PAGE}) == []


async def test__fetch_serverspace_plans__loads_price_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_serverspace_price_page(timeout: float) -> str:
        assert timeout > 0
        return SERVERSPACE_PRICE_PAGE

    monkeypatch.setattr(provider_plans.serverspace, "_fetch_serverspace_price_page", fake_fetch_serverspace_price_page)

    plans = await provider_plans.fetch_serverspace_plans()

    assert [p["id"] for p in plans] == [
        "serverspace-dc-2-fixed-1c-1gb-25gb",
        "serverspace-dc-2-fixed-2c-2gb-60gb",
        "serverspace-dc-239-fixed-1c-1gb-25gb",
        "serverspace-dc-239-fixed-2c-2gb-60gb",
    ]


async def test__fetch_ahost_plans__loads_country_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_url(url: str, timeout: float) -> str:
        assert timeout > 0
        if url == "https://ahost.eu/ru/vds-linux":
            return AHOST_LANDING
        if url == "https://ahost.eu/ru/vds-linux/germany":
            return AHOST_GERMANY_CARDS
        return ""

    monkeypatch.setattr(provider_plans.ahost, "_fetch_url", fake_fetch_url)

    plans = await provider_plans.fetch_ahost_plans()

    assert [p["id"] for p in plans] == ["ahost-germany-kvm-smart", "ahost-germany-kvm-basic"]


async def test__fetch_ishosting_plans__loads_country_pages_with_browser_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        assert timeout > 0
        if url == "https://ishosting.com/en/vps":
            return ISHOSTING_LANDING
        if url == "https://ishosting.com/en/vps/at":
            return ISHOSTING_AT_CARDS
        return ""

    monkeypatch.setattr(provider_plans.ishosting, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.fetch_ishosting_plans()

    assert [p["id"] for p in plans] == ["ishosting-austria-lite", "ishosting-austria-medium"]


async def test__fetch_ufo_plans__loads_country_fragments_with_page_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_url(url: str, timeout: float) -> str:
        assert url == "https://ufo.hosting/vps-vds"
        assert timeout > 0
        return UFO_LANDING

    async def fake_post_form_url(url: str, form: dict[str, str], timeout: float) -> str:
        assert url == "https://ufo.hosting/wp-admin/admin-ajax.php"
        assert form["action"] == "fetch_services_by_city"
        assert form["nonce"] == "nonce-123"
        assert timeout > 0
        html = UFO_INDIA_CARDS if form["cities"] == "india" else ""
        return json.dumps({"success": True, "data": {"vds": html}})

    monkeypatch.setattr(provider_plans.ufo, "_fetch_url", fake_fetch_url)
    monkeypatch.setattr(provider_plans.ufo, "_post_form_url", fake_post_form_url)

    plans = await provider_plans.fetch_ufo_plans()

    assert [p["id"] for p in plans] == ["ufo-india-brachium"]


async def test__plans_for__firstbyte_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "fb-live"}]

    monkeypatch.setattr(provider_plans, "fetch_firstbyte_plans", fake_fetch)

    assert await provider_plans.plans_for("FirstByte") == [{"id": "fb-live"}]


async def test__plans_for__ufo_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "ufo-live"}]

    monkeypatch.setattr(provider_plans, "fetch_ufo_plans", fake_fetch)

    assert await provider_plans.plans_for("UFO Hosting") == [{"id": "ufo-live"}]


async def test__plans_for__ishosting_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "ish-live"}]

    monkeypatch.setattr(provider_plans, "fetch_ishosting_plans", fake_fetch)

    assert await provider_plans.plans_for("ISHOSTING") == [{"id": "ish-live"}]


async def test__plans_for__ahost_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "ahost-live"}]

    monkeypatch.setattr(provider_plans, "fetch_ahost_plans", fake_fetch)

    assert await provider_plans.plans_for("AHost") == [{"id": "ahost-live"}]


async def test__plans_for__serverspace_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "serverspace-live"}]

    monkeypatch.setattr(provider_plans, "fetch_serverspace_plans", fake_fetch)

    assert await provider_plans.plans_for("Serverspace") == [{"id": "serverspace-live"}]


async def test__plans_for__firstbyte_caches_dynamic_catalog_and_returns_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_fetch() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return [{"id": "fb-live"}]

    monkeypatch.setattr(provider_plans, "fetch_firstbyte_plans", fake_fetch)

    first = await provider_plans.plans_for("firstbyte")
    first[0]["id"] = "mutated"

    assert await provider_plans.plans_for("FirstByte") == [{"id": "fb-live"}]
    assert calls == 1


async def test__plans_for__firstbyte_returns_stale_cache_when_refresh_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_fetch() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"id": "fb-live"}]
        raise RuntimeError("site is down")

    monkeypatch.setattr(provider_plans, "fetch_firstbyte_plans", fake_fetch)
    monkeypatch.setattr(provider_plans.cache, "_PROVIDER_PLANS_CACHE_TTL_S", 0)

    assert await provider_plans.plans_for("firstbyte") == [{"id": "fb-live"}]
    assert await provider_plans.plans_for("firstbyte") == [{"id": "fb-live"}]
    assert calls == 2


async def test__plans_for__empty_catalog_is_cached_briefly(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_fetch() -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(provider_plans, "fetch_firstbyte_plans", fake_fetch)

    assert await provider_plans.plans_for("firstbyte") == []
    assert await provider_plans.plans_for("FirstByte") == []
    assert calls == 1


async def test__plans_for__unknown_empty() -> None:
    assert await provider_plans.plans_for("nonexistent") == []
    assert await provider_plans.plans_for("") == []


def test__plan_bandwidth_bytes() -> None:
    assert plan_bandwidth_bytes({"trafficTb": 5}) == 5 * TIB
    assert plan_bandwidth_bytes({"trafficTb": None}) is None  # безлимит
    assert plan_bandwidth_bytes({}) is None
