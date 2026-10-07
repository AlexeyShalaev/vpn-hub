"""Провайдеры на ISPsystem BILLmanager: адрес биллинга с публичным прайсом и страница тарифов на сайте.

Разбор выгрузки общий (`..billmanager`). `country` задан для провайдеров, у которых все площадки в одной
стране (имена ДЦ вроде «NORD4» или «МMTC-9» страну не называют); у остальных страна берётся из имени ДЦ.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..billmanager import BillmanagerSource as Src

BILLMANAGER_SOURCES: Mapping[str, Src] = {
    "firstvds": Src("https://my.firstvds.ru/billmgr", "https://firstvds.ru/products/vds_vps_cloud"),
    "profitserver": Src("https://ps.profitserver.pro/billmgr", "https://profitserver.ru/"),
    "smartape": Src("https://cp.smartape.ru/billmgr", "https://www.smartape.ru/vps"),
    "cloud4box": Src("https://client.cloud4box.com/billmgr", "https://cloud4box.com/"),
    "kvmka": Src("https://billing.kvmka.ru/billmgr", "https://kvmka.ru/", dc_countries={"Гонконг": "HK"}),
    "datacheap": Src("https://vps.datacheap.ru/billmgr", "https://datacheap.ru/services/arenda-vps-vds-serverov/"),
    "askohost": Src("https://my.asko.host/billmgr", "https://asko.host/vps"),
    "skystark": Src("https://my.skystark.net/billmgr", "https://skystark.ru/"),
    "vds-sh": Src("https://my.vds.sh/manager/billmgr", "https://vds.sh/ru/"),
    "ln-tech": Src("https://lk.ln-tech.ru/billmgr", "https://ln-tech.ru/", country="RU"),
    "1bx-host": Src("https://my.1bx.host/billmgr", "https://1bx.host/", country="RU"),
    "coopertino": Src("https://my.coopertino.ru/billmgr", "https://coopertino.ru/", country="RU"),
    "general-it": Src("https://my.g-i-t.ru/billmgr", "https://git.ru/", country="RU"),
    "itsoft": Src("https://cloud.itsoft.ru/billmgr", "https://itsoft.ru/data-center/vds/", country="RU"),
    "multihost": Src("https://id.multihost.com/billmgr", "https://multihost.com/", dc_countries={"IXcellerate": "RU"}),
    "planetahost": Src("https://bill.planetahost.ru/billmgr", "https://planetahost.ru/", country="RU"),
    "simple-server": Src("https://bill.simple-server.ru/billmgr", "https://simple-server.ru/", country="RU"),
    "appletec": Src("https://shop.appletec.ru/billmgr", "https://appletec.ru/", country="RU"),
    "artplanet": Src("https://bill.artplanet.ru/manager/billmgr", "https://artplanet.ru/", country="RU"),
    "contell": Src("https://lk.contell.ru/billmgr", "https://contell.ru/", country="RU"),
    "ispserver": Src("https://my.ispserver.ru/manager/billmgr", "https://ispserver.ru/", country="RU"),
    "ihor": Src("https://billing.ihor-hosting.ru/billmgr", "https://ihor.online/vds", dc_countries={"Москва": "RU"}),
    "spacecore": Src("https://billing.spacecore.pro/billmgr", "https://spacecore.pro/ru/"),
    "xorek": Src("https://my.xorek.cloud/billmgr", "https://xorek.cloud/ru/vps"),
    "u1host": Src("https://my.u1host.com/billmgr", "https://u1host.com/ru"),
}
