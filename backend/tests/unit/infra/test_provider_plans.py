"""Динамический каталог тарифных планов провайдеров."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
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
    parse_ultahost_plans,
    parse_yun62_plans,
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

# Витрина WHMCS UltaHost (тема Twenty-One): у первой карточки правая колонка `package-side-right`
# дублирует цену/цикл — парсер обязан взять первое значение и не задваивать тариф.
ULTAHOST_STORE = """
<html><body>
  <div class="package">
    <div class="package-side package-side-left">
      <div class="package-header">
        <h3 class="package-title">VPS Basic</h3>
        <div class="package-price"><div class="price">
          <div class="price-starting-from">Starting from</div>
          <div class="price-amount"> $5.99 USD </div>
          <div class="price-cycle "> Monthly </div>
        </div></div>
      </div>
      <div class="package-body"><div class="package-content">
        <p><b>1 CPU</b> Core<br /><b>1 GB</b> RAM<br /><b>30 GB</b> NVMe SSD<br />
        <b>Unmetered</b> bandwidth<br /><b>1</b> dedicated IPs<br />Free 1-year SSL certificate</p>
      </div></div>
    </div>
    <div class="package-side package-side-right">
      <div class="price-amount"> $5.99 USD </div>
      <div class="price-cycle "> Monthly </div>
    </div>
  </div>
  <div class="package">
    <div class="package-side package-side-left">
      <div class="package-header">
        <h3 class="package-title">VPS Business</h3>
        <div class="package-price"><div class="price">
          <div class="price-starting-from">Starting from</div>
          <div class="price-amount"> $10.50 USD </div>
          <div class="price-cycle "> Monthly </div>
        </div></div>
      </div>
      <div class="package-body"><div class="package-content">
        <p><b>2 CPU</b> Core<br /><b>2 GB</b> RAM<br /><b>50 GB</b> NVMe SSD<br /><b>Unmetered</b> bandwidth</p>
      </div></div>
    </div>
  </div>
</body></html>
"""

# Страница заказа 62YUN: характеристики+месячная цена зашиты в onClick кнопки тарифа, код локации — во
# втором css-классе (tarifs frm), а карта «код→страна» — на кнопках выбора локации ($('#loc').val()).
# У каждой локации СВОЙ набор тарифов: в США есть promo-S но нет ultra-S, в Гонконге только promo-B.
YUN62_ORDER = """
<html><body>
  <div id="ordering-server__geo">
    <button onClick=" $('.frm').css('display','block'); $('#loc').val('frm'); $('#plan403').click(); ">США</button>
    <button onClick=" $('.fra').css('display','block'); $('#loc').val('fra'); $('#plan439').click(); ">Германия</button>
    <button onClick=" $('.hk').css('display','block'); $('#loc').val('hk'); $('#plan421').click(); ">Гонконг</button>
  </div>
  <input type="hidden" id="loc" value="frm">
  <div id="ordering-server__rates">
    <button class="tarifs frm " style="" id="plan403" onClick="
      orderingServerInner('1 vCPU', '1 Gb', '10 Gb NVMe', '1 IPv4');
      localStorage.setItem('diskType','nvme'); orderingServerSetPrice(219);
      $('#plan').val('403'); checkForm(); ">promo-S</button>
    <button class="tarifs frm " style="display:none;" id="plan445" onClick="
      orderingServerInner('2 vCPU', '2 Gb', '500 Gb HDD', '1 IPv4');
      localStorage.setItem('diskType','hdd'); orderingServerSetPrice(369);
      $('#plan').val('445'); checkForm(); ">promo-M</button>
    <button class="tarifs fra " style="display:none;" id="plan439" onClick="
      orderingServerInner('1 vCPU', '1 Gb', '10 Gb NVMe', '1 IPv4');
      localStorage.setItem('diskType','nvme'); orderingServerSetPrice(269);
      $('#plan').val('439'); checkForm(); ">ultra-S</button>
    <button class="tarifs hk " style="display:none;" id="plan421" onClick="
      orderingServerInner('4 vCPU', '8 Gb', '150 Gb NVMe', '1 IPv4');
      localStorage.setItem('diskType','nvme'); orderingServerSetPrice(1199);
      $('#plan').val('421'); checkForm(); ">promo-B</button>
  </div>
</body></html>
"""

# Годовой тариф (не помесячный) должен отсеиваться — берём только платёжный цикл Monthly.
ULTAHOST_ANNUAL_ONLY = """
<html><body><div class="package"><div class="package-side package-side-left">
  <div class="package-header"><h3 class="package-title">VPS Basic</h3>
  <div class="price"><div class="price-amount"> $59.00 USD </div><div class="price-cycle "> Annually </div></div></div>
  <div class="package-content"><p><b>1 CPU</b> Core<br /><b>1 GB</b> RAM<br />
  <b>30 GB</b> NVMe SSD<br /><b>Unmetered</b> bandwidth</p></div>
