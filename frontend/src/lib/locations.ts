// Каноникализация локаций тарифов. Один и тот же регион у разных провайдеров называется по-разному и на
// разных языках: ОАЭ / UAE / Арабские Эмираты / Дубай — это одно и то же. Сводим сырой регион к коду
// страны, чтобы в подборе фильтр показывал ОДНУ объединённую локацию (напр. «ОАЭ / UAE»), а не дубли.
// Города приводятся к стране (Мадрид → Испания, Амстердам → Нидерланды). Сырой `region` тарифа не
// меняется — каноникализация нужна только для группировки/фильтра в PlanFinder.
//
// Метки `ru`/`en` ниже — не UI-строки для перевода интерфейса, а данные: комбинированная билингвальная
// подпись локации (напр. «ОАЭ / UAE») показывается пользователю целиком независимо от языка интерфейса.

import { tg } from "./i18n";

interface Country {
  ru: string;
  en: string;
  aliases: string[]; // НОРМАЛИЗОВАННЫЕ синонимы (см. normLoc): оба языка + города/датацентры из каталогов
}

// Покрывает все локации, встречающиеся у firstbyte/ufo/ishosting/ahost/serverspace, + частые синонимы.
const COUNTRIES: Record<string, Country> = {
  AE: {
    ru: "ОАЭ",
    en: "UAE",
    aliases: [
      "оаэ",
      "uae",
      "united arab emirates",
      "арабские эмираты",
      "эмираты",
      "дубай",
      "dubai",
      "абу даби",
      "abu dhabi",
    ],
  },
  RU: {
    ru: "Россия",
    en: "Russia",
    aliases: [
      "россия",
      "russia",
      "russian federation",
      "рф",
      "москва",
      "moscow",
      "санкт петербург",
      "saint petersburg",
      "st petersburg",
      "спб",
      "питер",
    ],
  },
  KZ: {
    ru: "Казахстан",
    en: "Kazakhstan",
    aliases: ["казахстан", "kazakhstan", "алматы", "almaty", "астана", "astana", "kzg3"],
  },
  UZ: { ru: "Узбекистан", en: "Uzbekistan", aliases: ["узбекистан", "uzbekistan", "ташкент", "tashkent"] },
  DE: { ru: "Германия", en: "Germany", aliases: ["германия", "germany", "франкфурт", "frankfurt", "берлин", "berlin"] },
  NL: {
    ru: "Нидерланды",
    en: "Netherlands",
    aliases: ["нидерланды", "netherlands", "голландия", "holland", "амстердам", "amsterdam"],
  },
  FR: { ru: "Франция", en: "France", aliases: ["франция", "france", "париж", "paris"] },
  ES: { ru: "Испания", en: "Spain", aliases: ["испания", "spain", "мадрид", "madrid", "барселона", "barcelona"] },
  FI: { ru: "Финляндия", en: "Finland", aliases: ["финляндия", "finland", "хельсинки", "helsinki"] },
  BG: { ru: "Болгария", en: "Bulgaria", aliases: ["болгария", "bulgaria", "софия", "sofia"] },
  GB: {
    ru: "Великобритания",
    en: "United Kingdom",
    aliases: ["великобритания", "united kingdom", "англия", "uk", "лондон", "london"],
  },
  US: {
    ru: "США",
    en: "USA",
    aliases: [
      "сша",
      "usa",
      "united states",
      "америка",
      "нью джерси",
      "new jersey",
      "нью йорк",
      "new york",
      "лос анджелес",
      "los angeles",
      "сиэтл",
      "seattle",
      "даллас",
      "dallas",
      "чикаго",
      "chicago",
    ],
  },
  CA: { ru: "Канада", en: "Canada", aliases: ["канада", "canada", "торонто", "toronto", "монреаль", "montreal"] },
  BR: { ru: "Бразилия", en: "Brazil", aliases: ["бразилия", "brazil", "сан паулу", "sao paulo", "сан паоло"] },
  JP: { ru: "Япония", en: "Japan", aliases: ["япония", "japan", "токио", "tokyo"] },
  SG: { ru: "Сингапур", en: "Singapore", aliases: ["сингапур", "singapore"] },
  HK: { ru: "Гонконг", en: "Hong Kong", aliases: ["гонконг", "hong kong", "hongkong"] },
  IN: {
    ru: "Индия",
    en: "India",
    aliases: ["индия", "india", "мумбаи", "mumbai", "нью дели", "new delhi", "дели", "delhi"],
  },
  ID: { ru: "Индонезия", en: "Indonesia", aliases: ["индонезия", "indonesia", "джакарта", "jakarta"] },
  MY: { ru: "Малайзия", en: "Malaysia", aliases: ["малайзия", "malaysia", "куала лумпур", "kuala lumpur"] },
  TH: { ru: "Таиланд", en: "Thailand", aliases: ["таиланд", "thailand", "бангкок", "bangkok"] },
  AU: { ru: "Австралия", en: "Australia", aliases: ["австралия", "australia", "сидней", "sydney"] },
  AT: { ru: "Австрия", en: "Austria", aliases: ["австрия", "austria", "вена", "vienna", "грац", "graz"] },
  BE: { ru: "Бельгия", en: "Belgium", aliases: ["бельгия", "belgium"] },
  CH: { ru: "Швейцария", en: "Switzerland", aliases: ["швейцария", "switzerland", "цюрих", "zurich"] },
  CZ: { ru: "Чехия", en: "Czech Republic", aliases: ["чехия", "czech republic", "czechia", "прага", "prague"] },
  DK: { ru: "Дания", en: "Denmark", aliases: ["дания", "denmark", "копенгаген", "copenhagen"] },
  EE: { ru: "Эстония", en: "Estonia", aliases: ["эстония", "estonia", "таллин", "tallinn"] },
  GR: { ru: "Греция", en: "Greece", aliases: ["греция", "greece", "афины", "athens"] },
  HR: { ru: "Хорватия", en: "Croatia", aliases: ["хорватия", "croatia"] },
  HU: { ru: "Венгрия", en: "Hungary", aliases: ["венгрия", "hungary", "будапешт", "budapest"] },
  IE: { ru: "Ирландия", en: "Ireland", aliases: ["ирландия", "ireland", "дублин", "dublin"] },
  IS: { ru: "Исландия", en: "Iceland", aliases: ["исландия", "iceland", "рейкьявик", "reykjavik"] },
  IL: { ru: "Израиль", en: "Israel", aliases: ["израиль", "israel", "тель авив", "tel aviv"] },
  IT: {
    ru: "Италия",
    en: "Italy",
    aliases: ["италия", "italy", "милан", "milan", "палермо", "palermo", "рим", "rome"],
  },
  LV: { ru: "Латвия", en: "Latvia", aliases: ["латвия", "latvia", "рига", "riga"] },
  LT: { ru: "Литва", en: "Lithuania", aliases: ["литва", "lithuania", "вильнюс", "vilnius"] },
  MD: { ru: "Молдова", en: "Moldova", aliases: ["молдова", "moldova", "молдавия", "кишинев", "chisinau"] },
  MK: {
    ru: "Северная Македония",
    en: "North Macedonia",
    aliases: ["северная македония", "north macedonia", "македония", "macedonia"],
  },
  NO: { ru: "Норвегия", en: "Norway", aliases: ["норвегия", "norway", "осло", "oslo"] },
  PL: { ru: "Польша", en: "Poland", aliases: ["польша", "poland", "варшава", "warsaw"] },
  RO: { ru: "Румыния", en: "Romania", aliases: ["румыния", "romania", "бухарест", "bucharest"] },
  RS: { ru: "Сербия", en: "Serbia", aliases: ["сербия", "serbia", "белград", "belgrade"] },
  SE: { ru: "Швеция", en: "Sweden", aliases: ["швеция", "sweden", "стокгольм", "stockholm"] },
  SI: { ru: "Словения", en: "Slovenia", aliases: ["словения", "slovenia", "любляна", "ljubljana"] },
  TR: { ru: "Турция", en: "Turkey", aliases: ["турция", "turkey", "türkiye", "стамбул", "istanbul"] },
  UA: { ru: "Украина", en: "Ukraine", aliases: ["украина", "ukraine", "киев", "kyiv", "kiev"] },
  AR: { ru: "Аргентина", en: "Argentina", aliases: ["аргентина", "argentina", "буэнос айрес", "buenos aires"] },
  CL: { ru: "Чили", en: "Chile", aliases: ["чили", "chile", "сантьяго", "santiago"] },
  CO: { ru: "Колумбия", en: "Colombia", aliases: ["колумбия", "colombia", "богота", "bogota"] },
  MX: { ru: "Мексика", en: "Mexico", aliases: ["мексика", "mexico", "мехико", "mexico city"] },
  PE: { ru: "Перу", en: "Peru", aliases: ["перу", "peru", "лима", "lima"] },
  SA: {
    ru: "Саудовская Аравия",
    en: "Saudi Arabia",
    aliases: ["саудовская аравия", "saudi arabia", "саудовская", "эр рияд", "рияд", "riyadh"],
  },
  ZA: {
    ru: "ЮАР",
    en: "South Africa",
    aliases: ["юар", "south africa", "южная африка", "йоханнесбург", "johannesburg"],
  },
  NG: { ru: "Нигерия", en: "Nigeria", aliases: ["нигерия", "nigeria", "лагос", "lagos"] },
  // «georgia» без уточнения не ставим: это и штат США (Atlanta, Georgia) — только однозначные синонимы
  GE: { ru: "Грузия", en: "Georgia", aliases: ["грузия", "тбилиси", "tbilisi"] },
  KR: {
    ru: "Южная Корея",
    en: "South Korea",
    aliases: ["южная корея", "south korea", "корея", "korea", "сеул", "seoul"],
  },
};

