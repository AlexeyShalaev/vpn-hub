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
  imageVersion?: string | null; // версия бинарника в контейнере (xray/hysteria2), читает sync
  latestVersion?: string | null; // эталон релиза панели (null — детект не поддержан)
  updateAvailable?: boolean; // эталон строго новее того, что на сервере
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
  bandwidthQuota: number | null; // квота трафика тарифа за период (байт), null = безлимит
  billingDay: number | null; // день сброса периода (1..31), null → 1-е число
  vpns: Vpn[];
  protocols: Protocol[];
}

export interface ServerPrice {
  amount: number; // цена в единицах валюты за период
  currency: string; // RUB | USD | EUR | ...
  period: "minute" | "day" | "month";
  anchorDay: number | null; // день обновления (для month)
  since: number; // epoch начала действия текущей цены
}

export interface CostByCurrency {
  currency: string;
  amount: number;
}

export interface ServerCost {
  serverId: string;
  start: number;
  end: number;
  price: ServerPrice | null;
  byCurrency: CostByCurrency[]; // accrual-расход за период, раздельно по валютам
}

export interface CostReport {
  start: number;
  end: number;
  totals: CostByCurrency[];
  servers: { serverId: string; name: string; price: ServerPrice | null; byCurrency: CostByCurrency[] }[];
}

export interface ServerUsage {
  periodStart: number; // epoch начала текущего периода
  quota: number | null; // квота сервера (байт), null = безлимит
  serverUsed: number; // суммарно байт по серверу за период
  users: { userId: string; name: string; used: number; limit: number | null }[];
}

export interface ChainLink {
  id: string;
  entryServerId: string;
  exitServerId: string;
  exitServerName: string;
  proto: string; // xray
  state: "absent" | "linked" | "error";
  error: string | null;
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
  maxDevices: number | null; // персональный override лимита устройств; null = наследовать
  maxBytes: number | null; // персональный override лимита трафика (байт/период); null = наследовать
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
  maxDevices: number | null; // override лимита устройств для участников; null = глобальный дефолт
  maxBytes: number | null; // override лимита трафика участников (байт/период); null = глобальный дефолт
  members: Member[];
  access: { pools: string[]; servers: Record<string, VpnType[]> };
}

export interface DeviceLimit {
  used: number;
  limit: number;
}

export interface MyUsage {
  serverId: string;
  serverName: string;
  used: number; // байт за период (rx+tx)
  limit: number | null; // байт-лимит per сервер, null = без лимита
  suspended: boolean; // доступ приостановлен из-за лимита
  periodStart: number;
}

