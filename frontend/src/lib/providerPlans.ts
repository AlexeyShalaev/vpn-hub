import { tg } from "./i18n";
import type { Provider, ProviderPlan } from "./types";

// --- форматирование тарифов (общее для ServerForm-автозаполнения и каталога) ---
export function pricePeriodLabel(period: string): string {
  const labels: Record<string, string> = {
    minute: tg("plan.periodMinute"),
    day: tg("plan.periodDay"),
    month: tg("plan.periodMonth"),
  };
  return labels[period] ?? period;
}

export function fmtTraffic(tb: number | null): string {
  return tb == null ? tg("plan.trafficUnlimited") : tg("plan.trafficTb", { tb });
}

export function fmtPrice(p: ProviderPlan): string {
  return `${p.price.toLocaleString("ru-RU")} ${p.currency}/${pricePeriodLabel(p.period)}`;
}

export function fmtPort(p: ProviderPlan): string {
  return p.portMbps > 0 ? tg("plan.portMbps", { mbps: p.portMbps }) : tg("plan.portUnspecified");
}

export function planSpecs(p: ProviderPlan): string {
  return `${tg("plan.specsCpuRam", { cpu: p.cpu, ram: p.ramGb })} · ${tg("plan.specsDisk", { disk: p.diskGb, type: p.diskType })} · ${fmtPort(p)} · ${fmtTraffic(p.trafficTb)}`;
}

// --- приведение цен тарифов к одной валюте за месяц (для подбора по всем провайдерам) ---

// множитель «цена за период → цена за месяц»: месяц как ~30.44 дня (365.25/12), чтобы день/минута
// (если провайдер вдруг тарифицирует не помесячно) честно сравнивались с помесячными тарифами.
const DAYS_PER_MONTH = 365.25 / 12;
const MONTHLY_FACTOR: Record<string, number> = {
  month: 1,
  day: DAYS_PER_MONTH,
  minute: DAYS_PER_MONTH * 24 * 60,
};

// цена плана, приведённая к месяцу (в его собственной валюте); неизвестный период считаем месячным
export function monthlyPrice(price: number, period: string): number {
  return price * (MONTHLY_FACTOR[period] ?? 1);
}

// перевод суммы между валютами по курсам ЦБ (rates[X] = сколько base за 1 единицу X, base = 1).
// Возвращает null, если курс любой из валют неизвестен/некорректен — тогда сравнивать нельзя.
export function convertAmount(amount: number, from: string, to: string, rates: Record<string, number>): number | null {
  if (from === to) return amount; // одинаковые валюты — курс не нужен
  const rFrom = rates[from];
  const rTo = rates[to];
  if (!rFrom || !rTo || rFrom <= 0 || rTo <= 0) return null;
  return (amount * rFrom) / rTo;
}

// месячная цена плана в выбранной валюте (null, если пересчёт невозможен из-за отсутствия курса)
export function monthlyPriceIn(plan: ProviderPlan, currency: string, rates: Record<string, number>): number | null {
  return convertAmount(monthlyPrice(plan.price, plan.period), plan.currency, currency, rates);
}

const CURRENCY_SYMBOL: Record<string, string> = { RUB: "₽", USD: "$", EUR: "€" };
export function currencySymbol(code: string): string {
  return CURRENCY_SYMBOL[code] ?? code;
}

// сумма с разделителями разрядов и символом валюты; дробные знаки — только для мелких сумм
export function fmtMoney(amount: number, currency: string): string {
  const digits = amount >= 100 ? 0 : amount >= 10 ? 1 : 2;
  const num = amount.toLocaleString("ru-RU", { maximumFractionDigits: digits });
  return `${num} ${currencySymbol(currency)}`;
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