</div></div></body></html>
"""


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
        "trafficKnown": False,
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
        "trafficKnown": False,
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


def test__parse_ultahost_plans__expands_each_tier_across_locations() -> None:
    source = "https://bill.ultahost.com/store/linux-vps-hosting?currency=1"
    plans = parse_ultahost_plans({source: ULTAHOST_STORE})
    by_id = {p["id"]: p for p in plans}
    locations = provider_plans.ultahost._ULTAHOST_LOCATIONS

    # два тарифа развёрнуты по всем локациям, без задваивания из-за package-side-right
    assert len(plans) == 2 * len(locations)

    assert by_id["ulta-frankfurt-germany-vps-basic"] == {
        "id": "ulta-frankfurt-germany-vps-basic",
        "name": "VPS Basic · Frankfurt, Germany",
        "region": "Frankfurt, Germany",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 30,
        "diskType": "NVMe",
        "portMbps": 0,
        "trafficTb": None,  # Unmetered → безлимит
        "price": 5.99,
        "currency": "USD",
        "period": "month",
        "available": True,
        "sourceUrl": source,
    }
    assert by_id["ulta-tokyo-japan-vps-business"]["price"] == 10.5
    assert by_id["ulta-tokyo-japan-vps-business"]["cpu"] == 2
    assert by_id["ulta-tokyo-japan-vps-business"]["diskGb"] == 50
    # каждая локация встречается ровно один раз на тариф
    assert {p["region"] for p in plans} == set(locations)
    assert all(p["currency"] == "USD" and p["period"] == "month" for p in plans)


def test__parse_ultahost_plans__skips_non_monthly_cycle() -> None:
    assert parse_ultahost_plans({"https://bill.ultahost.com/store/linux-vps-hosting": ULTAHOST_ANNUAL_ONLY}) == []


def test__ultahost_price__parses_thousands_separator() -> None:
    price = provider_plans.ultahost._ulta_price
    assert price("$5.99 USD") == 5.99
    assert price("$10.50 USD") == 10.5
    # разделитель тысяч не должен превращаться в десятичную точку
    assert price("$1,299.00 USD") == 1299.0
    assert price("$1,234 USD") == 1234.0
    assert price("no digits here") is None


def test__parse_yun62_plans__extracts_per_location_tariffs_from_onclick() -> None:
    source = "https://62yun.ru/servers/order"
    plans = parse_yun62_plans({source: YUN62_ORDER})
    by_id = {p["id"]: p for p in plans}

    # 4 кнопки тарифов → 4 плана; коды локаций разрезолвлены в названия стран (frm=США, fra=Германия, hk=Гонконг)
    assert len(plans) == 4
    assert by_id["62yun-frm-promo-s"] == {
        "id": "62yun-frm-promo-s",
        "name": "promo-S · США",
        "region": "США",
        "cpu": 1,
        "ramGb": 1,
        "diskGb": 10,
        "diskType": "NVMe",
        "portMbps": 0,
        "trafficTb": None,
        "trafficKnown": False,  # квота не опубликована
        "price": 219.0,
        "currency": "RUB",
        "period": "month",
        "available": True,
        "sourceUrl": source,
    }
    # HDD-тариф читается как HDD, цена месячная в рублях
    assert by_id["62yun-frm-promo-m"]["diskType"] == "HDD"
    assert by_id["62yun-frm-promo-m"]["diskGb"] == 500
    assert by_id["62yun-frm-promo-m"]["price"] == 369.0
    # у каждой локации СВОЙ набор: в США нет ultra-S, в Гонконге только promo-B
    regions_by_tier = {(p["name"].split(" · ")[0], p["region"]) for p in plans}
    assert ("promo-S", "США") in regions_by_tier
    assert ("ultra-S", "США") not in regions_by_tier
    assert ("ultra-S", "Германия") in regions_by_tier
    assert {p["region"] for p in plans if p["name"].startswith("promo-B")} == {"Гонконг"}
    assert all(p["currency"] == "RUB" and p["period"] == "month" for p in plans)


async def test__fetch_yun62_plans__loads_order_page(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        assert timeout > 0
        assert "62yun.ru/servers/order" in url
        return YUN62_ORDER

    monkeypatch.setattr(provider_plans.yun62, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.fetch_yun62_plans()

    assert {p["region"] for p in plans} == {"США", "Германия", "Гонконг"}
    assert all(p["currency"] == "RUB" for p in plans)


async def test__fetch_ultahost_plans__loads_store_page(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        assert timeout > 0
        assert "store/linux-vps-hosting" in url
        return ULTAHOST_STORE

    monkeypatch.setattr(provider_plans.ultahost, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.fetch_ultahost_plans()

    assert {p["name"].split(" · ")[0] for p in plans} == {"VPS Basic", "VPS Business"}
    assert all(p["currency"] == "USD" for p in plans)


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


async def test__plans_for__ultahost_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "ulta-live"}]

    monkeypatch.setattr(provider_plans, "fetch_ultahost_plans", fake_fetch)

    assert await provider_plans.plans_for("UltaHost") == [{"id": "ulta-live"}]
    assert await provider_plans.plans_for("ultahost") == [{"id": "ulta-live"}]


async def test__plans_for__yun62_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "62yun-live"}]

    monkeypatch.setattr(provider_plans, "fetch_yun62_plans", fake_fetch)

    assert await provider_plans.plans_for("62YUN") == [{"id": "62yun-live"}]
    assert await provider_plans.plans_for("62yun") == [{"id": "62yun-live"}]


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


_FRONTEND_PLAN_SOURCES = Path(__file__).resolve().parents[4] / "frontend" / "src" / "lib" / "planSources.ts"


def test__plan_sources__every_source_has_a_fetcher() -> None:
    ids = [src.id for src in provider_plans.PLAN_SOURCES]
    assert len(ids) == len(set(ids))
    named, whmcs, billmanager = (
        set(provider_plans._FETCHER_NAMES),
        set(provider_plans.WHMCS_STORES),
        set(provider_plans.BILLMANAGER_SOURCES),
    )
    assert set(ids) == named | whmcs | billmanager
    assert len(named) + len(whmcs) + len(billmanager) == len(ids)  # движки не пересекаются
    for name in provider_plans._FETCHER_NAMES.values():
        assert callable(getattr(provider_plans, name))


@pytest.mark.parametrize("src", provider_plans.PLAN_SOURCES, ids=lambda s: s.id)
def test__provider_key__resolves_id_label_and_aliases(src: provider_plans.PlanSource) -> None:
    for name in (src.id, src.label, src.label.upper(), *src.aliases):
        assert provider_plans._provider_key(name) == src.id


def test__plan_sources__frontend_mirror_matches_backend_registry() -> None:
    if not _FRONTEND_PLAN_SOURCES.exists():
        pytest.skip("frontend sources are not part of this checkout")
    text = _FRONTEND_PLAN_SOURCES.read_text(encoding="utf-8")
    frontend = dict(re.findall(r'\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)"', text))  # biome переносит длинные строки
    assert frontend == {src.id: src.label for src in provider_plans.PLAN_SOURCES}


# --- Nuxt payload (Timeweb, Beget) --------------------------------------------------------------


def _nuxt_html(state: Any) -> str:
    """Страница с payload `__NUXT_DATA__` в формате devalue (плоский массив индексов), как отдаёт Nuxt 3."""
    values: list[Any] = []

    def add(value: Any) -> int:
        index = len(values)
        values.append(None)
        if isinstance(value, dict):
            values[index] = {k: add(v) for k, v in value.items()}
        elif isinstance(value, list):
            values[index] = [add(v) for v in value]
        else:
            values[index] = value
        return index

    add(state)
    payload = json.dumps(values, ensure_ascii=False)
    return f'<html><script type="application/json" data-ssr="true" id="__NUXT_DATA__">{payload}</script></html>'


def test__parse_nuxt_payload__resolves_devalue_tags_and_shared_refs() -> None:
    from vpnhub.infra.provider_plans.nuxt import parse_nuxt_payload

    values = [
        ["ShallowReactive", 1],
        {"data": 2, "when": 6, "tags": 7, "none": -1, "map": 8},
        ["Reactive", 3],
        [4, 4],  # один и тот же объект дважды (общая ссылка)
        {"name": 5},
        "Cloud-15",
        ["Date", "2026-10-07T00:00:00.000Z"],
        ["Set", 5],
        ["Map", 5, 4],
    ]
    html = f'<script id="__NUXT_DATA__" type="application/json">{json.dumps(values)}</script>'

    state = parse_nuxt_payload(html)

    assert state["data"] == [{"name": "Cloud-15"}, {"name": "Cloud-15"}]
    assert state["data"][0] is state["data"][1]
    assert state["when"] == "2026-10-07T00:00:00.000Z"
    assert state["tags"] == ["Cloud-15"]
    assert state["none"] is None
    assert state["map"] == {"Cloud-15": {"name": "Cloud-15"}}


@pytest.mark.parametrize("html", ["<html></html>", '<script id="__NUXT_DATA__">{broken</script>'])
def test__parse_nuxt_payload__missing_or_broken_payload_is_none(html: str) -> None:
    from vpnhub.infra.provider_plans.nuxt import parse_nuxt_payload

    assert parse_nuxt_payload(html) is None


TIMEWEB_STATE = {
    "data": {
        "vds/fetchTariffs": [
            {
                "id": 2573,
                "name": "SSD-15",
                "cpu": "1 x 2.8 ГГц",
                "memory": "1 ГБ",
                "storage": [{"size": "15 ГБ", "type": "SSD"}],
                "bandwidth": 100,
                "price": 149,
                "tags": ["site", "cp", "ssd_2022"],
            },
            {
                "id": 6767,
                "name": "Cloud NL-30",
                "cpu": "1 x 3.3 ГГц",
                "memory": "2 ГБ",
                "storage": [{"size": "30 ГБ", "type": "NVME"}],
                "bandwidth": 1000,
                "price": 810,
                "tags": ["site", "cp", "nl_base"],
            },
            {
                "id": 7000,
                "name": "Cloud XX",
                "cpu": "1 x 3 ГГц",
                "memory": "1 ГБ",
                "storage": [{"size": "15 ГБ", "type": "NVME"}],
                "bandwidth": 100,
                "price": 300,
                "tags": ["site", "cp", "unknown_tag"],  # локация не сопоставлена — тариф пропускаем
            },
        ],
        "configurator/servers": [
            {"location": "ru-1", "tags": ["ssd_2022"], "requirements": {}},
            {"location": "nl-1", "tags": ["nl_base"], "requirements": {}},
        ],
    }
}


def test__parse_timeweb_plans__maps_tariff_tags_to_locations_via_configurator() -> None:
    plans = provider_plans.parse_timeweb_plans({"https://timeweb.cloud/services/vds-vps": _nuxt_html(TIMEWEB_STATE)})

    assert [(p["id"], p["region"]) for p in plans] == [
        ("timeweb-6767", "Амстердам, Нидерланды"),
        ("timeweb-2573", "Санкт-Петербург, Россия"),
    ]
    nl = plans[0]
    assert nl["name"] == "Cloud NL-30 · Амстердам"
    assert (nl["cpu"], nl["ramGb"], nl["diskGb"], nl["diskType"], nl["portMbps"]) == (1, 2, 30, "NVMe", 1000)
    assert (nl["price"], nl["currency"], nl["period"], nl["trafficTb"]) == (810.0, "RUB", "month", None)
    assert "trafficKnown" not in nl  # у Timeweb трафик явно безлимитный


BEGET_STATE = {
    "pinia": {
        "services": {
            "planList": {
                "hostingPlans": [{"name": "blog", "specs": {"disk_size": 1}, "prices": {}, "type": "X"}],
                "vpsPlans": [
                    {
                        "name": "ru1_prime_v5",
                        "display_name": "Prime",
                        "specs": {"disk_size": 30720, "memory_size": 2048, "cpu_cores": 2, "bandwidth_public": 1000},
                        "prices": {"no_discount": {"month_amount": 810, "day_amount": 27}},
                        "region": "ru1",
                    },
                    {
                        "name": "kz1_prime_v5",
                        "display_name": "Prime",
                        "specs": {"disk_size": 30720, "memory_size": 2048, "cpu_cores": 2, "bandwidth_public": 150},
                        "prices": {"no_discount": {"month_amount": 900}},
                        "region": "kz1",
                    },
                ],
            }
        }
    }
}


def test__parse_beget_plans__extracts_vps_plans_from_pinia_state() -> None:
    plans = provider_plans.parse_beget_plans({"https://beget.com/ru/vps": _nuxt_html(BEGET_STATE)})

    assert [(p["id"], p["region"], p["price"]) for p in plans] == [
        ("beget-kz1_prime_v5", "Казахстан", 900.0),
        ("beget-ru1_prime_v5", "Санкт-Петербург, Россия", 810.0),
    ]
    spb = plans[1]
    assert (spb["cpu"], spb["ramGb"], spb["diskGb"], spb["diskType"], spb["portMbps"]) == (2, 2, 30, "NVMe", 1000)
    assert (spb["trafficTb"], spb["trafficKnown"]) == (None, False)  # квота не опубликована — не «безлимит»


@pytest.mark.parametrize(
    ("provider", "module", "fetch_name"),
    [("timeweb", "timeweb", "fetch_timeweb_plans"), ("beget", "beget", "fetch_beget_plans")],
)
async def test__fetch_nuxt_providers__parse_the_downloaded_page(
    monkeypatch: pytest.MonkeyPatch, provider: str, module: str, fetch_name: str
) -> None:
    state = TIMEWEB_STATE if provider == "timeweb" else BEGET_STATE
    calls: list[str] = []

    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        calls.append(url)
        return _nuxt_html(state)

    monkeypatch.setattr(getattr(provider_plans, module), "_fetch_browser_url", fake_fetch_browser_url)

    plans = await getattr(provider_plans, fetch_name)()

    assert len(calls) == 1
    assert len(plans) == 2


async def test__fetch_timeweb_plans__network_error_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(url: str, timeout: float) -> str:
        raise TimeoutError

    monkeypatch.setattr(provider_plans.timeweb, "_fetch_browser_url", boom)

    assert await provider_plans.fetch_timeweb_plans() == []


# --- публичные API облаков (Vultr, Linode) ------------------------------------------------------

VULTR_REGIONS = {
    "regions": [
        {"id": "ams", "city": "Amsterdam", "country": "NL"},
        {"id": "sao", "city": "São Paulo", "country": "BR"},
    ]
}
VULTR_PLANS = {
    "plans": [
        {"id": "vc2-1c-0.5gb-free", "type": "vc2", "vcpu_count": 1, "ram": 512, "disk": 10, "bandwidth": 0,
         "monthly_cost": 0, "locations": ["ams"]},
        {"id": "vc2-1c-0.5gb-v6", "type": "vc2", "vcpu_count": 1, "ram": 512, "disk": 10, "bandwidth": 512,
         "monthly_cost": 2.5, "locations": ["ams"]},
        {"id": "vc2-1c-1gb", "type": "vc2", "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 1024,
         "monthly_cost": 5, "locations": ["ams", "sao", "unknown"],
         "location_cost": {"sao": {"monthly_cost": 7.5}}},
        {"id": "vhp-1c-1gb-amd", "type": "vhp", "vcpu_count": 1, "ram": 1024, "disk": 25, "bandwidth": 2048,
         "monthly_cost": 6, "locations": ["ams"]},
        {"id": "vcg-a16-2c-8g-2vram", "type": "vcg", "vcpu_count": 2, "ram": 8192, "disk": 50, "bandwidth": 1024,
         "monthly_cost": 43, "locations": ["ams"]},
    ]
}  # fmt: skip


def test__parse_vultr_plans__expands_vps_plans_by_location_with_location_prices() -> None:
    plans = provider_plans.parse_vultr_plans(VULTR_PLANS, VULTR_REGIONS)

    assert [(p["id"], p["price"], p["country"]) for p in plans] == [
        ("vultr-ams-vc2-1c-1gb", 5.0, "NL"),
        ("vultr-ams-vhp-1c-1gb-amd", 6.0, "NL"),
        ("vultr-sao-vc2-1c-1gb", 7.5, "BR"),  # поправка цены для Сан-Паулу
    ]
    amd = plans[1]
    assert amd["name"] == "High Performance AMD 1C/1GB · Amsterdam"
    assert (amd["region"], amd["diskType"], amd["trafficTb"], amd["currency"]) == ("Amsterdam, NL", "NVMe", 2.0, "USD")


LINODE_REGIONS = {
    "data": [
        {
            "id": "nl-ams",
            "label": "Amsterdam, NL",
            "country": "nl",
            "site_type": "core",
            "status": "ok",
            "capabilities": ["Linodes", "Block Storage"],
        },
        {
            "id": "br-gru",
            "label": "Sao Paulo, BR",
            "country": "br",
            "site_type": "core",
            "status": "ok",
            "capabilities": ["Linodes"],
        },
        {
            "id": "us-edge",
            "label": "Edge, US",
            "country": "us",
            "site_type": "distributed",
            "status": "ok",
            "capabilities": ["Linodes"],
        },
        {
            "id": "xx-obj",
            "label": "Storage only",
            "country": "us",
            "site_type": "core",
            "status": "ok",
            "capabilities": ["Object Storage"],
        },
    ]
}
LINODE_TYPES = {
    "data": [
        {"id": "g6-nanode-1", "label": "Nanode 1GB", "class": "nanode", "vcpus": 1, "memory": 1024, "disk": 25600,
         "transfer": 1000, "network_out": 1000, "price": {"monthly": 5.0},
         "region_prices": [{"id": "br-gru", "monthly": 7.0}]},
        {"id": "g1-gpu-rtx6000-1", "label": "GPU", "class": "gpu", "vcpus": 8, "memory": 32768, "disk": 655360,
         "transfer": 16000, "network_out": 10000, "price": {"monthly": 1000.0}, "region_prices": []},
        {"id": "g8-dedicated-4-2", "label": "G8 Dedicated 4x2", "class": "dedicated", "vcpus": 2, "memory": 4096,
         "disk": 41984, "transfer": 0, "network_out": 4000, "price": {"monthly": None}, "region_prices": []},
    ]
}  # fmt: skip


def test__parse_linode_plans__expands_types_over_core_linode_regions() -> None:
    plans = provider_plans.parse_linode_plans(LINODE_TYPES, LINODE_REGIONS)

    assert [(p["id"], p["price"], p["country"]) for p in plans] == [
        ("linode-nl-ams-g6-nanode-1", 5.0, "NL"),
        ("linode-br-gru-g6-nanode-1", 7.0, "BR"),  # региональная цена
    ]
    nl = plans[0]
    assert (nl["name"], nl["cpu"], nl["ramGb"], nl["diskGb"], nl["portMbps"], nl["trafficTb"]) == (
        "Nanode 1GB · Amsterdam",
        1,
        1,
        25,
        1000,
        1.0,
    )


async def test__fetch_vultr_plans__follows_cursor_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        "https://api.vultr.com/v2/plans?per_page=500": {
            "plans": VULTR_PLANS["plans"][:3],
            "meta": {"links": {"next": "abc"}},
        },
        "https://api.vultr.com/v2/plans?per_page=500&cursor=abc": {
            "plans": VULTR_PLANS["plans"][3:],
            "meta": {"links": {"next": ""}},
        },
        "https://api.vultr.com/v2/regions?per_page=500": VULTR_REGIONS,
    }

    async def fake_fetch_json(url: str, timeout: float) -> Any:
        return pages[url]

    monkeypatch.setattr(provider_plans.vultr, "_fetch_json", fake_fetch_json)

    plans = await provider_plans.fetch_vultr_plans()

    assert len(plans) == 3


async def test__fetch_linode_plans__api_error_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(url: str, timeout: float) -> Any:
        raise OSError("down")

    monkeypatch.setattr(provider_plans.linode, "_fetch_json", boom)

    assert await provider_plans.fetch_linode_plans() == []


# --- Hetzner (HTML линеек + фид цен) ------------------------------------------------------------

HETZNER_ROW = """
<div class="cloud-matrix-product {extra}" style="order: 1;">
  <div class="cell name-cell"><div class="no-wrap ">{name}</div></div>
  <div class="cell cpu-cell"><svg><path d="M1"/></svg> {cpu} <div class="arch-type-badge">AMD</div></div>
  <div class="cell ram-cell"><svg></svg> {ram} GB</div>
  <div class="cell drive-cell"><svg></svg> {disk} GB <span class="product-cloud-drive-label">NVMe</span></div>
  <div class="cell month-price-cell">
    <ho-price-container country="fi,de" product-key="{key}" ></ho-price-container>
  </div>
  <div class="product-details-container">
    <div class="location-box text-caption-2 box-1">
      <span class="location-label">eu-central</span>
      <span class="traffic-info-amount">20
          TB</span>
      <ho-price-container class="text-price" product-key="CLOUD_66" price-type="hourly" location=ALL>
      </ho-price-container>
      <ho-price-container location="NBG1,HEL1" product-key="{key}" ></ho-price-container>
    </div>
    <div class="location-box text-caption-2 box-2">
      <span class="traffic-info-amount">1 TB</span>
      <ho-price-container location="SIN1" product-key="{key}" ></ho-price-container>
    </div>
  </div>
