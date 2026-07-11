// «Умное автозаполнение»: парсинг вставленного письма провайдера с реквизитами
// сервера. Работает целиком на клиенте — вставленный текст (включая пароль)
// никуда не отправляется, заполняются только поля формы.
//
// Устройство: generic-парсер по меткам («IP-адрес:», «Пользователь:», …)
// покрывает типовые письма BILLmanager/WHMCS/SolusVM на русском и английском
// (в т.ч. шаблон «vdsopen», по которому шлют FirstByte и UFO Hosting), а также
// копии реквизитов из панелей (Serverspace, AHost), где метки без двоеточий и
// значение на следующей строке. Профили провайдеров добавляют специфику:
// сигнатуру для автоопределения и извлечение локации из названия тарифа
// (KVM-SSD-1-PAR → Париж, Naos[RS] → Сербия).

import { type TKey, tg } from "./i18n";

export interface ParsedServerInfo {
  providerId?: string;
  ip?: string;
  hostname?: string;
  sshUser?: string;
  password?: string;
  sshPort?: string;
  location?: string;
  tariff?: string;
}

type Field = "ip" | "hostname" | "user" | "password" | "port" | "location" | "tariff";

// ---------- метки полей (generic, RU + EN) ----------
// Регэкспы матчатся на часть строки ДО двоеточия/тире (label) без учёта
// регистра; скобочные пояснения в метке («Логин (обычно root)») срезаются.
const LABELS: Record<Field, RegExp[]> = {
  ip: [
    /^ip(v[46])?([\s-]*(адрес|address))?([\s-]*(сервера|server))?$/i,
    /^(основной|главный|внешний|main|primary|dedicated|server|external)[\s-]*ip([\s-]*(адрес|address))?$/i,
    /^(адрес|address)[\s-]*(сервера|server)$/i,
  ],
  hostname: [
    /^(доменное\s+имя|domain\s+name|hostname|host\s*name|server\s*(host)?name|имя\s+(хоста|сервера)|fqdn)$/i,
    /^(домен|host)$/i,
  ],
  user: [
    /^(пользователь|имя\s+пользователя|логин|username|login|user)$/i,
    /^(ssh|root)[\s-]*(пользователь|user|login|логин)$/i,
    /^(пользователь|логин|login|user(name)?)\s*(ssh|root)$/i,
    /^(логин|login|пользователь|username|user)\s+(для|for)\s+linux$/i,
  ],
  password: [
    /^(пароль|password|passwd|pass)$/i,
    /^(root|ssh|администратора?|admin)[\s-]*(пароль|password)$/i,
    /^(пароль|password)[\s-]*(root|ssh|administrator|администратора?|суперпользователя)$/i,
    /^(пароль|password)\s+(от\s+|для\s+)?(пользователя|user)(\s+\S+)?$/i,
  ],
  port: [/^(ssh[\s-]*)?(порт|port)(\s*(ssh|подключения))?$/i],
  location: [
    /^(локация|location|дата[\s-]*центр|data[\s-]*center|датацентр|дц|цод|регион|region|страна|country|местоположение|размещение)$/i,
  ],
  tariff: [/^(тариф(ный\s+план)?|тарифный\s+план|plan|package|product\/?service|service|услуга)$/i],
};

// Метки/заголовки, рядом с которыми логин и пароль относятся к панели
// управления или биллингу, а не к SSH-доступу на сервер.
const PANEL_CONTEXT =
  /панел|panel|биллинг|billing|ispmanager|vmmanager|личн\w+\s+кабинет|control|аккаунт|account|ftp|vnc/i;
// Заголовки секций про сам сервер — сбрасывают «панельный» контекст.
const SERVER_CONTEXT = /ssh|root|сервер|server/i;

// ---------- валидаторы значений ----------
const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const IPV6 = /^[0-9a-f]{0,4}(:[0-9a-f]{0,4}){2,7}$/i;
const HOSTNAME = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/i;

function isIPv4(s: string): boolean {
  const m = IPV4.exec(s);
  return !!m && m.slice(1).every((o) => Number(o) <= 255);
}

const VALIDATORS: Record<Field, (v: string) => boolean> = {
  ip: (v) => isIPv4(v) || IPV6.test(v),
  hostname: (v) => HOSTNAME.test(v) && !isIPv4(v),
  user: (v) => /^[a-z_][\w.@-]{0,63}$/i.test(v),
  password: (v) => v.length >= 3 && !/\s/.test(v),
  port: (v) => /^\d{1,5}$/.test(v) && Number(v) >= 1 && Number(v) <= 65535,
  location: (v) => v.length >= 2 && v.length <= 64 && !/https?:/i.test(v),
  tariff: (v) => v.length >= 2 && v.length <= 64,
};

