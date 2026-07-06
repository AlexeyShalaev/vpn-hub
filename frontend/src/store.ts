import { create } from "zustand";
import { detectLang, type Lang } from "./lib/i18n";
import type { Me } from "./lib/types";

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
  const stored = localStorage.getItem("vpnhub.theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const savedTheme = initialTheme();
document.documentElement.setAttribute("data-theme", savedTheme);

const initialLang = detectLang();
document.documentElement.setAttribute("lang", initialLang);

let toastTimer: ReturnType<typeof setTimeout> | undefined;

export const useStore = create<State>((set) => ({
  me: null,
  setMe: (me) => set({ me, viewRole: me?.role ?? "member" }),
  theme: savedTheme,
  toggleTheme: () =>
    set((s) => {
      const theme = s.theme === "light" ? "dark" : "light";
      localStorage.setItem("vpnhub.theme", theme);
      document.documentElement.setAttribute("data-theme", theme);
      return { theme };
    }),
  lang: initialLang,
  setLang: (lang) =>
    set(() => {
      localStorage.setItem("vpnhub.lang", lang);
      document.documentElement.setAttribute("lang", lang);
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

export function copyText(text: string, toast: (m: string) => void, msg = "Скопировано") {
  navigator.clipboard?.writeText(text).catch(() => {});
  toast(msg);
}