</div>
"""
HETZNER_PAGE = (
    "<html>"
    + HETZNER_ROW.format(extra="", name="CPX22", cpu=2, ram=4, disk=80, key="CLOUD_124+CLOUD_21")
    + HETZNER_ROW.format(extra="not-available", name="CX23", cpu=2, ram=4, disk=40, key="CLOUD_132+CLOUD_21")
    + '<div class="cloud-matrix-product-fold"></div></html>'
)
HETZNER_PRICES = {
    "products": {
        "CLOUD_124": {
            "locations": [
                {"countryCode": "de", "datacenter": "NBG1", "active": True, "prices": {"monthly": {"EUR": "19.49"}}},
                {"countryCode": "fi", "datacenter": "HEL1", "active": True, "prices": {"monthly": {"EUR": "19.49"}}},
                {"countryCode": "sg", "datacenter": "SIN1", "active": True, "prices": {"monthly": {"EUR": "26.49"}}},
            ]
        },
        "CLOUD_132": {
            "locations": [
                {"countryCode": "de", "datacenter": "NBG1", "active": True, "prices": {"monthly": {"EUR": "5.49"}}},
            ]
        },
        "CLOUD_21": {"locations": [{"datacenter": "ALL", "prices": {"monthly": {"EUR": "0.50"}}}]},
    }
}


def test__parse_hetzner_plans__joins_html_specs_with_per_dc_prices_and_ipv4() -> None:
    url = "https://www.hetzner.com/cloud/regular-performance/"
    plans = provider_plans.parse_hetzner_plans({url: HETZNER_PAGE}, HETZNER_PRICES)

    assert [(p["id"], p["price"], p["trafficTb"], p["available"]) for p in plans] == [
        ("hetzner-hel1-cpx22", 19.99, 20.0, True),
        ("hetzner-nbg1-cx23", 5.99, 20.0, False),  # «not available» на сайте; в HEL1/SIN1 цены нет — пропуск
        ("hetzner-nbg1-cpx22", 19.99, 20.0, True),
        ("hetzner-sin1-cpx22", 26.99, 1.0, True),
    ]
    hel = plans[0]
    assert (hel["name"], hel["region"], hel["country"], hel["currency"]) == (
        "CPX22 · Helsinki",
        "Helsinki, FI",
        "FI",
        "EUR",
    )
    assert (hel["cpu"], hel["ramGb"], hel["diskGb"], hel["diskType"]) == (2, 4, 80, "NVMe")


async def test__fetch_hetzner_plans__loads_prices_and_every_line(monkeypatch: pytest.MonkeyPatch) -> None:
    pages: list[str] = []

    async def fake_fetch_json(url: str, timeout: float) -> Any:
        return HETZNER_PRICES

    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        pages.append(url)
        if url.endswith("general-purpose/"):
            raise TimeoutError  # одна линейка недоступна — остальные всё равно разбираются
        return HETZNER_PAGE if url.endswith("cost-optimized/") else "<html></html>"

    monkeypatch.setattr(provider_plans.hetzner, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(provider_plans.hetzner, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.fetch_hetzner_plans()

    assert len(pages) == 3
    assert len(plans) == 4
    assert {p["sourceUrl"] for p in plans} == {"https://www.hetzner.com/cloud/cost-optimized/"}


# --- общий парсер WHMCS ---------------------------------------------------------------------------

WHMCS_PAGE = """
<html><body>
<div class="product clearfix" id="product1">
  <header><span id="product1-name">KVM SMART</span><span class="qty">1608 Available</span></header>
  <div class="product-desc"><ul>
    <li>1 GB RAM</li><li>1 vCPU</li><li>15 GB SSD</li>
    <li><span>Traffic:</span></li><li><span>1 TB</span></li>
    <li>1 Gbps port</li>
  </ul></div>
  <footer><div class="product-pricing" id="product1-price">Starting from <span class="price">EUR 4.99</span>
    <br/>Monthly</div></footer>
