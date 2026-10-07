// Подбор тарифа по всем провайдерам: чистая логика фильтров и сортировки (UI — PlanFinderModal в Catalog).
// Цены у провайдеров в разных валютах и периодах — всё сводится к месячной цене в выбранной валюте по
// курсу ЦБ (monthlyPriceIn), поэтому бюджет и сортировка по цене работают через провайдеров разом.

import { canonicalLocation } from "./locations";
import { monthlyPriceIn } from "./providerPlans";
import type { ProviderPlan } from "./types";

// план + к какому провайдеру относится (для агрегированного подбора)
export type FinderPlan = ProviderPlan & { providerId: string; providerLabel: string };
// плюс месячная цена, приведённая к выбранной валюте (null = пересчёт невозможен — нет курса)
export type RankedPlan = FinderPlan & { monthly: number | null };

export type PlanSort = "price" | "pricePerGb" | "ram" | "cpu";

export interface PlanFilter {
  query: string; // слова в названии тарифа, локации или провайдере
  regions: string[]; // канонические ключи локаций (ISO-коды)
  providers: string[]; // id источников тарифов
  ramMin: string; // поля диапазонов — как в инпутах; пусто = без ограничения
  ramMax: string;
  cpuMin: string;
  diskMin: string;
  portMin: string; // Мбит/с; тарифы без опубликованной скорости порта при этом отсекаются
  priceMin: string;
  priceMax: string;
  currency: string;
  diskTypes: string[]; // NVMe / SSD / HDD …; пусто = любые
  unlimitedOnly: boolean; // только безлимитный трафик
  onlyAvailable: boolean;
  sort: PlanSort;
}

export const DEFAULT_PLAN_FILTER: PlanFilter = {
  query: "",
  regions: [],
  providers: [],
  ramMin: "",
  ramMax: "",
  cpuMin: "",
  diskMin: "",
  portMin: "",
  priceMin: "",
  priceMax: "",
  currency: "RUB",
  diskTypes: [],
  unlimitedOnly: false,
  onlyAvailable: true,
  sort: "price",
};

// число из инпута диапазона; пустое/некорректное → значение по умолчанию (граница «без ограничения»)
export function numOr(text: string, fallback: number): number {
  const n = Number(text);
  return text.trim() !== "" && Number.isFinite(n) ? n : fallback;
}

const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");

// тарифы без пересчёта цены (нет курса) — всегда в конце, иначе по выбранному критерию
function compare(sort: PlanSort): (a: RankedPlan, b: RankedPlan) => number {
  const byPrice = (a: RankedPlan, b: RankedPlan) => {
    if (a.monthly == null || b.monthly == null) return (a.monthly == null ? 1 : 0) - (b.monthly == null ? 1 : 0);
    return a.monthly - b.monthly;
  };
  if (sort === "pricePerGb")
    return (a, b) => {
      if (a.monthly == null || b.monthly == null || a.ramGb <= 0 || b.ramGb <= 0) return byPrice(a, b);
      return a.monthly / a.ramGb - b.monthly / b.ramGb || byPrice(a, b);
    };
  if (sort === "ram") return (a, b) => b.ramGb - a.ramGb || byPrice(a, b);
  if (sort === "cpu") return (a, b) => b.cpu - a.cpu || byPrice(a, b);
  return byPrice;
}

export function rankPlans(all: readonly FinderPlan[], f: PlanFilter, rates: Record<string, number>): RankedPlan[] {
  const ramLo = numOr(f.ramMin, 0);
  const ramHi = numOr(f.ramMax, Number.POSITIVE_INFINITY);
  const cpuLo = numOr(f.cpuMin, 0);
  const diskLo = numOr(f.diskMin, 0);
  const portLo = numOr(f.portMin, 0);
  const priceLo = numOr(f.priceMin, 0);
  const priceHi = numOr(f.priceMax, Number.POSITIVE_INFINITY);
  const hasPriceBound = f.priceMin.trim() !== "" || f.priceMax.trim() !== "";
  const words = norm(f.query).split(/\s+/).filter(Boolean);
  return all
    .filter((p) => (f.onlyAvailable ? p.available !== false : true))
    .filter((p) => f.regions.length === 0 || f.regions.includes(canonicalLocation(p.region).key))
    .filter((p) => f.providers.length === 0 || f.providers.includes(p.providerId))
    .filter((p) => p.ramGb >= ramLo && p.ramGb <= ramHi && p.cpu >= cpuLo && p.diskGb >= diskLo)
    .filter((p) => portLo <= 0 || p.portMbps >= portLo)
    .filter((p) => f.diskTypes.length === 0 || f.diskTypes.includes(p.diskType))
    .filter((p) => !f.unlimitedOnly || p.trafficTb == null)
    .filter((p) => {
      if (words.length === 0) return true;
      const text = norm(`${p.name} ${p.region} ${p.providerLabel}`);
      return words.every((w) => text.includes(w));
    })
    .map((p) => ({ ...p, monthly: monthlyPriceIn(p, f.currency, rates) }))
    .filter((p) => (hasPriceBound ? p.monthly != null && p.monthly >= priceLo && p.monthly <= priceHi : true))
    .sort(compare(f.sort));
}