// ---------- локация из названия тарифа ----------
// Коды дата-центров в суффиксе тарифа (FirstByte: KVM-SSD-1-PAR, EU-KVM-SSD-2-FIN).
// Значения — ключи i18n (city.*), переводятся в locationFromTariff() при обращении.
const DC_CODES: Record<string, TKey> = {
  MSK: "city.moscow",
  SPB: "city.saintPetersburg",
  KZN: "city.kazan",
  EKB: "city.yekaterinburg",
  NSK: "city.novosibirsk",
  PAR: "city.paris",
  PARS: "city.paris",
  AMS: "city.amsterdam",
  FRA: "city.frankfurt",
  FIN: "city.helsinki",
  HEL: "city.helsinki",
  SOF: "city.sofia",
  MAD: "city.madrid",
  WAW: "city.warsaw",
  LON: "city.london",
  VIE: "city.vienna",
  PRG: "city.prague",
  STO: "city.stockholm",
  MIL: "city.milan",
  IST: "city.istanbul",
  TLV: "city.telAviv",
  ALM: "city.almaty",
  NYC: "city.newYork",
  LAX: "city.losAngeles",
  TOR: "city.toronto",
  HKG: "city.hongKong",
  SG: "city.singapore",
  SGP: "city.singapore",
  TK: "city.tokyo",
  TOK: "city.tokyo",
  DB: "city.dubai",
  DXB: "city.dubai",
};

// Коды стран в квадратных скобках (UFO Hosting и родственные: Naos[RS], Haedus[NL]).
// Значения — ключи i18n (city.*), переводятся в locationFromTariff() при обращении.
const COUNTRY_CODES: Record<string, TKey> = {
  RU: "city.russia",
  BY: "city.belarus",
  KZ: "city.kazakhstan",
  NL: "city.netherlands",
  DE: "city.germany",
  FR: "city.france",
  FI: "city.finland",
  RS: "city.serbia",
  US: "city.usa",
  GB: "city.unitedKingdom",
  UK: "city.unitedKingdom",
  TR: "city.turkey",
  PL: "city.poland",
  MD: "city.moldova",
  LV: "city.latvia",
  LT: "city.lithuania",
  EE: "city.estonia",
  UA: "city.ukraine",
  AT: "city.austria",
  CH: "city.switzerland",
  SE: "city.sweden",
  NO: "city.norway",
  ES: "city.spain",
  IT: "city.italy",
  CZ: "city.czechia",
  SK: "city.slovakia",
  BG: "city.bulgaria",
  RO: "city.romania",
  GR: "city.greece",
  PT: "city.portugal",
  HU: "city.hungary",
  IL: "city.israel",
  AE: "city.uae",
  HK: "city.hongKong",
  SG: "city.singapore",
  JP: "city.japan",
  IN: "city.india",
  BR: "city.brazil",
  CA: "city.canada",
  MX: "city.mexico",
  AM: "city.armenia",
  GE: "city.georgia",
  AZ: "city.azerbaijan",
  UZ: "city.uzbekistan",
  KG: "city.kyrgyzstan",
};

function locationFromTariff(tariff: string): string | undefined {
  const t = tariff.trim().toUpperCase();
  // Naos[RS] → Сербия
  const bracket = /\[([A-Z]{2})\]/.exec(t);
  if (bracket && COUNTRY_CODES[bracket[1]]) return tg(COUNTRY_CODES[bracket[1]]);
  // KVM-SSD-1-PAR, PARs-2 → Париж
  const suffix = /-([A-Z]{2,4})S?\d*$/.exec(t);
  if (suffix && DC_CODES[suffix[1]]) return tg(DC_CODES[suffix[1]]);
  const prefix = /^([A-Z]{2,4})-/.exec(t);
  if (prefix && DC_CODES[prefix[1]]) return tg(DC_CODES[prefix[1]]);
  if (prefix && COUNTRY_CODES[prefix[1]]) return tg(COUNTRY_CODES[prefix[1]]);
  return undefined;
}

// ---------- профили провайдеров ----------
interface ProviderProfile {
  id: string;
  signature: RegExp;
  labels?: Partial<Record<Field, RegExp[]>>;
}

const PROVIDERS: ProviderProfile[] = [
  { id: "firstbyte", signature: /firstbyte/i },
  { id: "ufo", signature: /ufo[\s.-]?host/i },
  { id: "ishosting", signature: /is[\s*.-]?hosting/i },
  { id: "ahost", signature: /\bahost\b/i },
  { id: "serverspace", signature: /serverspace/i },
];

// ---------- разбор ----------
interface Candidate {
  value: string;
  score: number;
  order: number;
}

function normalize(text: string): string[] {
  return text
    .replace(/ /g, " ")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((l) => l.replace(/^[\s•*·—-]+\s*/, "").trim());
}

// Строка вида «Метка: значение» / «Метка — значение» → [метка, значение].
// Значение может быть пустым (тогда смотрим следующую строку).
function splitLine(line: string): [string, string] | null {
  const colon = line.indexOf(":");
  if (colon > 0 && colon <= 48) {
    const value = line.slice(colon + 1).trim();
    // «Панель: https://…» — не считаем "https" меткой.
    if (!value.startsWith("//")) return [line.slice(0, colon).trim(), value];
  }
  const dash = /^(.{1,48}?)\s+[—–-]\s+(.*)$/.exec(line);
  if (dash) return [dash[1].trim(), dash[2].trim()];
  return null;
}