export interface DeviceConfig {
  serverId: string;
  type: VpnType;
  proto: string | null;
  status?: string; // active | revoked
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

export interface AuditEvent {
  id: string;
  at: string; // отформатированная дата (дд.мм.гггг чч:мм)
  rel: string | null; // относительное время («5 мин назад»)
  actorKind: "admin" | "user" | "system";
  actorId: string | null;
  actorName: string;
  type: string; // стабильный код (auth.login, group.join, config.download, access.revoke, …)
  label: string; // русская подпись типа события
  targetKind: string | null;
  targetId: string | null;
  ownerUserId: string | null;
  meta: Record<string, unknown>;
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
  bundle?: string[]; // amnezia-протоколы, выдаваемые одним vpn:// (awg/awg_legacy/xray)
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
  maxClients: number | null; // мягкий лимит числа конфигов (null = без лимита)
  usedClients: number; // занято: активные конфиги + внешние клиенты
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
  updateMode: "command" | "webhook" | "k8s" | "manual";
  updateHint?: string; // почему кнопка недоступна (напр. в k8s не применён RBAC)
  db: { engine: string; host: string; name: string; status: string; latency: string | null };
  lastBackup: string;
  backupFrequency: string; // off|daily|weekly|monthly
  masterKeySet: boolean;
  defaultDevicesPerUser: number; // глобальный дефолт лимита устройств на пользователя
  defaultUserBytes: number | null; // глобальный дефолт лимита трафика на пользователя (байт/период), null = без лимита
  backups: { id: string; at: string; size: string; kind: string }[];
  releases: { v: string; date: string; notes: string[] }[];
}

// per-server мониторинг ресурсов хоста (owner): один сэмпл = один monitor-тик по SSH
export interface ServerMetricSample {
  at: number; // epoch seconds
  cpuPct: number | null; // 0..100
  load1: number | null; // 1-минутный load average
  memUsed: number | null; // байт
  memTotal: number | null; // байт
  diskUsed: number | null; // байт (/)
  diskTotal: number | null; // байт (/)
  tcpEstab: number | null; // TCP established
  uptimeS: number | null; // аптайм хоста, сек
  onlineClients: number | null; // суммарно онлайн (сумма известных по протоколам)
  onlineByProto?: Record<string, number | null>; // честный online по протоколам: {proto: count|null}
}
export interface ServerMetrics {
  serverId: string;
  current: ServerMetricSample | null; // последнее значение (гейджи/цифры)
  samples: ServerMetricSample[]; // история (мини-графики), в хронологическом порядке
}

// супер-мониторинг клиентов: per-client трафик+онлайн по всем протоколам/серверам
export interface MonitoringClient {
  configId?: string | null; // DeviceConfig.id — для ручной паузы/старта (null у external)
  status?: string; // active | paused | suspended | revoked
  proto: string; // id протокола (awg | xray | hysteria2 | ...)
  clientId: string | null; // pubkey/uuid/authid движка
  userName: string; // имя пользователя (пусто для external)
  deviceName: string; // имя устройства (пусто для external)
  external: boolean; // клиент без нашего DeviceConfig (заведён вне панели)
  extName?: string; // имя из Amnezia clientsTable (только для external — заведён мимо панели, но с именем)
  online: boolean; // активна ли сессия прямо сейчас
  rxTotal: number; // upload (клиент→сервер) за период, байт
  txTotal: number; // download (сервер→клиент) за период, байт
  rxBytes: number; // последний кумулятив upload
  txBytes: number; // последний кумулятив download
  rxSpeed: number; // текущая скорость upload, байт/сек (0 у офлайн)
  txSpeed: number; // текущая скорость download, байт/сек
  lastSeen: number | null; // epoch последнего онлайна/трафика (null — не видели)
  serverId?: string; // заполнено в глобальном мониторинге
  serverName?: string;
}
export interface MonitoringSummary {
  clientsTotal: number;
  clientsOnline: number;
  serversTotal: number;
  rxTotal: number; // суммарный upload за период
  txTotal: number; // суммарный download за период
}
export interface Monitoring {
  period: "1h" | "24h" | "7d";
  onlineWindowSeconds: number;
  summary: MonitoringSummary;
  clients: MonitoringClient[];
}
// per-server overview (тот же endpoint, что и раньше, но с online/speed на клиентах)
export interface ServerTraffic {
  serverId: string;
  period: "1h" | "24h" | "7d";
  onlineWindowSeconds: number;
  clients: MonitoringClient[];
  series: { at: number; proto: string; clientId: string | null; rx: number; tx: number }[];
}

// admin-дашборд здоровья инстанса (не путать с owner-трафиком)
export interface MetricPoint {
  at: number; // epoch seconds
  value: number;
}
export interface MetricSeries {
  name: string;
  labels: string; // компактная строка лейблов, напр. "status=online"
  points: MetricPoint[];
}
export interface MetricsOverview {
  period: "1h" | "24h" | "7d";
  series: MetricSeries[];
  servers: { online: number; offline: number; unknown: number };
  httpTotal: number;
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
  accepted?: boolean; // применение запущено в фоне — дальше поллим UpgradeStatus
  mode?: string;
  target?: string;
  from?: string;
  manual?: boolean;
  message?: string;
  instructions?: string[];
  code?: number;
  log?: string;
}

export interface UpgradeStatus {
  state: "idle" | "running" | "triggered" | "failed";
  mode?: string;
  target?: string;
  from?: string;
  log?: string;
  version: string; // текущая версия бэкенда: стала равной target → обновление удалось
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
// Иконка ПО-вендора (см. PATHS в components/ui). Красится акцентом var(--<type>).
export const VPN_ICON: Record<VpnType, string> = {
  amnezia: "vpn_amnezia",
  openvpn: "vpn_openvpn",
  outline: "vpn_outline",
  hysteria2: "vpn_hysteria2",
};
export const PROTO_LABEL: Record<string, string> = {
  awg: "AmneziaWG",
  awg_legacy: "AmneziaWG Legacy",
  xray: "Xray",
  xray_xhttp: "Xray XHTTP",
  openvpn: "OpenVPN",
  hysteria2: "Hysteria2",
};
// Полный набор протоколов вендора (id → label) для выбора при установке/докачке.
// Зеркалит backend VENDOR_PROTOS + catalog.PROTOS — держать в синхроне при добавлении протокола.
export const VENDOR_PROTOCOLS: Record<VpnType, { id: string; label: string }[]> = {
  amnezia: [
    { id: "awg", label: "AmneziaWG" },
    { id: "awg_legacy", label: "AmneziaWG Legacy" },
    { id: "xray", label: "Xray" },
    { id: "xray_xhttp", label: "Xray XHTTP" },
  ],
  openvpn: [{ id: "openvpn", label: "OpenVPN" }],
  outline: [{ id: "outline", label: "Shadowsocks" }],
  hysteria2: [{ id: "hysteria2", label: "Hysteria2" }],
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
