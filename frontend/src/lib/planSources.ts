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
];
