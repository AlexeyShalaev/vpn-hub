"""Динамический каталог тарифных планов провайдеров."""

from __future__ import annotations

from typing import Any

import pytest

from vpnhub.infra import provider_plans
from vpnhub.infra.provider_plans import TIB, discover_firstbyte_plan_urls, parse_firstbyte_plans, plan_bandwidth_bytes

pytestmark = pytest.mark.unit


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


async def test__plans_for__firstbyte_fetches_dynamic_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch() -> list[dict[str, Any]]:
        return [{"id": "fb-live"}]

    monkeypatch.setattr(provider_plans, "fetch_firstbyte_plans", fake_fetch)

    assert await provider_plans.plans_for("FirstByte") == [{"id": "fb-live"}]


async def test__plans_for__unknown_empty() -> None:
    assert await provider_plans.plans_for("nonexistent") == []
    assert await provider_plans.plans_for("") == []


def test__plan_bandwidth_bytes() -> None:
    assert plan_bandwidth_bytes({"trafficTb": 5}) == 5 * TIB
    assert plan_bandwidth_bytes({"trafficTb": None}) is None  # безлимит
    assert plan_bandwidth_bytes({}) is None