</div>
<div class="product clearfix" id="product2">
  <header><span id="product2-name">512MB VPS [CL]</span><span class="qty">0 Available</span></header>
  <div class="product-desc">
    <div>1 Core</div><div>CPU</div><div>512MB</div><div>RAM</div><div>30GB</div><div>SSD</div>
    <div>200GB @ 100Mbps</div><div>Bandwidth</div>
  </div>
  <footer><div class="product-pricing" id="product2-price">
    <span class="price">$65.00 USD</span><br/>Annually</div></footer>
</div>
<div class="product clearfix" id="product3">
  <header><span id="product3-name">Қайнар</span></header>
  <div class="product-desc"><p id="product3-description"><ul>
    <li><strong>15 ГБ</strong> дискового пространства</li><li><strong>1</strong> ядро vCPU</li>
    <li><strong>2 ГБ</strong> оперативной памяти (RAM)</li><li>Трафик безлимитный</li>
  </ul></p></div>
  <footer><div class="product-pricing" id="product3-price">
    Начиная от <span class="price">2 383.00₸</span><br/>ежемесячно</div></footer>
</div>
<div class="product clearfix" id="product4">
  <header><span id="product4-name">Licence</span></header>
  <div class="product-desc"><ul><li>Software licence</li></ul></div>
  <footer><div class="product-pricing" id="product4-price">$10.00 USD One Time</div></footer>
