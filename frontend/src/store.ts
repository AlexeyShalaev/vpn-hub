import { create } from "zustand";
import { detectLang, type Lang, tg } from "./lib/i18n";
import type { Me } from "./lib/types";

// Импорт этого модуля возможен вне браузера (юнит-тесты в node, где нет DOM/Storage) —
// доступ к localStorage/document гейтим, чтобы модуль не падал на этапе загрузки.
const HAS_DOM = typeof document !== "undefined";
const HAS_LS = typeof localStorage !== "undefined";

// Предпочтение темы: «системная» (следует за ОС), либо явно светлая/тёмная.
export type ThemePref = "system" | "light" | "dark";

interface State {
  me: Me | null;
  setMe: (me: Me | null) => void;
  themePref: ThemePref; // что выбрал пользователь
  theme: "light" | "dark"; // эффективная тема (для компонентов/графиков)
  setThemePref: (pref: ThemePref) => void;
  lang: Lang;
  setLang: (lang: Lang) => void;
  viewRole: "owner" | "member";
  setViewRole: (r: "owner" | "member") => void;
  toastMsg: string | null;
  toast: (msg: string) => void;
}

function systemTheme(): "light" | "dark" {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

// Сохранённое предпочтение (vpnhub.theme): system | light | dark. По умолчанию — системная.
function initialThemePref(): ThemePref {
  const stored = HAS_LS ? localStorage.getItem("vpnhub.theme") : null;
  if (stored === "system" || stored === "light" || stored === "dark") return stored;
  return "system";
}

// Эффективная тема из предпочтения: «системная» → смотрим prefers-color-scheme.
function effectiveTheme(pref: ThemePref): "light" | "dark" {
  return pref === "system" ? systemTheme() : pref;
}

const savedThemePref = initialThemePref();
const savedTheme = effectiveTheme(savedThemePref);
const initialLang = detectLang();
if (HAS_DOM) {
  document.documentElement.setAttribute("data-theme", savedTheme);
  document.documentElement.setAttribute("lang", initialLang);
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useStore = create<State>((set) => ({
  me: null,
  setMe: (me) => set({ me, viewRole: me?.role ?? "member" }),
  themePref: savedThemePref,
  theme: savedTheme,
  setThemePref: (pref) =>
    set(() => {
      if (HAS_LS) localStorage.setItem("vpnhub.theme", pref);
      const theme = effectiveTheme(pref);
      if (HAS_DOM) document.documentElement.setAttribute("data-theme", theme);
      return { themePref: pref, theme };
    }),
  lang: initialLang,
  setLang: (lang) =>
    set(() => {
      if (HAS_LS) localStorage.setItem("vpnhub.lang", lang);
      if (HAS_DOM) document.documentElement.setAttribute("lang", lang);
      return { lang };
    }),
  viewRole: "member",
  setViewRole: (viewRole) => set({ viewRole }),
  toastMsg: null,
  toast: (toastMsg) => {
    set({ toastMsg });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => set({ toastMsg: null }), 2000);
  },
}));

// Когда выбрана «системная» тема — следим за сменой оформления ОС в реальном времени.
if (typeof window !== "undefined" && window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (useStore.getState().themePref !== "system") return;
    const theme = systemTheme();
    if (HAS_DOM) document.documentElement.setAttribute("data-theme", theme);
    useStore.setState({ theme });
  });
}

export function copyText(text: string, toast: (m: string) => void, msg = tg("common.copied")) {
  navigator.clipboard?.writeText(text).catch(() => {});
  toast(msg);
}
