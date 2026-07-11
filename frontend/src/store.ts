import { create } from "zustand";
import { detectLang, type Lang, tg } from "./lib/i18n";
import type { Me } from "./lib/types";

// Импорт этого модуля возможен вне браузера (юнит-тесты в node, где нет DOM/Storage) —
// доступ к localStorage/document гейтим, чтобы модуль не падал на этапе загрузки.
const HAS_DOM = typeof document !== "undefined";
const HAS_LS = typeof localStorage !== "undefined";

interface State {
  me: Me | null;
  setMe: (me: Me | null) => void;
  theme: "light" | "dark";
  toggleTheme: () => void;
  lang: Lang;
  setLang: (lang: Lang) => void;
  viewRole: "owner" | "member";
  setViewRole: (r: "owner" | "member") => void;
  toastMsg: string | null;
  toast: (msg: string) => void;
}

// Если пользователь не выбирал тему явно (в localStorage нет vpnhub.theme) — берём
// системную из prefers-color-scheme; явный выбор всегда имеет приоритет.
function initialTheme(): "light" | "dark" {
  const stored = HAS_LS ? localStorage.getItem("vpnhub.theme") : null;
  if (stored === "light" || stored === "dark") return stored;
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

const savedTheme = initialTheme();
const initialLang = detectLang();
if (HAS_DOM) {
  document.documentElement.setAttribute("data-theme", savedTheme);
  document.documentElement.setAttribute("lang", initialLang);
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useStore = create<State>((set) => ({
  me: null,
  setMe: (me) => set({ me, viewRole: me?.role ?? "member" }),
  theme: savedTheme,
  toggleTheme: () =>
    set((s) => {
      const theme = s.theme === "light" ? "dark" : "light";
      if (HAS_LS) localStorage.setItem("vpnhub.theme", theme);
      if (HAS_DOM) document.documentElement.setAttribute("data-theme", theme);
      return { theme };
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

export function copyText(text: string, toast: (m: string) => void, msg = tg("common.copied")) {
  navigator.clipboard?.writeText(text).catch(() => {});
  toast(msg);
}
