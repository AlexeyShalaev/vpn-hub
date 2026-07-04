// Доменные типы (форма ответов бэкенда, camelCase как в прототипе).

export type VpnType = "amnezia" | "openvpn" | "outline" | "hysteria2";

export interface Me {
  id: string;
  kind: "admin" | "user";
  name: string;
  phone: string;
  isAdmin: boolean;
  role: "owner" | "member";
}

export interface Vpn {
  type: VpnType;
  installed: boolean;
  running: boolean;
  port: string;
}

export type ProtocolState = "absent" | "installing" | "installed" | "external" | "error";

export interface Remediation {
  kind: "auto" | "manual" | "none";
  title: string;
  explanation: string;
  canAutoFix: boolean;
  fixLabel: string | null;
  manualSteps: string[];
}

export interface Protocol {
  vendor: VpnType;
  proto: string; // awg | awg_legacy | xray | openvpn
  container: string;
  port: string;
  state: ProtocolState;
  installed: boolean;
  running: boolean;
  error: string | null;
  errorCode?: string | null;
  remediation?: Remediation | null;
  externalClients: number;
}

export interface Server {
  id: string;
  name: string;
  provider: string;
  ip: string;
  sshUser: string;
  sshPort: string;
  auth: "key" | "password";
  secret: string;
  location: string;
  status: "online" | "offline" | "unknown";
  latency: string | null;
  lastCheck: string | null;
  vpns: Vpn[];
  protocols: Protocol[];
}

export interface Pool {
  id: string;
  name: string;
  serverIds: string[];
}

export interface Member {
  id: string;
  name: string;
  role: "admin" | "member";
  status: "active" | "invited";
  phone?: string;
}

export interface Session {
  id: string;
  ip: string;
  device: string;
  userAgent: string;
  createdAt: string;
  lastSeen: string | null;
  current: boolean;
}

export interface InvitePeek {
  id: string;
  name: string;
  ownerName: string;
  memberCount: number;
}

export interface Group {
  id: string;
  name: string;
  token: string;
  members: Member[];
  access: { pools: string[]; servers: Record<string, VpnType[]> };
}

export interface DeviceConfig {
  serverId: string;
  type: VpnType;
  proto: string | null;
}

export interface Device {
  id: string;
  name: string;
  platform: "ios" | "android" | "mac" | "windows" | "linux" | "router";
  configs: DeviceConfig[];
}

export interface AvailableServer {
  id: string;
  name: string;
  provider: string;
  location: string;
  status: Server["status"];
  latency: string | null;
  lastCheck: string | null;
  fromGroup: string;
  vpns: VpnType[];
}

export interface Provider {
  id: string;
  name: string;
  url: string;
  blurb: string;
  tags: string[];
}

export interface AdminUser {
  id: string;
  phone: string;
  name: string;
  status: "pending" | "active" | "blocked";
  createdAt: string;
  isAdmin: boolean;
}

export interface ConfigFormat {
  id: string;
  label: string;
  sub?: string;
  text: string;
  filename: string;
  qr: string;
}

export interface ConfigResult {
  type: VpnType;
  proto: string;
  filename: string;
  text: string;
  uri: string;
  hint: string;
  clients: { name: string; store: string; url: string; note?: string; wgOnly?: boolean }[];
  protos: string[];
  serverId: string;
  formats: ConfigFormat[];
}

export interface ServerClientConfig {
  id: string;
  device: string;
  platform: string;
  proto: string;
  vpnType: string;
  clientName: string;
  status: string;
}

export interface ServerAccessUser {
  userId: string;
  name: string;
  phone: string;
  hasAccess: boolean;
  groups: string[];
  configs: ServerClientConfig[];
}

export interface ServerAccess {
  pools: { id: string; name: string }[];
  groups: { id: string; name: string; via: string; vpns: string[] }[];
  users: ServerAccessUser[];
}

export interface VpnAdvancedProtocol {
  proto: string;
  label: string;
  container: string;
  port: string;
  state: string;
  installed: boolean;
  running: boolean;
  error: string | null;
  externalClients: number;
  params: Record<string, string> | null;
  keys: Record<string, string>;
}

export interface VpnAdvancedClient {
  id: string;
  clientName: string;
  user: string;
  device: string;
  proto: string;
  clientIp: string;
  clientId: string;
  status: string;
}

export interface VpnAdvanced {
  vendor: string;
  protocols: VpnAdvancedProtocol[];
  clients: VpnAdvancedClient[];
}

export interface VpnExternal {
  external: { proto: string; label: string; clients: { id: string; name: string }[] }[];
}

export interface SystemInfo {
  version: string;
  latest: string;
  updateAvailable: boolean;
  channel: string;
  image: string;
  edition: string;
  built: string;
  uptime: string;
  baseUrl: string;
  masterKeyInsecure: boolean;
  masterKeyFromEnv: boolean;
  updateSupported: boolean;
  db: { engine: string; host: string; name: string; status: string; latency: string | null };
  lastBackup: string;
  backupFrequency: string; // off|daily|weekly|monthly
  masterKeySet: boolean;
  backups: { id: string; at: string; size: string; kind: string }[];
  releases: { v: string; date: string; notes: string[] }[];
}

export interface UpdateCheck {
  available: boolean;
  current?: string;
  latest: string;
  checked?: boolean;
  reason?: string;
  releases?: { v: string; date: string; notes: string[] }[];
}

export interface UpgradeResult {
  ok: boolean;
  manual?: boolean;
  message?: string;
  instructions?: string[];
  code?: number;
  log?: string;
}

export const VPN_LABEL: Record<VpnType, string> = {
  amnezia: "Amnezia",
  openvpn: "OpenVPN",
  outline: "Outline",
  hysteria2: "Hysteria2",
};
export const VPN_DESC: Record<VpnType, string> = {
  amnezia: "Маскируется под обычный трафик — лучший против блокировок.",
  openvpn: "Классика, максимальная совместимость с устройствами.",
  outline: "Один ключ, проще всего для новичков.",
  hysteria2: "Быстрый QUIC-протокол с обфускацией — хорош на нестабильных и мобильных сетях.",
};
export const PROTO_LABEL: Record<string, string> = {
  awg: "AmneziaWG",
  awg_legacy: "AmneziaWG Legacy",
  xray: "Xray",
  xray_xhttp: "Xray XHTTP",
  openvpn: "OpenVPN",
  hysteria2: "Hysteria2",
};
export const PROTO_STATE_LABEL: Record<ProtocolState, string> = {
  absent: "нет",
  installing: "устанавливается…",
  installed: "готов",
  external: "внешний",
  error: "ошибка",
};
export const PLATFORM_LABEL: Record<Device["platform"], string> = {
  ios: "iPhone / iPad",
  android: "Android",
  mac: "macOS",
  windows: "Windows",
  linux: "Linux",
  router: "Роутер",
};
