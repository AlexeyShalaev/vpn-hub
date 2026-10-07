"""Провайдеры на WHMCS: какие витрины (группы товаров) читать и где они расположены.

Разбор разметки общий (`..whmcs`), здесь — только данные. Локация группы задаётся явно: заголовки групп
у хостеров нестабильны («KVM Australia», «KVM VPS in the City of London»), а URL витрины — нет.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..whmcs import WhmcsPage

_EDIS = "https://manage.edisglobal.com/cart.php?language=english&gid="
_FLOKINET = "https://billing.flokinet.is/index.php?rp=/store/virtual-private-server-"
_ZAPPIE = "https://billing.zappiehost.com/index.php?rp=/store/"

WHMCS_STORES: Mapping[str, tuple[WhmcsPage, ...]] = {
    # EDIS Global (Австрия): KVM в 17 городах, в т.ч. Москва и Дубай
    "edis-global": tuple(
        WhmcsPage(f"{_EDIS}{gid}", region, country, disk_type="SSD")
        for gid, region, country in (
            (192, "Vienna, Austria", "AT"),
            (107, "Graz, Austria", "AT"),
            (100, "Sydney, Australia", "AU"),
            (102, "Brussels, Belgium", "BE"),
            (122, "Frankfurt, Germany", "DE"),
            (127, "London, United Kingdom", "GB"),
            (132, "Stockholm, Sweden", "SE"),
            (137, "Paris, France", "FR"),
            (142, "Warsaw, Poland", "PL"),
            (147, "Seville, Spain", "ES"),
            (152, "Milan, Italy", "IT"),
            (157, "Amsterdam, Netherlands", "NL"),
            (162, "Bucharest, Romania", "RO"),
            (167, "Copenhagen, Denmark", "DK"),
            (172, "Oslo, Norway", "NO"),
            (177, "Dubai, UAE", "AE"),
            (182, "Moscow, Russia", "RU"),
        )
    ),
    # FlokiNET: приватность, приём крипты; VPS в Румынии, Исландии, Финляндии и Нидерландах
    "flokinet": (
        WhmcsPage(f"{_FLOKINET}romania", "Bucharest, Romania", "RO", currency="EUR"),
        WhmcsPage(f"{_FLOKINET}iceland", "Reykjavik, Iceland", "IS", currency="EUR"),
        WhmcsPage(f"{_FLOKINET}finland", "Finland", "FI", currency="EUR"),
        WhmcsPage(f"{_FLOKINET}netherlands", "Netherlands", "NL", currency="EUR"),
    ),
    # Zappie Host: Чили, Новая Зеландия, ЮАР
    "zappie-host": (
        WhmcsPage(f"{_ZAPPIE}chile-budget-lxc-servers", "Santiago, Chile", "CL"),
        WhmcsPage(f"{_ZAPPIE}chile-premium-kvm-servers", "Santiago, Chile", "CL"),
        WhmcsPage(f"{_ZAPPIE}new-zealand-vps", "Auckland, New Zealand", "NZ"),
        WhmcsPage(f"{_ZAPPIE}new-zealand-kvm-servers", "Auckland, New Zealand", "NZ"),
        WhmcsPage(f"{_ZAPPIE}south-africa-vps", "Johannesburg, South Africa", "ZA"),
        WhmcsPage(f"{_ZAPPIE}south-africa-premium-kvm-servers", "Johannesburg, South Africa", "ZA"),
    ),
    # iDHost (Казахтелеком): VPS в Казахстане, цены в тенге
    "idhost-kazakhtelecom": (
        WhmcsPage("https://idhost.telecom.kz/index.php?rp=/store/linux-vps", "Kazakhstan", "KZ", currency="KZT"),
    ),
    # Hosteroid: VPS в Великобритании
    "hosteroid": (WhmcsPage("https://hosteroid.uk/store/vps", "London, United Kingdom", "GB", currency="EUR"),),
}
