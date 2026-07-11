import { create } from "zustand";
import type { TKey } from "./lib/i18n";

// метаданные пунктов навигации (иконка + i18n-ключ). Общий источник для сайдбара, нижней навигации
// и лаунчера на «Главной» — чтобы не дублировать иконки/подписи по разным файлам.
export const NAV_META: Record<string, { labelKey: TKey; icon: string }> = {
  home: { labelKey: "nav.home", icon: "home" },
  servers: { labelKey: "nav.servers", icon: "servers" },
  monitoring: { labelKey: "nav.monitoring", icon: "monitoring" },
  finance: { labelKey: "nav.finance", icon: "finance" },
  groups: { labelKey: "nav.groups", icon: "groups" },
  access: { labelKey: "nav.access", icon: "access" },
  available: { labelKey: "nav.available", icon: "available" },
  devices: { labelKey: "nav.devices", icon: "devices" },
  setup: { labelKey: "nav.setup", icon: "file" },
  events: { labelKey: "nav.events", icon: "events" },
  users: { labelKey: "nav.users", icon: "users" },
  system: { labelKey: "nav.system", icon: "system" },
  profile: { labelKey: "nav.profile", icon: "profile" },
};

export type Screen =
  | "home"
  | "servers"
  | "server"
  | "serverForm"
  | "catalog"
  | "monitoring"
  | "finance"
  | "groups"
  | "group"
  | "access"
  | "available"
  | "devices"
  | "setup"
  | "events"
  | "users"
  | "system"
  | "profile"
  | "join";

type Params = Record<string, string | undefined>;

// разделы страницы сервера, адресуемые в URL: /servers/{id}/{tab} (connection — без суффикса)
const SERVER_TABS = new Set(["connection", "protocols", "monitoring", "access"]);

interface NavState {
  screen: Screen;
  params: Params;
  go: (screen: Screen, params?: Params) => void;
}

// --- экран <-> URL ------------------------------------------------------------

function screenToPath(screen: Screen, params: Params): string {
  switch (screen) {
    case "home":
      return "/home";
    case "servers":
      return "/servers";
    case "server": {
      const tab = params.tab && params.tab !== "connection" && SERVER_TABS.has(params.tab) ? `/${params.tab}` : "";
      return `/servers/${params.serverId ?? ""}${tab}`;
    }
    case "serverForm":
      if (params.serverId) return `/servers/${params.serverId}/edit`;
      return params.provider ? `/servers/new?provider=${encodeURIComponent(params.provider)}` : "/servers/new";
    case "catalog":
      return "/catalog";
    case "monitoring":
      return "/monitoring";
    case "finance":
      return "/finance";
    case "groups":
      return "/groups";
    case "group":
      return `/groups/${params.groupId ?? ""}`;
    case "access":
      return params.groupId ? `/access/${params.groupId}` : "/access";
    case "available":
      return "/available";
    case "devices":
      return "/devices";
    case "setup":
      return "/setup";
    case "events":
      return "/events";
    case "users":
      return "/users";
    case "system":
      return "/system";
    case "profile":
      return "/profile";
    case "join":
      return `/join/${params.token ?? ""}`;
    default:
      return "/";
  }
}

function pathToState(pathname: string, search: string): { screen: Screen; params: Params } {
  const seg = pathname
    .replace(/^\/+|\/+$/g, "")
    .split("/")
    .filter(Boolean);
  const sp = new URLSearchParams(search);
  if (seg.length === 0) return { screen: "available", params: {} };
  const [a, b, c] = seg;
  switch (a) {
    case "home":
      return { screen: "home", params: {} };
    case "servers":
      if (!b) return { screen: "servers", params: {} };
      if (b === "new") return { screen: "serverForm", params: { provider: sp.get("provider") ?? undefined } };
      if (c === "edit") return { screen: "serverForm", params: { serverId: b } };
      return { screen: "server", params: { serverId: b, ...(c && SERVER_TABS.has(c) ? { tab: c } : {}) } };
    case "catalog":
      return { screen: "catalog", params: {} };
    case "monitoring":
      return { screen: "monitoring", params: {} };
    case "finance":
      return { screen: "finance", params: {} };
    case "groups":
      return b ? { screen: "group", params: { groupId: b } } : { screen: "groups", params: {} };
    case "access":
      return { screen: "access", params: b ? { groupId: b } : {} };
    case "available":
      return { screen: "available", params: {} };
    case "devices":
      return { screen: "devices", params: {} };
    case "setup":
      return { screen: "setup", params: {} };
    case "events":
      return { screen: "events", params: {} };
    case "users":
      return { screen: "users", params: {} };
    case "system":
      return { screen: "system", params: {} };
    case "profile":
      return { screen: "profile", params: {} };
    case "join":
      return { screen: "join", params: { token: b ?? "" } };
    default:
      return { screen: "available", params: {} };
  }
}

const initial =
  typeof window !== "undefined"
    ? pathToState(window.location.pathname, window.location.search)
    : { screen: "available" as Screen, params: {} as Params };

export const useNav = create<NavState>((set) => ({
  screen: initial.screen,
  params: initial.params,
  go: (screen, params = {}) => {
    const path = screenToPath(screen, params);
    if (typeof window !== "undefined" && path !== window.location.pathname + window.location.search) {
      window.history.pushState({}, "", path);
    }
    set({ screen, params });
  },
}));

// синхронизация с кнопками назад/вперёд браузера
if (typeof window !== "undefined") {
  window.addEventListener("popstate", () => {
    const s = pathToState(window.location.pathname, window.location.search);
    useNav.setState({ screen: s.screen, params: s.params });
  });
}
