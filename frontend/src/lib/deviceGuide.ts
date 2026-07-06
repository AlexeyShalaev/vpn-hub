// Справочные данные для экрана «Настрой устройство» (member): по каждой платформе —
// рекомендованное приложение, ссылка в стор/на сайт и пошаговая инструкция импорта.
//
// Почему ДАННЫЕ, а не JSX: тексты шагов ссылаются на i18n-ключи (setup.*), поэтому
// инструкции легко переводятся (ru+en синхронно) и правятся в одном месте, без
// раскопок по разметке. Реальные ссылки — только на официальные сторы/сайты приложений.
//
// Deep-link'и «Открыть в приложении» зависят от ФОРМАТА выданного конфига, а не от
// платформы: vpn:// (AmneziaVPN), vless:// (Streisand/Hiddify/v2rayNG), hy2://
// (Hysteria), ss:// (Outline). Сам URI и есть deep-link — ОС/приложение ловит схему.

import type { TKey } from "./i18n";
import type { VpnType } from "./types";

export type GuidePlatform = "ios" | "android" | "windows" | "mac" | "linux" | "router";

// Порядок вывода платформ на экране.
export const GUIDE_PLATFORMS: GuidePlatform[] = ["ios", "android", "windows", "mac", "linux", "router"];

export interface GuideApp {
  /** Отображаемое имя приложения (бренд, не переводится). */
  name: string;
  /** Ключ i18n с названием магазина/источника ("App Store", "Google Play", "сайт"…). */
  storeKey: TKey;
  /** Официальная ссылка на страницу загрузки. */
  url: string;
}

export interface PlatformGuide {
  platform: GuidePlatform;
  /** Ключ i18n с человекочитаемым названием платформы. */
  labelKey: TKey;
  /** Рекомендованное универсальное приложение (для vless/hy2 конфигов). */
  app: GuideApp;
  /** Ключи i18n с шагами импорта (по порядку). */
  stepKeys: TKey[];
}

// ── Рекомендованные приложения по платформам ─────────────────────────────────────
// Универсальные клиенты (vless://, hy2://): Streisand на Apple, Hiddify/v2rayNG на
// прочих — все с открытым кодом и поддержкой большинства схем. Реальные официальные ссылки.
const STREISAND: GuideApp = {
  name: "Streisand",
  storeKey: "setup.storeAppStore",
  url: "https://apps.apple.com/app/streisand/id6450534064",
};
const HIDDIFY_ANDROID: GuideApp = {
  name: "Hiddify",
  storeKey: "setup.storeGooglePlay",
  url: "https://play.google.com/store/apps/details?id=app.hiddify.com",
};
const HIDDIFY_DESKTOP: GuideApp = {
  name: "Hiddify",
  storeKey: "setup.storeSite",
  url: "https://hiddify.com/",
};

export const PLATFORM_GUIDES: PlatformGuide[] = [
  {
    platform: "ios",
    labelKey: "setup.platformIos",
    app: STREISAND,
    stepKeys: ["setup.stepInstall", "setup.stepGetConfig", "setup.stepImportUri", "setup.stepConnect"],
  },
  {
    platform: "android",
    labelKey: "setup.platformAndroid",
    app: HIDDIFY_ANDROID,
    stepKeys: ["setup.stepInstall", "setup.stepGetConfig", "setup.stepImportUri", "setup.stepConnect"],
  },
  {
    platform: "windows",
    labelKey: "setup.platformWindows",
    app: HIDDIFY_DESKTOP,
    stepKeys: ["setup.stepInstall", "setup.stepGetConfig", "setup.stepImportFile", "setup.stepConnect"],
  },
  {
    platform: "mac",
    labelKey: "setup.platformMac",
    app: STREISAND,
    stepKeys: ["setup.stepInstall", "setup.stepGetConfig", "setup.stepImportUri", "setup.stepConnect"],
  },
  {
    platform: "linux",
    labelKey: "setup.platformLinux",
    app: HIDDIFY_DESKTOP,
    stepKeys: ["setup.stepInstall", "setup.stepGetConfig", "setup.stepImportFile", "setup.stepConnect"],
  },
  {
    platform: "router",
    labelKey: "setup.platformRouter",
    app: {
      name: "AmneziaWG / WireGuard",
      storeKey: "setup.storeSite",
      url: "https://docs.amnezia.org/documentation/instructions/how_import_openwrt/",
    },
    stepKeys: ["setup.stepRouterFw", "setup.stepGetConfig", "setup.stepRouterImport", "setup.stepConnect"],
  },
];

// ── Приложения-вендоры (для vpn:// AmneziaVPN и ss:// Outline) ───────────────────
// Эти клиенты «родные» для конкретного формата и есть на всех платформах — ссылки на
// страницу загрузки, где перечислены все ОС.
export const AMNEZIA_APP: GuideApp = {
  name: "AmneziaVPN",
  storeKey: "setup.storeSite",
  url: "https://amnezia.org/en/downloads",
};
export const OUTLINE_APP: GuideApp = {
  name: "Outline",
  storeKey: "setup.storeSite",
  url: "https://getoutline.org/get-started/#step-3",
};

// ── Deep-link «Открыть в приложении» по ФОРМАТУ конфига ──────────────────────────
// Возвращает готовую ссылку-схему и приложение, которое её обработает. Для большинства
// форматов сам URI конфига И ЕСТЬ deep-link — ОС передаёт схему зарегистрированному
// приложению. Для Amnezia (vpn://) ссылку открывает AmneziaVPN, для Outline (ss://) —
// Outline. Если формат не распознан — возвращаем null (кнопку не показываем).
export interface DeepLink {
  /** Готовый URI для открытия (обычно = сам конфиг). */
  href: string;
  /** Приложение, которое зарегистрировано на эту схему. */
  app: GuideApp;
}

// Универсальный клиент для vless/hy2 — Hiddify (кросс-платформенный).
const HIDDIFY_ANY: GuideApp = HIDDIFY_DESKTOP;

/** Определяет deep-link «Открыть в приложении» по строке конфига. */
export function deepLinkFor(config: string, vpn: VpnType): DeepLink | null {
  const s = (config || "").trim();
  const scheme = s.slice(0, s.indexOf("://") + 3).toLowerCase();
  switch (scheme) {
    case "vpn://":
      return { href: s, app: AMNEZIA_APP };
    case "vless://":
    case "hy2://":
    case "hysteria2://":
      return { href: s, app: HIDDIFY_ANY };
    case "ss://":
      return { href: s, app: OUTLINE_APP };
    default:
      // .ovpn / .conf и прочие файловые форматы deep-link'а не имеют — импорт файлом.
      // vpn как vendor Amnezia без vpn:// (напр. awg-конфиг) — тоже открывает AmneziaVPN.
      if (vpn === "amnezia" && s.startsWith("vpn://")) return { href: s, app: AMNEZIA_APP };
      return null;
  }
}
