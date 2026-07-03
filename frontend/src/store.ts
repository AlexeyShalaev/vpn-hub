import { create } from "zustand";
import type { Me } from "./lib/types";

interface State {
  me: Me | null;
  setMe: (me: Me | null) => void;
  theme: "light" | "dark";
  toggleTheme: () => void;
  viewRole: "owner" | "member";
  setViewRole: (r: "owner" | "member") => void;
  toastMsg: string | null;
  toast: (msg: string) => void;
}

const savedTheme = (localStorage.getItem("vpnhub.theme") as "light" | "dark") || "light";
document.documentElement.setAttribute("data-theme", savedTheme);

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
