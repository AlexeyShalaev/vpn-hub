import { create } from "zustand";

export type Screen =
  | "home"
  | "servers"
  | "server"
  | "serverForm"
  | "catalog"
  | "groups"
  | "group"
  | "access"
  | "available"
  | "devices"
  | "events"
  | "users"
  | "system"
  | "profile"
  | "join";

type Params = Record<string, string | undefined>;

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
    case "server":
      return `/servers/${params.serverId ?? ""}`;
    case "serverForm":
      if (params.serverId) return `/servers/${params.serverId}/edit`;
      return params.provider ? `/servers/new?provider=${encodeURIComponent(params.provider)}` : "/servers/new";
    case "catalog":
      return "/catalog";
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
      return { screen: "server", params: { serverId: b } };
    case "catalog":
      return { screen: "catalog", params: {} };
    case "groups":
      return b ? { screen: "group", params: { groupId: b } } : { screen: "groups", params: {} };
    case "access":
      return { screen: "access", params: b ? { groupId: b } : {} };
    case "available":
      return { screen: "available", params: {} };
    case "devices":
      return { screen: "devices", params: {} };
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
