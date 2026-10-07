// Каталог провайдеров: двуязычное описание и справочник способов оплаты (порядок — как у бэкенда).

import { type Lang, tFor } from "./i18n";
import { countryLabel } from "./locations";
import type { PaymentMethod, Provider } from "./types";

export const PAYMENT_METHODS: readonly PaymentMethod[] = [
  "ru_card",
  "sbp",
  "ru_wallet",
  "crypto",
  "card",
  "paypal",
  "bank",
  "local",
];

// описание карточки на языке интерфейса; английского нет — показываем русское
export function providerBlurb(p: Provider, lang: Lang): string {
  return lang === "en" && p.blurbEn ? p.blurbEn : p.blurb;
}

// ── поиск и фильтры каталога ────────────────────────────────────────────────────

export type CatalogSort = "catalog" | "name" | "locations";

export interface CatalogFilter {
  query: string; // слова запроса: имя, сайт, описание (оба языка), теги, названия стран
  countries: string[]; // хоть одна из локаций (ISO-коды); пусто = любые
  payments: PaymentMethod[]; // хоть один из способов оплаты; пусто = любые
  hq: string[]; // страна компании; пусто = любая
  liveOnly: boolean; // только провайдеры с живыми тарифами
  sort: CatalogSort;
}

export const EMPTY_CATALOG_FILTER: CatalogFilter = {
  query: "",
  countries: [],
  payments: [],
  hq: [],
  liveOnly: false,
  sort: "catalog",
};

const searchNorm = (s: string) => s.toLowerCase().replace(/ё/g, "е");

function haystack(p: Provider): string {
  return searchNorm([p.name, p.id, p.url, p.blurb, p.blurbEn, ...p.tags, ...p.countries.map(countryLabel)].join("\n"));
}

const anyOf = <T>(wanted: readonly T[], have: readonly T[]) =>
  wanted.length === 0 || wanted.some((w) => have.includes(w));

export function filterProviders(
  providers: readonly Provider[],
  f: CatalogFilter,
  hasLivePlans: (p: Provider) => boolean,
): Provider[] {
  const words = searchNorm(f.query).split(/\s+/).filter(Boolean);
  const out = providers.filter(
    (p) =>
      (words.length === 0 || words.every((w) => haystack(p).includes(w))) &&
      anyOf(f.countries, p.countries) &&
      anyOf(f.payments, p.payments) &&
      (f.hq.length === 0 || f.hq.includes(p.hq)) &&
      (!f.liveOnly || hasLivePlans(p)),
  );
  if (f.sort === "name") return out.sort((a, b) => a.name.localeCompare(b.name, "ru", { sensitivity: "base" }));
  if (f.sort === "locations") return out.sort((a, b) => b.countries.length - a.countries.length);
  return out; // порядок каталога (как в файле) — его задаёт администратор
}

// значения для мультивыбора с числом провайдеров у каждого: [значение, сколько]; по убыванию частоты
export function facetCounts(values: readonly (readonly string[])[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const list of values) for (const v of new Set(list)) if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}

// ── теги карточки ────────────────────────────────────────────────────────────────

// подписи способов оплаты на обоих языках: тег «Карта РФ» дублирует бейдж оплаты в любом языке интерфейса
const PAYMENT_TAGS = new Set(
  (["ru", "en"] as const).flatMap((l) => PAYMENT_METHODS.map((m) => tFor(l)(`pay.${m}`).toLowerCase())),
);

// типовые теги каталога (данные на русском) → английская подпись для английского интерфейса
const TAG_EN: Record<string, string> = {
  "почасовая оплата": "Hourly billing",
  "безлимитный трафик": "Unmetered traffic",
  "много локаций": "Many locations",
  "nvme и hdd": "NVMe & HDD",
};

function tagLabel(tag: string, lang: Lang): string {
  if (lang !== "en") return tag;
  const key = tag.toLowerCase();
  if (TAG_EN[key]) return TAG_EN[key];
  const m = /^(\d+\+?)\s+(стран|страны|страна|локаций|локации)$/i.exec(tag.trim());
  if (m) return `${m[1]} ${m[2].startsWith("стран") ? "countries" : "locations"}`;
  return tag;
}

// теги для карточки: без повторов способов оплаты, на языке интерфейса, где перевод известен
export function cardTags(p: Provider, lang: Lang): string[] {
  return p.tags.filter((t) => !PAYMENT_TAGS.has(t.toLowerCase())).map((t) => tagLabel(t, lang));
}
