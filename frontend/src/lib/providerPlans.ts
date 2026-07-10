import type { Provider, ProviderPlan } from "./types";

// --- форматирование тарифов (общее для ServerForm-автозаполнения и каталога) ---
export const PRICE_PERIOD_LABEL: Record<string, string> = { minute: "мин", day: "день", month: "мес" };

export function fmtTraffic(tb: number | null): string {
  return tb == null ? "безлимит" : `${tb} ТБ`;
}

export function fmtPrice(p: ProviderPlan): string {
  return `${p.price.toLocaleString("ru-RU")} ${p.currency}/${PRICE_PERIOD_LABEL[p.period] ?? p.period}`;
}

export function fmtPort(p: ProviderPlan): string {
  return p.portMbps > 0 ? `${p.portMbps} Мбит` : "порт не указан";
}

export function planSpecs(p: ProviderPlan): string {
  return `${p.cpu}vCPU/${p.ramGb}ГБ RAM · ${p.diskGb}ГБ ${p.diskType} · ${fmtPort(p)} · ${fmtTraffic(p.trafficTb)}`;
}

export const DYNAMIC_PLAN_PROVIDER_LABELS: Record<string, string> = {
  ahost: "AHost",
  firstbyte: "FirstByte",
  ishosting: "ISHOSTING",
  serverspace: "Serverspace",
  ufo: "UFO Hosting",
};

export function normalizeProviderKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s._-]+/g, "");
}

export function isDynamicPlanProviderId(providerId: string | undefined): providerId is string {
  return !!providerId && Object.hasOwn(DYNAMIC_PLAN_PROVIDER_LABELS, providerId);
}

export function dynamicPlanProviderIdByName(name: string): string {
  const key = normalizeProviderKey(name);
  if (key === "ahost" || key === "ahosteu") return "ahost";
  if (key === "firstbyte") return "firstbyte";
  if (key === "ishosting" || key === "ishostingcom") return "ishosting";
  if (key === "serverspace" || key === "serverspaceru" || key === "serverspaceio") return "serverspace";
  if (key === "ufo" || key === "ufohosting") return "ufo";
  return "";
}

export function findDynamicPlanProvider(providers: Provider[], providerName: string): Provider | null {
  const id = dynamicPlanProviderIdByName(providerName);
  if (!id) return null;
  return providers.find((p) => p.id.toLowerCase() === id || dynamicPlanProviderIdByName(p.name) === id) ?? null;
}

export function dynamicPlanProviderId(provider: Provider | null, providerName: string): string {
  const byId = (provider?.id ?? "").toLowerCase();
  if (isDynamicPlanProviderId(byId)) return byId;
  const byKnownName = dynamicPlanProviderIdByName(provider?.name ?? "");
  if (byKnownName) return byKnownName;
  return dynamicPlanProviderIdByName(providerName);
}

export function planProviderDisplayName(providerId: string): string {
  return DYNAMIC_PLAN_PROVIDER_LABELS[providerId] ?? providerId;
}

export function providerNameById(providers: Provider[], providerId: string): string {
  const p = providers.find((pp) => pp.id === providerId);
  if (p) return p.name;
  if (isDynamicPlanProviderId(providerId)) return planProviderDisplayName(providerId);
  return providerId;
}