function matchField(label: string, labels: Record<Field, RegExp[]>): Field | null {
  // «Логин (обычно root)» → «Логин»; лишние пробелы схлопываем.
  const clean = label
    .replace(/\s*\([^)]*\)\s*$/, "")
    .replace(/\s+/g, " ")
    .trim();
  if (!clean) return null;
  for (const field of Object.keys(labels) as Field[]) {
    if (labels[field].some((re) => re.test(clean))) return field;
  }
  return null;
}

// «s3cret (change for security reasons…)» → «s3cret»; кавычки и хвостовая
// пунктуация срезаются.
function cleanValue(raw: string, field: Field): string {
  let v = raw.trim();
  if (field === "password" || field === "user") v = v.replace(/\s+\([^)]*\)\s*$/, "");
  return v.replace(/^["'«]|["'»,.;]+$/g, "").trim();
}

/**
 * Разбирает вставленный текст письма провайдера (целиком или фрагмент).
 * @param selectedProviderId — id провайдера, уже выбранного в форме (если есть)
 */
export function parseServerInfo(text: string, selectedProviderId?: string): ParsedServerInfo {
  const lines = normalize(text);
  const result: ParsedServerInfo = {};

  // Определяем провайдера по сигнатуре в тексте.
  const detected = PROVIDERS.find((p) => p.signature.test(text));
  if (detected) result.providerId = detected.id;
  const profile = detected ?? PROVIDERS.find((p) => p.id === selectedProviderId);

  // Общие + провайдерские метки.
  const labels: Record<Field, RegExp[]> = { ...LABELS };
  if (profile?.labels) {
    for (const f of Object.keys(profile.labels) as Field[]) {
      labels[f] = [...(profile.labels[f] ?? []), ...LABELS[f]];
    }
  }

  const candidates: Partial<Record<Field, Candidate[]>> = {};
  let panelSection = false;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line) continue;

    const split = splitLine(line);
    // Метка без двоеточия на отдельной строке (копия из панели провайдера:
    // «Логин» / «root» на соседних строках).
    let label: string;
    let inlineValue: string;
    if (split) [label, inlineValue] = split;
    else [label, inlineValue] = [line, ""];

    const field = matchField(label, labels);
    if (!field || (!split && line.length > 24)) {
      // Не поле — возможно, заголовок секции («Доступ в панель управления»,
      // «VMmanager 6 — внешняя панель», «Информация о сервере»).
      if (PANEL_CONTEXT.test(line)) panelSection = true;
      else if (SERVER_CONTEXT.test(line)) panelSection = false;
      continue;
    }

    // Значение — после двоеточия или на следующей непустой строке.
    let value = inlineValue;
    if (!value) {
      for (let j = i + 1; j < lines.length && j <= i + 2; j++) {
        if (lines[j]) {
          // Следующая строка не должна сама быть меткой («Пароль:», «Логин»).
          const next = splitLine(lines[j]);
          const nextLabel = next ? next[0] : lines[j];
          if (!matchField(nextLabel, labels)) value = lines[j];
          break;
        }
      }
    }
    value = cleanValue(value, field);
    if (!value || !VALIDATORS[field](value)) continue;

    let score = 1;
    // Логин/пароль от панели/биллинга — не то, что нужно для SSH.
    if (field === "user" || field === "password") {
      if (/root|ssh|сервер|server/i.test(label)) score += 2;
      if (panelSection || PANEL_CONTEXT.test(label)) score -= 2;
    }
    const list = candidates[field] ?? [];
    candidates[field] = list;
    list.push({ value, score, order: i });
  }

  const pick = (field: Field): string | undefined => {
    const list = candidates[field];
    if (!list?.length) return undefined;
    list.sort((a, b) => b.score - a.score || a.order - b.order);
    return list[0].value;
  };

  result.hostname = pick("hostname");
  result.sshUser = pick("user");
  result.password = pick("password");
  result.sshPort = pick("port");
  result.location = pick("location");
  result.tariff = pick("tariff");

  // IP: сначала по метке, иначе — первый валидный IPv4 в тексте.
  result.ip = pick("ip");
  if (!result.ip) {
    const m = text.match(/\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/g);
    result.ip = m?.find(isIPv4);
  }

  // Локация из названия тарифа (KVM-SSD-1-PAR → Париж, Naos[RS] → Сербия).
  if (!result.location && result.tariff) result.location = locationFromTariff(result.tariff);

  // Убираем undefined-ключи, чтобы Object.keys(result) был списком найденного.
  for (const k of Object.keys(result) as (keyof ParsedServerInfo)[]) {
    if (result[k] === undefined) delete result[k];
  }
  return result;
}

/** Есть ли в результате хоть что-то полезное для формы. */
export function hasUsefulInfo(r: ParsedServerInfo): boolean {
  return !!(r.ip || r.hostname || r.sshUser || r.password || r.sshPort || r.location);
}