const PUNCT_RE = /[()[\]{}.,/|·—–-]+/g;

// нормализация региона для матчинга: нижний регистр, ё→е, пунктуация/скобки → пробелы, схлопнуть пробелы
export function normLoc(s: string): string {
  return s.toLowerCase().replace(/ё/g, "е").replace(PUNCT_RE, " ").replace(/\s+/g, " ").trim();
}

// Остальные страны мира — из Intl.DisplayNames (ru + en): провайдеров сотни, все страны вручную не перечислить.
// Ручные записи выше приоритетнее (у них города и синонимы). Не-страны (EU, UN…) отбрасываем, а однословные
// имена, совпадающие с топонимами США (Jersey ↔ New Jersey, Georgia ↔ штат), в индекс не попадают.
const NON_COUNTRY_CODES = new Set([
  // не страны и псевдо-регионы
  ...["EU", "EZ", "UN", "QO", "ZZ", "XA", "XB", "AC", "CP", "CQ", "DG", "EA", "IC", "TA"],
  // устаревшие коды: иначе VD («Вьетнам») или YU («Сербия») перехватили бы имя у действующего кода
  ...["AN", "BU", "CS", "DD", "DY", "FX", "HV", "NH", "NT", "RH", "SU", "TP", "VD", "YD", "YU", "ZR"],
]);
const AMBIGUOUS_CODES = new Set(["JE", "GE"]);

