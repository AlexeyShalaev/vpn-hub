// Реестр провайдеров с живыми тарифами — зеркало `backend/.../provider_plans/keys.py` (PLAN_SOURCES).
// Совпадение id/подписей проверяет backend-тест реестра, так что добавлять провайдера нужно в оба места.
// aliases — дополнительные написания имени (домен, сокращение); id и label сопоставляются и так.

export interface PlanSource {
  id: string;
  label: string;
  aliases: string[];
}

export const PLAN_SOURCES: readonly PlanSource[] = [
  { id: "firstbyte", label: "FirstByte", aliases: [] },
  { id: "ufo", label: "UFO Hosting", aliases: [] },
  { id: "ishosting", label: "ISHOSTING", aliases: ["ishosting.com"] },
  { id: "ahost", label: "AHost", aliases: ["ahost.eu"] },
  { id: "serverspace", label: "Serverspace", aliases: ["serverspace.ru", "serverspace.io"] },
  { id: "ultahost", label: "UltaHost", aliases: ["ulta", "ultahost.com"] },
  { id: "62yun", label: "62YUN", aliases: ["yun62", "62yun.ru"] },
  { id: "timeweb", label: "Timeweb Cloud", aliases: ["timeweb.cloud", "timeweb.com", "timeweb.ru"] },
  { id: "beget", label: "Beget", aliases: ["beget.com", "beget.ru"] },
  { id: "hetzner", label: "Hetzner", aliases: ["hetzner.com", "hetzner cloud"] },
  { id: "vultr", label: "Vultr", aliases: ["vultr.com"] },
  { id: "linode", label: "Akamai (Linode)", aliases: ["linode", "linode.com", "akamai", "akamai cloud"] },
  { id: "cherry-servers", label: "Cherry Servers", aliases: ["cherry", "cherryservers.com"] },
  { id: "edis-global", label: "EDIS Global", aliases: ["edis", "edisglobal.com"] },
  { id: "flokinet", label: "FlokiNET", aliases: ["flokinet.is"] },
  { id: "zappie-host", label: "Zappie Host", aliases: ["zappiehost.com"] },
  {
    id: "idhost-kazakhtelecom",
    label: "iDHost (Kazakhtelecom)",
    aliases: ["idhost", "idhost.kz", "idhost.telecom.kz"],
  },
  { id: "hosteroid", label: "Hosteroid", aliases: ["hosteroid.uk"] },
  { id: "firstvds", label: "FirstVDS", aliases: ["firstvds.ru"] },
  { id: "profitserver", label: "ProfitServer", aliases: ["profitserver.ru", "profitserver.pro"] },
  { id: "smartape", label: "SmartApe", aliases: ["smartape.ru"] },
  { id: "cloud4box", label: "Cloud4box", aliases: ["cloud4box.com"] },
  { id: "kvmka", label: "KVMka", aliases: ["kvmka.ru"] },
  { id: "datacheap", label: "DataCheap", aliases: ["datacheap.ru"] },
  { id: "askohost", label: "AskoHost", aliases: ["asko.host"] },
  { id: "skystark", label: "Skystark", aliases: ["skystark.ru", "skystark.net"] },
  { id: "vds-sh", label: "VDS.SH", aliases: ["vdssh", "vds.sh"] },
  { id: "ln-tech", label: "LNTech", aliases: ["ln-tech.ru"] },
  { id: "1bx-host", label: "1BX.host", aliases: ["1bx"] },
  { id: "coopertino", label: "Coopertino", aliases: ["купертино", "coopertino.ru"] },
  { id: "general-it", label: "General iT", aliases: ["g-i-t.ru", "git.ru"] },
  { id: "itsoft", label: "ITSOFT", aliases: ["itsoft.ru"] },
  { id: "multihost", label: "MultiHOST", aliases: ["multihost.com"] },
  { id: "planetahost", label: "PlanetaHost", aliases: ["planetahost.ru"] },
  { id: "simple-server", label: "Simple-server", aliases: ["simple-server.ru"] },
  { id: "appletec", label: "Appletec", aliases: ["appletec.ru"] },
  { id: "artplanet", label: "ArtPlanet", aliases: ["artplanet.ru"] },
  { id: "contell", label: "Contell", aliases: ["contell.ru"] },
  { id: "ispserver", label: "ISPserver", aliases: ["ispserver.ru"] },
  { id: "ihor", label: "IHOR Hosting", aliases: ["айхор", "ihor-hosting.ru", "ihor.online"] },
  { id: "spacecore", label: "SpaceCore", aliases: ["spacecore.pro"] },
  { id: "xorek", label: "XorekCloud", aliases: ["xorek", "xorek.cloud"] },
  { id: "u1host", label: "U1 HOST", aliases: ["u1host.com"] },
];
