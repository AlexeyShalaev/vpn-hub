"""Реестр источников динамических тарифов: id, подпись и синонимы имени провайдера.

Один источник правды для «какие провайдеры умеют живые тарифы»: id нормализуется из любого
написания (`UFO Hosting`, `ufo-hosting`, `ufo.hosting` → `ufo`). Фронтенд держит зеркальный список
в `frontend/src/lib/planSources.ts` — их совпадение проверяет тест реестра.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanSource:
    id: str
    label: str
    aliases: tuple[str, ...] = ()


PLAN_SOURCES: tuple[PlanSource, ...] = (
    PlanSource("firstbyte", "FirstByte"),
    PlanSource("ufo", "UFO Hosting"),
    PlanSource("ishosting", "ISHOSTING", ("ishosting.com",)),
    PlanSource("ahost", "AHost", ("ahost.eu",)),
    PlanSource("serverspace", "Serverspace", ("serverspace.ru", "serverspace.io")),
    PlanSource("ultahost", "UltaHost", ("ulta", "ultahost.com")),
    PlanSource("62yun", "62YUN", ("yun62", "62yun.ru")),
    PlanSource("timeweb", "Timeweb Cloud", ("timeweb.cloud", "timeweb.com", "timeweb.ru")),
    PlanSource("beget", "Beget", ("beget.com", "beget.ru")),
    PlanSource("hetzner", "Hetzner", ("hetzner.com", "hetzner cloud")),
    PlanSource("vultr", "Vultr", ("vultr.com",)),
    PlanSource("linode", "Akamai (Linode)", ("linode", "linode.com", "akamai", "akamai cloud")),
    PlanSource("cherry-servers", "Cherry Servers", ("cherry", "cherryservers.com")),
    PlanSource("4vps", "4VPS", ("4vps.su", "fourvps")),
    PlanSource("binarylane", "BinaryLane", ("binarylane.com.au",)),
    PlanSource("mammoth-cloud", "Mammoth Cloud", ("mammoth", "mammoth.com.au")),
    # WHMCS-витрины (providers/whmcs_stores.py)
    PlanSource("edis-global", "EDIS Global", ("edis", "edisglobal.com")),
    PlanSource("flokinet", "FlokiNET", ("flokinet.is",)),
    PlanSource("zappie-host", "Zappie Host", ("zappiehost.com",)),
    PlanSource("idhost-kazakhtelecom", "iDHost (Kazakhtelecom)", ("idhost", "idhost.kz", "idhost.telecom.kz")),
    PlanSource("hosteroid", "Hosteroid", ("hosteroid.uk",)),
    PlanSource("virtono", "Virtono", ("virtono.com",)),
    PlanSource("vm6-networks", "VM6 Networks", ("vm6", "vm6.co.uk")),
    PlanSource("webtuga", "WebTuga", ("webtuga.pt",)),
    PlanSource("casbay", "Casbay", ("casbay.com",)),
    PlanSource("hypehost", "HypeHost", ("hypehost.com.br",)),
    PlanSource("lyrahosting", "Lyra Hosting", ("lyrahosting.com",)),
    PlanSource("letshost", "LetsHost", ("letshost.ie",)),
    PlanSource("websouls", "WebSouls", ("websouls.com",)),
    PlanSource("hostpro-by", "HostPro.by", ("hostpro.by",)),
    PlanSource("servarica", "Servarica", ("servarica.com",)),
    PlanSource("ihost-al", "iHost.al", ("ihost.al",)),
    PlanSource("baboonhosting", "Baboon Hosting", ("baboonhosting.com",)),
    PlanSource("greencloudvps", "GreenCloud", ("greencloud", "greencloudvps.com")),
    PlanSource("smokyhosts", "SmokyHosts", ("smokyhosts.com",)),
    PlanSource("adminvps", "AdminVPS", ("adminvps.ru",)),
    PlanSource("domishko", "Домишко", ("domishko.ru",)),
    PlanSource("george-datacenter", "George Datacenter", ("georgedatacenter.com",)),
    PlanSource("worldbus", "WORLDBUS", ("worldbus.ge",)),
    PlanSource("cloudfanatic", "Cloudfanatic", ("cloudfanatic.net",)),
    PlanSource("iniz", "INIZ", ("iniz.com",)),
    PlanSource("krypt-ion", "iON Cloud by Krypt", ("krypt", "ion.krypt.asia")),
    PlanSource("mynymbox", "Mynymbox", ("mynymbox.io",)),
    PlanSource("napoleon", "Napoleon", ("napoleon.com.br",)),
    PlanSource("noblevps", "Noble VPS", ("noblevps.com",)),
    PlanSource("royal-server", "Royal Server", ("royal-server.ro", "royaldata.ro")),
    PlanSource("binary-racks", "Binary Racks", ("binaryracks.com",)),
    PlanSource("hostslim", "HostSlim", ("hostslim.eu",)),
    PlanSource("datacom-mn", "Datacom", ("datacom.mn",)),
    # BILLmanager: публичный прайс-лист (providers/billmanager_sources.py)
    PlanSource("firstvds", "FirstVDS", ("firstvds.ru",)),
    PlanSource("profitserver", "ProfitServer", ("profitserver.ru", "profitserver.pro")),
    PlanSource("smartape", "SmartApe", ("smartape.ru",)),
    PlanSource("cloud4box", "Cloud4box", ("cloud4box.com",)),
    PlanSource("kvmka", "KVMka", ("kvmka.ru",)),
    PlanSource("datacheap", "DataCheap", ("datacheap.ru",)),
    PlanSource("askohost", "AskoHost", ("asko.host",)),
    PlanSource("skystark", "Skystark", ("skystark.ru", "skystark.net")),
    PlanSource("vds-sh", "VDS.SH", ("vdssh", "vds.sh")),
    PlanSource("ln-tech", "LNTech", ("ln-tech.ru",)),
    PlanSource("1bx-host", "1BX.host", ("1bx",)),
    PlanSource("coopertino", "Coopertino", ("купертино", "coopertino.ru")),
    PlanSource("general-it", "General iT", ("g-i-t.ru", "git.ru")),
    PlanSource("itsoft", "ITSOFT", ("itsoft.ru",)),
    PlanSource("multihost", "MultiHOST", ("multihost.com",)),
    PlanSource("planetahost", "PlanetaHost", ("planetahost.ru",)),
    PlanSource("simple-server", "Simple-server", ("simple-server.ru",)),
    PlanSource("appletec", "Appletec", ("appletec.ru",)),
    PlanSource("artplanet", "ArtPlanet", ("artplanet.ru",)),
    PlanSource("contell", "Contell", ("contell.ru",)),
    PlanSource("ispserver", "ISPserver", ("ispserver.ru",)),
    PlanSource("ihor", "IHOR Hosting", ("айхор", "ihor-hosting.ru", "ihor.online")),
    PlanSource("spacecore", "SpaceCore", ("spacecore.pro",)),
    PlanSource("xorek", "XorekCloud", ("xorek", "xorek.cloud")),
    PlanSource("u1host", "U1 HOST", ("u1host.com",)),
    PlanSource("retzor", "Retzor", ("retzor.com",)),
    PlanSource("megahost-kz", "MEGAHOST", ("megahost", "megahost.kz")),
    PlanSource("itldc", "ITLDC", ("itldc.com",)),
    PlanSource("rusonyx", "Rusonyx", ("rusonyx.ru", "русоникс")),
    PlanSource("optibit", "Optibit", ("оптибит", "optibit.ru")),
    PlanSource("senko-digital", "Senko Digital", ("senko", "senko.digital")),
)

_COMPACT_RE = re.compile(r"[\s._-]+")


def _compact(value: str) -> str:
    return _COMPACT_RE.sub("", value.strip().lower())


_ALIASES: dict[str, str] = {
    _compact(name): src.id for src in PLAN_SOURCES for name in (src.id, src.label, *src.aliases)
}


def _provider_key(provider_id: str) -> str:
    raw = (provider_id or "").strip().lower()
    return _ALIASES.get(_compact(raw), raw)