function displayNames(lang: string): Intl.DisplayNames | null {
  try {
    return new Intl.DisplayNames([lang], { type: "region" });
  } catch {
    return null; // окружение без Intl.DisplayNames — обходимся ручным списком
  }
}
const DN_RU = displayNames("ru");
const DN_EN = displayNames("en");

function intlName(dn: Intl.DisplayNames | null, code: string): string | null {
  if (!dn) return null;
  try {
    const name = dn.of(code);
    return name && name !== code ? name : null;
  } catch {
    return null;
  }
}

// все двухбуквенные коды, у которых Intl знает имя страны/территории (кроме ручных и не-стран)
const INTL_COUNTRIES: Record<string, Country> = {};
for (let a = 65; a <= 90; a++) {
  for (let b = 65; b <= 90; b++) {
    const code = String.fromCharCode(a, b);
    if (COUNTRIES[code] || NON_COUNTRY_CODES.has(code)) continue;
    const ruName = intlName(DN_RU, code);
    const enName = intlName(DN_EN, code);
    if (!ruName || !enName) continue;
    const aliases = AMBIGUOUS_CODES.has(code) ? [] : [normLoc(ruName), normLoc(enName)];
    INTL_COUNTRIES[code] = { ru: ruName, en: enName, aliases };
  }
}

// обратный индекс: нормализованный синоним → код страны (ручные синонимы приоритетнее Intl)
const ALIAS_TO_CODE = new Map<string, string>();
for (const [code, c] of [...Object.entries(COUNTRIES), ...Object.entries(INTL_COUNTRIES)]) {
  for (const a of c.aliases) if (!ALIAS_TO_CODE.has(a)) ALIAS_TO_CODE.set(a, code);
}

// Подпись страны по ISO-коду: «Германия / Germany» (один язык, если совпадают); неизвестный код — как есть.
export function countryLabel(code: string): string {
  const up = code.toUpperCase();
  const c = COUNTRIES[up] ?? INTL_COUNTRIES[up];
  if (!c) return up;
  return c.ru === c.en ? c.ru : `${c.ru} / ${c.en}`;
}

// Флаг-эмодзи по ISO-коду (региональные индикаторы); на системах без флагов покажутся две буквы.
export function flagEmoji(code: string): string {
  if (!/^[A-Za-z]{2}$/.test(code)) return "";
  return String.fromCodePoint(...[...code.toUpperCase()].map((ch) => 0x1f1e6 + ch.charCodeAt(0) - 65));
}

// код страны для нормализованного региона: полная строка → пара соседних слов → отдельное слово.
// Пары проверяем раньше слов, чтобы «hong kong»/«united kingdom» не распадались на неоднозначные слова.
function matchCode(norm: string): string | null {
  if (ALIAS_TO_CODE.has(norm)) return ALIAS_TO_CODE.get(norm) as string;
  const words = norm.split(" ").filter(Boolean);
  for (let i = 0; i < words.length - 1; i++) {
    const pair = `${words[i]} ${words[i + 1]}`;
    if (ALIAS_TO_CODE.has(pair)) return ALIAS_TO_CODE.get(pair) as string;
  }
  for (const w of words) {
    if (ALIAS_TO_CODE.has(w)) return ALIAS_TO_CODE.get(w) as string;
  }
  return null;
}

export interface CanonLoc {
  key: string; // код страны (AE, RU…) для известных; «x:<norm>» для нераспознанных (каждая отдельно)
  label: string; // подпись объединённой локации: «ОАЭ / UAE» (или один язык, если совпадают/неизвестно)
}

// Свести сырой регион к канонической локации. Нераспознанные не сливаем — оставляем как есть, чтобы не
// склеить разные места по ошибке.
export function canonicalLocation(region: string): CanonLoc {
  const norm = normLoc(region);
  const code = norm ? matchCode(norm) : null;
  if (code) return { key: code, label: countryLabel(code) };
  return { key: `x:${norm}`, label: region.trim() || tg("common.none") };
}
