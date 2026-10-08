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
_VIRTONO = "https://www.virtono.com/index.php?rp=/store/"
_GREENCLOUD = "https://greencloudvps.com/billing/store/"
_ADMINVPS = "https://my.adminvps.ru/store/"

# GreenCloud: город — только в описании товара («Staten Island, NY Location»), группы смешивают локации
_GREENCLOUD_REGIONS: Mapping[str, tuple[str, str]] = {
    "Staten Island": ("New York, USA", "US"),
    "Buffalo": ("Buffalo, USA", "US"),
    "Ashburn": ("Ashburn, USA", "US"),
    "Ogden": ("Ogden, USA", "US"),
    "Chicago": ("Chicago, USA", "US"),
    "San Jose": ("San Jose, USA", "US"),
    "Phoenix": ("Phoenix, USA", "US"),
    "Los Angeles": ("Los Angeles, USA", "US"),
    "Jacksonville": ("Jacksonville, USA", "US"),
    "Kansas City": ("Kansas City, USA", "US"),
    "Dallas": ("Dallas, USA", "US"),
    "Toronto": ("Toronto, Canada", "CA"),
    "Coventry": ("Coventry, United Kingdom", "GB"),
    "Amsterdam": ("Amsterdam, Netherlands", "NL"),
    "Frankfurt": ("Frankfurt, Germany", "DE"),
    "Düsseldorf": ("Düsseldorf, Germany", "DE"),
    "Singapore": ("Singapore", "SG"),
    "Tokyo": ("Tokyo, Japan", "JP"),
    "Hong Kong": ("Hong Kong", "HK"),
}
# SmokyHosts: город — в имени товара («Size M VPS, Roubaix, France»)
_SMOKYHOSTS_REGIONS: Mapping[str, tuple[str, str]] = {
    "Bufallo": ("Buffalo, USA", "US"),
    "Buffalo": ("Buffalo, USA", "US"),
    "Los Angeles": ("Los Angeles, USA", "US"),
    "Kansas City": ("Kansas City, USA", "US"),
    "Tampa": ("Tampa, USA", "US"),
    "Bend": ("Bend, USA", "US"),
    "Montreal": ("Montreal, Canada", "CA"),
    "Roubaix": ("Roubaix, France", "FR"),
    "London": ("London, United Kingdom", "GB"),
    "Vestfold": ("Vestfold, Norway", "NO"),
    "Mazovia": ("Warsaw, Poland", "PL"),
    "Mumbai": ("Mumbai, India", "IN"),
    "Singapore": ("Singapore", "SG"),
    "Hong Kong": ("Hong Kong", "HK"),
    "Sydney": ("Sydney, Australia", "AU"),
}

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
    # Virtono (Румыния): KVM в 13 городах Европы, США и Азии
    "virtono": tuple(
        WhmcsPage(f"{_VIRTONO}{slug}", region, country, currency="EUR")
        for slug, region, country in (
            ("bucharest-ro-vps", "Bucharest, Romania", "RO"),
            ("amsterdam-nl-vps", "Amsterdam, Netherlands", "NL"),
            ("budapest-hu-vps", "Budapest, Hungary", "HU"),
            ("copenhagen-dk-vps", "Copenhagen, Denmark", "DK"),
            ("frankfurt-de-vps", "Frankfurt, Germany", "DE"),
            ("madrid-es-vps", "Madrid, Spain", "ES"),
            ("milan-it-vps", "Milan, Italy", "IT"),
            ("miami-fl-vps", "Miami, USA", "US"),
            ("new-york-ny-vps", "New York, USA", "US"),
            ("hong-kong-hk-vps", "Hong Kong", "HK"),
            ("singapore-sg-vps", "Singapore", "SG"),
            ("tokyo-jp-vps", "Tokyo, Japan", "JP"),
            ("sydney-au-vps", "Sydney, Australia", "AU"),
        )
    ),
    # VM6 Networks: бюджетные VPS в Великобритании (Норвич)
    "vm6-networks": (
        WhmcsPage("https://www.vm6.co.uk/manager/store/budget-uk-vps-hosting", "Norwich, United Kingdom", "GB"),
    ),
    # Casbay: Linux VPS в Малайзии
    "casbay": (WhmcsPage("https://billing.casbay.com/store/linux-vps-my-t2", "Kuala Lumpur, Malaysia", "MY"),),
    # HypeHost: VPS в Сан-Паулу, цены в реалах
    "hypehost": (
        WhmcsPage("https://my.hypehost.com.br/index.php?rp=/store/vps-ryzen-sao-paulo", "Sao Paulo, Brazil", "BR"),
        WhmcsPage("https://my.hypehost.com.br/index.php?rp=/store/vps-sao-paulo", "Sao Paulo, Brazil", "BR"),
    ),
    # Lyra Hosting: Linux VPS в Нидерландах
    "lyrahosting": (
        WhmcsPage("https://my.lyrahosting.com/store/linux-vps-netherlands", "Netherlands", "NL", currency="EUR"),
    ),
    # LetsHost: VPS в Ирландии (Дублин)
    "letshost": (
        WhmcsPage(
            "https://billing.letshost.ie/index.php?rp=/store/vps-servers", "Dublin, Ireland", "IE", currency="EUR"
        ),
    ),
    # WebSouls: VPS в Пакистане
    "websouls": (
        WhmcsPage(
            "https://billing.websouls.com/index.php?rp=/store/virtual-private-server-pak-based", "Pakistan", "PK"
        ),
    ),
    # HostPro.by: VPS в Беларуси, цены в белорусских рублях
    "hostpro-by": (WhmcsPage("https://my.hostpro.by/store/vps-vds", "Minsk, Belarus", "BY", currency="BYN"),),
    # Servarica: KVM-слайсы в Монреале
    "servarica": (
        WhmcsPage("https://clients.servarica.com/store/v3-kvm-slices", "Montreal, Canada", "CA"),
        WhmcsPage("https://clients.servarica.com/store/v3-kvm-fat", "Montreal, Canada", "CA"),
        WhmcsPage("https://clients.servarica.com/store/nvme-plans", "Montreal, Canada", "CA"),
    ),
    # iHost.al: VPS в Албании
    "ihost-al": (WhmcsPage("https://www.my.ihost.al/store/vps-hosting", "Tirana, Albania", "AL", currency="EUR"),),
    # Baboon Hosting: KVM VPS в Амстердаме
    "baboonhosting": (
        WhmcsPage(
            "https://clients.baboonhosting.com/index.php?rp=/store/kvmvps",
            "Amsterdam, Netherlands",
            "NL",
            currency="EUR",
        ),
    ),
    # WebTuga: VPS в Португалии
    "webtuga": (
        WhmcsPage(
            "https://clientes.webtuga.pt/index.php?rp=/store/vps-ssd-unmanaged-2024",
            "Lisbon, Portugal",
            "PT",
            currency="EUR",
        ),
    ),
    # GreenCloud: KVM и EPYC VDS в 19 городах США, Канады, Европы и Азии
    "greencloudvps": tuple(
        WhmcsPage(f"{_GREENCLOUD}{group}", "USA", "US", regions=_GREENCLOUD_REGIONS)
        for group in ("budget-kvm-sale", "premium-kvm-sale", "epyc-nvme-kvm-vds")
    ),
    # SmokyHosts: VPS в 15 городах, локация — в имени тарифа
    "smokyhosts": (WhmcsPage("https://members.smokyhosts.com/store/vps", "USA", "US", regions=_SMOKYHOSTS_REGIONS),),
    # AdminVPS: VPS в России, Беларуси и Европе, цены в рублях («руб.»)
    "adminvps": tuple(
        WhmcsPage(f"{_ADMINVPS}{group}", region, country)
        for group, region, country in (
            ("vps-moshchnyi", "Moscow, Russia", "RU"),
            ("vps-moshniy-belarus", "Belarus", "BY"),
            ("vps-finland", "Finland", "FI"),
            ("vps-poland", "Poland", "PL"),
            ("vps-france", "France", "FR"),
            ("vps-italy", "Italy", "IT"),
            ("vps-spain", "Spain", "ES"),
            ("vps-switzerland", "Switzerland", "CH"),
        )
    ),
    # Домишко: KVM VDS в Нидерландах
    "domishko": (WhmcsPage("https://my.domishko.ru/index.php/store/vds-servery", "Netherlands", "NL"),),
    # George Datacenter: AMD EPYC VPS в Эшберне и Далласе
    "george-datacenter": (
        WhmcsPage("https://desk.georgedatacenter.com/store/ashburn-amd-7443p-7b13", "Ashburn, USA", "US"),
        WhmcsPage("https://desk.georgedatacenter.com/store/dallas-amd-7443p", "Dallas, USA", "US"),
    ),
    # WORLDBUS: SSD VPS в Тбилиси, Стамбуле и Европе (тема Lagom)
    "worldbus": tuple(
        WhmcsPage(f"https://portal.worldbus.ge/store/{group}", region, country)
        for group, region, country in (
            ("ssd-vps-in-georgia", "Tbilisi, Georgia", "GE"),
            ("ssd-vps-in-turkey", "Istanbul, Turkey", "TR"),
            ("ssd-vps-in-germany", "Falkenstein, Germany", "DE"),
            ("ssd-vps-in-netherlands", "Naaldwijk, Netherlands", "NL"),
            ("standard-vps-in-france", "France", "FR"),
            ("standard-vps-in-united-kingdom", "United Kingdom", "GB"),
        )
    ),
    # Cloudfanatic: KVM VPS в четырёх городах США
    "cloudfanatic": tuple(
        WhmcsPage(f"https://my.cloudfanatic.net/store/{group}", region, "US")
        for group, region in (
            ("chicago-10gbps-cloud", "Chicago, USA"),
            ("la-ssd-kvm-vps", "Los Angeles, USA"),
            ("nc-ssd-kvm-vps", "Raleigh, USA"),
            ("phoenix-cloud", "Phoenix, USA"),
        )
    ),
    # INIZ: SSD VPS в Лос-Анджелесе, Нью-Йорке и Ковентри, цены в фунтах
    "iniz": tuple(
        WhmcsPage(f"https://my.iniz.com/store/{group}", region, country)
        for group, region, country in (
            ("la-ssd-vps", "Los Angeles, USA", "US"),
            ("nyc-ssd-vps", "New York, USA", "US"),
            ("uk-ssd-vps", "Coventry, United Kingdom", "GB"),
        )
    ),
    # iON Cloud by Krypt: VPS в США и Сингапуре
    "krypt-ion": tuple(
        WhmcsPage(f"https://ion.krypt.asia/store/vps-cloud-{group}", region, country)
        for group, region, country in (
            ("los-angeles", "Los Angeles, USA", "US"),
            ("silicon-valley", "San Jose, USA", "US"),
            ("dallas", "Dallas, USA", "US"),
            ("honolulu", "Honolulu, USA", "US"),
            ("singapore", "Singapore", "SG"),
        )
    ),
    # Mynymbox: KVM VPS в Хельсинки и Амстердаме
    "mynymbox": (
        WhmcsPage("https://client.mynymbox.io/store/kvm-vps-finland", "Helsinki, Finland", "FI"),
        WhmcsPage("https://client.mynymbox.io/store/kvm-vps-netherlands", "Amsterdam, Netherlands", "NL"),
    ),
    # Napoleon: VPS в Бразилии и США, цены в реалах
    "napoleon": (
        WhmcsPage("https://painel.napoleon.com.br/store/cloud-bra", "Brazil", "BR"),
        WhmcsPage("https://painel.napoleon.com.br/store/cloud", "USA", "US"),
    ),
    # Noble VPS: VPS в Финиксе
    "noblevps": (WhmcsPage("https://dash.noblevps.com/index.php?rp=/store/usa-vps", "Phoenix, USA", "US"),),
    # Royal Server: VPS в Румынии
    "royal-server": (
        WhmcsPage("https://royaldata.ro/index.php/store/vps-server", "Romania", "RO"),
        WhmcsPage("https://royaldata.ro/index.php/store/vps-kvm-ryzen-9-9950x-nvme-gen-5", "Romania", "RO"),
    ),
    # Binary Racks: VPS в Великобритании, цены в фунтах (тема Lagom)
    "binary-racks": tuple(
        WhmcsPage(f"https://portal.binaryracks.com/index.php?rp=/store/{group}&currency=14", "United Kingdom", "GB")
        for group in ("vps", "budget-vps")
    ),
    # HostSlim: VPS в Нидерландах и Эстонии
    "hostslim": (
        WhmcsPage(
            "https://clients.hostslim.eu/store/vps-hosting",
            "Netherlands",
            "NL",
            regions={"Estonia": ("Estonia", "EE")},
        ),
    ),
    # Datacom: облачные VPS в Монголии, цены в тугриках (тема Lagom)
    "datacom-mn": (WhmcsPage("https://manage.datacom.mn/store/cloud", "Mongolia", "MN"),),
}