</div>
</body></html>
"""


def test__parse_whmcs_page__reads_standard_cart_products_in_any_layout() -> None:
    page = provider_plans.WhmcsPage("https://example.com/cart.php?gid=1", "Vienna, Austria", "AT")

    plans = {p["name"]: p for p in provider_plans.parse_whmcs_page("edis", page, WHMCS_PAGE)}

    assert set(plans) == {"KVM SMART · Vienna", "512MB VPS [CL] (yearly) · Vienna", "Қайнар · Vienna"}  # без лицензии
    smart = plans["KVM SMART · Vienna"]
    assert (smart["cpu"], smart["ramGb"], smart["diskGb"], smart["diskType"]) == (1, 1, 15, "SSD")
    assert (smart["trafficTb"], smart["portMbps"], smart["price"], smart["currency"]) == (1, 1000, 4.99, "EUR")
    assert (smart["region"], smart["country"], smart["available"]) == ("Vienna, Austria", "AT", True)
    assert smart["id"] == "edis-vienna-austria-kvm-smart"
    # значения и подписи разнесены по строкам, цена за год приведена к месяцу
    split = plans["512MB VPS [CL] (yearly) · Vienna"]
    assert (split["cpu"], split["ramGb"], split["diskGb"], split["portMbps"]) == (1, 0.5, 30, 100)
    assert (split["price"], split["currency"], split["available"]) == (5.42, "USD", False)
    kz = plans["Қайнар · Vienna"]
    assert (kz["cpu"], kz["ramGb"], kz["diskGb"], kz["trafficTb"], kz["price"]) == (1, 2, 15, None, 2383.0)
    assert kz["currency"] == "KZT"
    assert "trafficKnown" not in kz  # «Трафик безлимитный» — квота известна
    assert "trafficKnown" not in smart


@pytest.mark.parametrize(
    ("text", "default", "expected"),
    [
        ("Starting from $1,299.00 USD Monthly", "", (1299.0, "USD", 1, "")),
        ("Desde $6,000CLP Mensualmente", "", (6000.0, "CLP", 1, "")),
        ("Desde $79.900 Mensualmente", "CLP", (79900.0, "CLP", 1, "")),
        ("R$ 49,90 mensal", "", (49.9, "BRL", 1, "")),
        ("€7.99EUR Quarterly €5.00 Setup Fee", "", (2.66, "EUR", 3, "quarterly")),
        ("$10.00 USD One Time", "", None),
        ("Free", "", None),
    ],
)
def test__whmcs_parse_price__currencies_separators_and_cycles(
    text: str, default: str, expected: tuple[float, str, int, str] | None
) -> None:
    from vpnhub.infra.provider_plans.whmcs import _parse_price

    assert _parse_price(text, default) == expected


async def test__fetch_whmcs_plans__skips_unreachable_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = (
        provider_plans.WhmcsPage("https://a.example/store/vps", "Vienna, Austria", "AT"),
        provider_plans.WhmcsPage("https://a.example/store/down", "Oslo, Norway", "NO"),
    )

    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        if url.endswith("down"):
            raise TimeoutError
        return WHMCS_PAGE

    monkeypatch.setattr(provider_plans.whmcs, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.fetch_whmcs_plans("edis", pages)

    assert {p["region"] for p in plans} == {"Vienna, Austria"}
    assert len(plans) == 3


async def test__plans_for__routes_whmcs_providers_to_their_store_config(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def fake_fetch_browser_url(url: str, timeout: float) -> str:
        seen.append(url)
        return WHMCS_PAGE

    monkeypatch.setattr(provider_plans.whmcs, "_fetch_browser_url", fake_fetch_browser_url)

    plans = await provider_plans.plans_for("FlokiNET")

    assert seen == [p.url for p in provider_plans.WHMCS_STORES["flokinet"]]
    assert plans and all(p["id"].startswith("flokinet-") for p in plans)


# --- Cherry Servers (публичный API) -------------------------------------------------------------

CHERRY_PLANS = [
    {
        "slug": "e3-1240v3",
        "name": "E3-1240v3",
        "type": "baremetal",
        "specs": {},
        "pricing": [],
        "available_regions": [],
    },
    {
        "slug": "B2-1-1gb-20s-shared",
        "name": "Cloud VPS 1 (Gen 2)",
        "type": "vps",
        "specs": {
            "cpus": {"cores": 1},
            "memory": {"total": 1},
            "storage": [{"count": 1, "size": 20, "type": "SSD"}],
            "nics": {"name": "1Gbps"},
            "bandwidth": {"name": "1TB"},
        },
        "pricing": [
            {"unit": "Hourly", "price": 0.015, "currency": "EUR"},
            {"unit": "Monthly", "price": 3.0, "currency": "EUR"},
        ],
        "available_regions": [
            {"region_iso_2": "LT", "location": "Lithuania, Šiauliai", "stock_qty": 113},
            {"region_iso_2": "SG", "location": "Singapore", "stock_qty": 0},
        ],
    },
]


def test__parse_cherry_plans__expands_vps_by_region_with_stock() -> None:
    plans = provider_plans.parse_cherry_plans(CHERRY_PLANS)

    assert [(p["id"], p["region"], p["available"]) for p in plans] == [
        ("cherry-sg-b2-1-1gb-20s-shared", "Singapore", False),
        ("cherry-lt-b2-1-1gb-20s-shared", "Šiauliai, Lithuania", True),
    ]
    lt = plans[1]
    assert (lt["cpu"], lt["ramGb"], lt["diskGb"], lt["diskType"], lt["portMbps"], lt["trafficTb"]) == (
        1,
        1,
        20,
        "SSD",
        1000,
        1,
    )
    assert (lt["price"], lt["currency"], lt["country"]) == (3.0, "EUR", "LT")


# --- общий парсер BILLmanager -------------------------------------------------------------------


def _bm_addon(intname: str, limit: str, unit: str = "", name: str = "") -> str:
    measure = f"<measure>6</measure><measure><id>6</id><name>{unit}</name></measure>" if unit else ""
    return (
        f"<addon><name>{name}</name><addonlimit>{limit}</addonlimit>{measure}"
        f"<addon_itemtype_info><intname>{intname}</intname></addon_itemtype_info></addon>"
    )


def _bm_pricelist(pid: int, name: str, cost: str, addons: str, dcs: str = "", **flags: str) -> str:
    extra = "".join(f"<{k}>{v}</{k}>" for k, v in flags.items())
    return (
        f"<pricelist><id>{pid}</id><name>{name}</name><active>on</active>{extra}"
        f"<itemtype_info><intname>vds</intname></itemtype_info>{dcs}"
        f'<price currency="RUB"><period cost="0.0000" type="month" length="-100">trial</period>'
        f'<period cost="{cost}" type="month" length="1">monthly</period></price>{addons}</pricelist>'
    )


BM_EXPORT = (
    "<doc>"
    + _bm_pricelist(
        1400,
        "Взлёт",
        "490.0000",
        _bm_addon("ncpu", "2", "Unit")
        + _bm_addon("mem", "2048", "Mb")
        + _bm_addon("disc", "40", "Gb", "Дисковое пространство NVMe")
        + _bm_addon("inbound", "905", "Mbps")
        + _bm_addon("outbound", "100", "Mbps"),
        "<datacenter><id>4</id><name>Moscow</name><name_ru>Москва, Россия</name_ru></datacenter>"
        "<datacenter><id>7</id><name>Host-Telecom (CZ)</name></datacenter>",
    )
    + _bm_pricelist(
        1500,
        "VDS-KVM-SSD 4.0",
        "949.0000",
        _bm_addon("ncpu", "2")
        + _bm_addon("mem", "2")
        + _bm_addon("disc", "20")
        + _bm_addon("bandwidth", "32", "Tb", "Port 1 Gbit/s, 32 Tb included"),
    )
    + _bm_pricelist(1600, "Конфигуратор", "0.0000", _bm_addon("ncpu", "1") + _bm_addon("mem", "1024", "Mb"))
    + _bm_pricelist(1700, "Скрытый", "100.0000", _bm_addon("ncpu", "1"), hideinorder="on")
    + _bm_pricelist(
        1800,
        "KVM-HB-20",
        "400.0000",
        _bm_addon("ip", "1"),
        description_ru=(
            "&lt;ul&gt;&lt;li&gt;1 vCPU&lt;/li&gt;&lt;li&gt;2 GB RAM&lt;/li&gt;"
            "&lt;li&gt;20 GB HDD&lt;/li&gt;&lt;/ul&gt;"
        ),
    )
    + "</doc>"
)


def test__parse_billmanager_export__reads_addons_datacenters_and_description_fallback() -> None:
    source = provider_plans.BillmanagerSource(
        "https://my.example.ru/billmgr", "https://example.ru/vps", default_region="Россия", country="RU"
    )

    plans = {p["id"]: p for p in provider_plans.parse_billmanager_export("vds-sh", source, BM_EXPORT)}

    assert set(plans) == {"vds-sh-1400-4", "vds-sh-1400-7", "vds-sh-1500", "vds-sh-1800"}  # без конструктора и скрытого
    msk = plans["vds-sh-1400-4"]
    assert (msk["name"], msk["region"], msk["country"]) == ("Взлёт · Москва, Россия", "Москва, Россия", "RU")
    assert (msk["cpu"], msk["ramGb"], msk["diskGb"], msk["diskType"], msk["portMbps"]) == (2, 2, 40, "NVMe", 100)
    assert (msk["price"], msk["currency"], msk["sourceUrl"]) == (490.0, "RUB", "https://example.ru/vps")
    assert plans["vds-sh-1400-7"]["country"] == "CZ"  # код страны в скобках у имени ДЦ
    ssd = plans["vds-sh-1500"]  # без ДЦ — регион по умолчанию; единицы не указаны — RAM в ГБ
    assert (ssd["region"], ssd["ramGb"], ssd["diskType"], ssd["portMbps"], ssd["trafficTb"]) == (
        "Россия",
        2,
        "SSD",
        1000,
        32.0,
    )
    described = plans["vds-sh-1800"]  # характеристики только в описании
    assert (described["cpu"], described["ramGb"], described["diskGb"], described["diskType"]) == (1, 2, 20, "HDD")
    assert msk["trafficKnown"] is False  # ни квоты, ни «безлимита» в прайсе
    assert "trafficKnown" not in ssd  # 32 ТБ указаны


def test__billmanager_export_url__asks_for_available_vds_only() -> None:
    from vpnhub.infra.provider_plans.billmanager import export_url

    url = export_url(provider_plans.BillmanagerSource("https://my.example.ru/billmgr", "https://example.ru"))

    assert url == ("https://my.example.ru/billmgr?func=pricelist.export&out=xml&itemtype=vds&onlyavailable=on")


async def test__fetch_billmanager_plans__downloads_and_handles_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_open_export(url: str, timeout: float) -> io.BytesIO:
        calls.append(url)
        if "down" in url:
            raise TimeoutError
        return io.BytesIO(BM_EXPORT.encode())

    monkeypatch.setattr(provider_plans.billmanager, "_open_export", fake_open_export)
    ok = provider_plans.BillmanagerSource("https://up.example/billmgr", "https://up.example", default_region="Россия")
    down = provider_plans.BillmanagerSource("https://down.example/billmgr", "https://down.example")

    assert len(await provider_plans.fetch_billmanager_plans("x", ok)) == 4
    assert await provider_plans.fetch_billmanager_plans("x", down) == []
    assert len(calls) == 2


def test__parse_billmanager_export__broken_xml_is_empty() -> None:
    source = provider_plans.BillmanagerSource("https://my.example.ru/billmgr", "https://example.ru")

    assert provider_plans.parse_billmanager_export("x", source, "<doc><pricelist>") == []


def test__parse_billmanager_export__rejects_documents_with_dtd() -> None:
    source = provider_plans.BillmanagerSource("https://my.example.ru/billmgr", "https://example.ru")
    bomb = '<?xml version="1.0"?><!DOCTYPE doc [<!ENTITY a "aaaa">]>' + BM_EXPORT

    assert provider_plans.parse_billmanager_export("x", source, bomb) == []


# --- 4VPS (публичный POST getTariffs) -----------------------------------------------------------

FOURVPS_HOME = """
<div class="grid__block selectCountry" data-country="Нидерланды" data-panel-id="1" data-cluster="5">NL</div>
<div class="grid__block selectCountry" data-country="Германия" data-panel-id="1" data-cluster="8">DE</div>
<div class="grid__block selectCountry" data-country="Нидерланды" data-panel-id="1" data-cluster="5">дубль</div>
"""
FOURVPS_TARIFFS = {
    "error": False,
    "data": [
        {"id": 13, "name": "NL-cx01", "cpu_number": 1, "ram_mib": 1, "rom": 10, "eth": "2Gbit/s", "price": 472,
         "sold_out": False},
        {"id": 14, "name": "NL-cx11", "cpu_number": 1, "ram_mib": 2048, "rom": 20, "eth": "1Gbit/s", "price": 616,
         "sold_out": True},
    ],
}  # fmt: skip


def test__discover_fourvps_clusters__reads_country_buttons_once() -> None:
    clusters = provider_plans.discover_fourvps_clusters(FOURVPS_HOME)

    assert [(c.country, c.panel_id, c.cluster) for c in clusters] == [("Нидерланды", "1", "5"), ("Германия", "1", "8")]


async def test__fetch_fourvps_plans__posts_month_period_per_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    forms: list[dict[str, str]] = []

    async def fake_home(url: str, timeout: float) -> str:
        return FOURVPS_HOME

    async def fake_post(url: str, form: dict[str, str], timeout: float) -> str:
        forms.append(dict(form))
        return json.dumps(FOURVPS_TARIFFS)

    monkeypatch.setattr(provider_plans.fourvps, "_fetch_browser_url", fake_home)
    monkeypatch.setattr(provider_plans.fourvps, "_post_form_url", fake_post)

    plans = await provider_plans.fetch_fourvps_plans()

    assert sorted(f["cluster"] for f in forms) == ["5", "8"]
    assert all(f["period"] == "720" and f["panelId"] == "1" for f in forms)
    nl = {p["id"]: p for p in plans if p["region"] == "Нидерланды"}
    cheap, sold = nl["4vps-5-nl-cx01"], nl["4vps-5-nl-cx11"]
    assert (cheap["cpu"], cheap["ramGb"], cheap["diskGb"], cheap["portMbps"], cheap["price"]) == (1, 1, 10, 2000, 472.0)
    assert (cheap["currency"], cheap["available"]) == ("RUB", True)
    assert (sold["ramGb"], sold["available"]) == (2, False)  # МиБ → ГБ, распродан


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["1x2.1Ghz - 3.9Ghz CPU", "1GB RAM", "20GB SSD Storage", "3TB @ 1Gbps Monthly Traffic"], (1, 1, 20, 3, 1000)),
        (
            ["CPU: 1vCPU", "Memória: 2GB", "Armazenamento: 50GB SSD", "Tráfego Mensal: Ilimitado"],
            (1, 2, 50, None, None),
        ),
        (["2 vCPU Cores", "4 GB ECC DDR4", "40 GB NVMe"], (2, 4, 40, None, None)),
        (["Geekbench Score 500+", "½ vCPU Core (3.4GHz+ Ryzen)", "384MB Memory"], (None, 0.38, None, None, None)),
    ],
)
def test__whmcs_parse_specs__multilingual_and_odd_layouts(
    lines: list[str], expected: tuple[int | None, float | None, float | None, float | None, int | None]
) -> None:
    from vpnhub.infra.provider_plans.whmcs import _parse_specs

    specs = _parse_specs(lines)

    assert (specs.cpu, specs.ram_gb, specs.disk_gb, specs.traffic_tb, specs.port_mbps) == expected


def test__parse_billmanager_export__streams_large_documents_without_dtd_check_false_positives() -> None:
    """Тарифы за пределами первых 64 КБ тоже читаются; «<!ENTITY» в тексте описания — не DTD."""
    source = provider_plans.BillmanagerSource(
        "https://my.example.ru/billmgr", "https://example.ru", default_region="Россия", country="RU"
    )
    filler = "".join(_bm_pricelist(i, f"Скрытый {i}", "1.0000", "", hideinorder="on") for i in range(1, 400))
    doc = BM_EXPORT.replace("<doc>", "<doc>" + filler).replace("Взлёт", "Взлёт &lt;!ENTITY&gt;")

    plans = provider_plans.parse_billmanager_export("x", source, doc)

    assert len(doc.encode()) > 65_536
    assert len(plans) == 4
