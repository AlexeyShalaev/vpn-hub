// Обёртки над REST-эндпоинтами + ключи react-query.
import { API_BASE, http } from "./api";
import type {
  AdminUser,
  AuditEvent,
  AvailableServer,
  ChainLink,
  ConfigResult,
  CostReport,
  Device,
  DeviceLimit,
  FinanceOverview,
  FxRates,
  Group,
  InvitePeek,
  Me,
  MetricsOverview,
  Monitoring,
  MyUsage,
  Pool,
  Provider,
  ProviderPlan,
  Server,
  ServerAccess,
  ServerCost,
  ServerMetrics,
  ServerPrice,
  ServerTraffic,
  ServerUsage,
  Session,
  SystemInfo,
  SystemStorage,
  UpdateCheck,
  UpgradeResult,
  UpgradeStatus,
  VpnAdvanced,
  VpnExternal,
} from "./types";

// auth
export const getMe = () => http.get<Me | null>("/auth/me");
export const setupStatus = () => http.get<{ needed: boolean; keyFromEnv: boolean }>("/setup/status");
export const setupAdmin = (b: {
  name: string;
  phone: string;
  password: string;
  password2?: string;
  masterKey?: string;
}) => http.post<Me>("/setup/admin", b);
export const setupRestore = (file: File, key: string) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("key", key);
  return http.upload<{ ok: boolean }>("/setup/restore", fd);
};
export const login = (b: { phone: string; password: string }) => http.post<Me>("/auth/login", b);
export const register = (b: { name: string; phone: string; password: string; password2: string }) =>
  http.post<{ ok: boolean }>("/auth/register", b);
export const logout = () => http.post<{ ok: boolean }>("/auth/logout");
export const changePassword = (b: { current: string; new: string }) =>
  http.post<{ ok: boolean }>("/auth/change-password", b);
export const listSessions = () => http.get<Session[]>("/auth/sessions");
export const revokeSession = (id: string) => http.del(`/auth/sessions/${id}`);
export const revokeOtherSessions = () => http.post<{ ok: boolean; revoked: number }>("/auth/sessions/revoke-others");

// invites / join
export const peekInvite = (token: string) => http.get<InvitePeek>(`/groups/by-token/${token}`);
export const joinGroup = (token: string) =>
  http.post<{ id: string; name: string; ok: boolean }>(`/groups/join/${token}`);

// servers
export const listServers = () => http.get<Server[]>("/servers");
export const getServer = (id: string) => http.get<Server>(`/servers/${id}`);
export const createServer = (b: Record<string, unknown>) => http.post<Server>("/servers", b);
export const updateServer = (id: string, b: Record<string, unknown>) => http.patch<Server>(`/servers/${id}`, b);
export const deleteServer = (id: string) => http.del(`/servers/${id}`);
export const checkServer = (id: string) => http.post<Server>(`/servers/${id}/check`);
// миграция на новый VPS: новые SSH-реквизиты + фоновая переустановка установленных протоколов;
// выданные конфиги помечаются revoked (перевыдача — материал сервера генерится заново)
export const migrateServer = (
  id: string,
  b: { ip: string; sshPort?: string; sshUser?: string; auth?: string; secret?: string },
) =>
  http.post<{ server: Server; reinstall: Record<string, string[]>; configsRevoked: number }>(
    `/servers/${id}/migrate`,
    b,
  );
export const syncServer = (id: string) => http.post<Server>(`/servers/${id}/sync`);
// install: protos — выбранные протоколы вендора (id); пусто → все. Для start/stop/remove тело игнорируется.
export const vpnOp = (id: string, type: string, op: string, protos?: string[]) =>
  http.post<Server>(`/servers/${id}/vpns/${type}/${op}`, protos?.length ? { protos } : undefined);
// автофикс ошибки установки: устранить причину по SSH и переустановить (роутится через {op}=fix)
export const vpnFix = (id: string, type: string) => http.post<Server>(`/servers/${id}/vpns/${type}/fix`);
// операция над одним протоколом: op ∈ {start, stop, remove}
// (start/stop — свитчер контейнера; remove — снос + отзыв конфигов этого протокола)
export const protocolOp = (id: string, proto: string, op: string) =>
  http.post<Server>(`/servers/${id}/protocols/${proto}/${op}`);
export const removeProtocol = (id: string, proto: string) => protocolOp(id, proto, "remove");
// обновление серверного компонента протокола (xray/hysteria2): rebuild контейнера --no-cache --pull
export const updateProtocol = (id: string, proto: string) => protocolOp(id, proto, "update");
// смена obfuscation-параметров AmneziaWG: preset ∈ {default, aggressive, mobile} ЛИБО values (ручной ввод).
// переписывает живой awg0.conf + syncconf (пиры сохраняются) и обновляет params_json.
export const setProtocolParams = (
  id: string,
  proto: string,
  body: { preset?: string; values?: Record<string, string> },
) => http.patch<Server>(`/servers/${id}/protocols/${proto}/params`, body);
// управление Xray-Reality: rotate_short_id (новый shortId) и/или смена sni (маскировочный домен) —
// переписывает realitySettings в server.json + рестарт контейнера; клиенты (uuid) сохраняются.
export const setReality = (
  id: string,
  proto: string,
  body: { rotate_short_id?: boolean; short_id?: string; sni?: string },
) => http.patch<Server>(`/servers/${id}/protocols/${proto}/reality`, body);
// мягкий лимит числа конфигов на протоколе (owner): maxClients=null/0 → снять лимит
export const setProtocolLimit = (id: string, proto: string, maxClients: number | null) =>
  http.patch<Server>(`/servers/${id}/protocols/${proto}/limit`, { maxClients });
// квота трафика тарифа + день сброса периода (owner): quotaBytes=null/0 → безлимит
export const setBandwidthQuota = (id: string, quotaBytes: number | null, billingDay: number | null) =>
  http.patch<Server>(`/servers/${id}/quota`, { quotaBytes, billingDay });
// трафик сервера и пользователей за текущий период (owner)
export const serverUsage = (id: string) => http.get<ServerUsage>(`/servers/${id}/usage`);
// финансовый учёт: цена сервера + accrual-расход + сводный отчёт
export const getServerPrice = (id: string) => http.get<{ price: ServerPrice | null }>(`/servers/${id}/price`);
export const setServerPrice = (
  id: string,
  b: { amount: number | null; currency: string; period: string; anchorDay: number | null },
) => http.put<{ price: ServerPrice | null }>(`/servers/${id}/price`, b);
export const serverCost = (id: string) => http.get<ServerCost>(`/servers/${id}/cost`);
export const financeCost = () => http.get<CostReport>("/finance/cost");
export const financeOverview = (start: number, end: number) => {
  const qs = new URLSearchParams({ start: String(start), end: String(end) });
  return http.get<FinanceOverview>(`/finance/overview?${qs.toString()}`);
};

// мультихоп: цепочки, где этот сервер — вход (entry); трафик выходит через exit-сервер (Xray outbound)
export const listChains = (sid: string) => http.get<ChainLink[]>(`/servers/${sid}/chains`);
export const createChain = (sid: string, exitServerId: string) =>
  http.post<ChainLink>(`/servers/${sid}/chains`, { exitServerId });
export const deleteChain = (sid: string, chainId: string) =>
  http.del<{ ok: boolean }>(`/servers/${sid}/chains/${chainId}`);
export const listProviders = () => http.get<Provider[]>("/providers");
// справочные тарифные планы провайдера (для автозаполнения цены/квоты при создании сервера)
export const providerPlans = (pid: string) => http.get<ProviderPlan[]>(`/providers/${pid}/plans`);
// курсы валют (кэш ЦБ РФ) — чтобы подбор тарифов сводил цены разных провайдеров к одной валюте
export const fxRates = () => http.get<FxRates>("/fx/rates");

// per-server ресурсы хоста (CPU/RAM/диск/load/uptime/TCP + онлайн-клиенты) — последние + история за период
export const serverMetrics = (sid: string, period = "24h") =>
  http.get<ServerMetrics>(`/servers/${sid}/metrics?period=${encodeURIComponent(period)}`);

// per-server per-client трафик+онлайн (клиенты этого сервера: скачал/отдал/скорость/онлайн)
export const serverTraffic = (sid: string, period = "24h") =>
  http.get<ServerTraffic>(`/servers/${sid}/traffic?period=${encodeURIComponent(period)}`);

// глобальный супер-мониторинг: per-client трафик+онлайн по ВСЕМ серверам владельца + сводка
export const monitoring = (period = "24h") => http.get<Monitoring>(`/monitoring?period=${encodeURIComponent(period)}`);

// включить точную онлайн-статистику (Xray Stats API / Hysteria2 trafficStats) — рестарт контейнеров
export const enableServerStats = (sid: string) =>
  http.post<{ enabled: Record<string, string> }>(`/servers/${sid}/stats/enable`, {});

// server access overview (владелец: пулы/группы/пользователи+конфиги этого сервера)
export const serverAccess = (sid: string) => http.get<ServerAccess>(`/servers/${sid}/access`);
export const renameServerClient = (sid: string, cid: string, name: string) =>
  http.patch<{ ok: boolean }>(`/servers/${sid}/clients/${cid}`, { name });
export const revokeServerClient = (sid: string, cid: string) =>
  http.del<{ ok: boolean }>(`/servers/${sid}/clients/${cid}`);
// ручная пауза/старт доступа по конфигу (cid = config_id); статус → paused/active
export const pauseServerClient = (sid: string, cid: string) =>
  http.post<{ ok: boolean; status: string }>(`/servers/${sid}/clients/${cid}/pause`);
export const resumeServerClient = (sid: string, cid: string) =>
  http.post<{ ok: boolean; status: string }>(`/servers/${sid}/clients/${cid}/resume`);
export const vpnAdvanced = (sid: string, vtype: string) => http.get<VpnAdvanced>(`/servers/${sid}/vpns/${vtype}`);
export const vpnExternal = (sid: string, vtype: string) =>
  http.get<VpnExternal>(`/servers/${sid}/vpns/${vtype}/external`);

// pools
export const listPools = () => http.get<Pool[]>("/pools");
export const createPool = (b: { name: string; serverIds: string[] }) => http.post<Pool>("/pools", b);
export const updatePool = (id: string, b: { name: string; serverIds: string[] }) => http.patch<Pool>(`/pools/${id}`, b);
export const deletePool = (id: string) => http.del(`/pools/${id}`);

// groups
export const listGroups = () => http.get<Group[]>("/groups");
export const getGroup = (id: string) => http.get<Group>(`/groups/${id}`);
export const createGroup = (b: { name: string }) => http.post<Group>("/groups", b);
export const updateGroup = (id: string, b: { name: string }) => http.patch<Group>(`/groups/${id}`, b);
export const deleteGroup = (id: string) => http.del(`/groups/${id}`);
export const regenToken = (id: string) => http.post<Group>(`/groups/${id}/token`);
export const addMember = (id: string, b: { name: string; role: string; phone?: string }) =>
  http.post<Group>(`/groups/${id}/members`, b);
export const toggleMemberRole = (gid: string, mid: string) => http.post<Group>(`/groups/${gid}/members/${mid}/role`);
export const removeMember = (gid: string, mid: string) => http.del<Group>(`/groups/${gid}/members/${mid}`);
export const setGroupLimit = (gid: string, maxDevices: number | null) =>
  http.patch<Group>(`/groups/${gid}/limit`, { maxDevices });
export const setMemberLimit = (gid: string, mid: string, maxDevices: number | null) =>
  http.patch<Group>(`/groups/${gid}/members/${mid}/limit`, { maxDevices });
export const setGroupBytes = (gid: string, maxBytes: number | null) =>
  http.patch<Group>(`/groups/${gid}/byte-limit`, { maxBytes });
export const setMemberBytes = (gid: string, mid: string, maxBytes: number | null) =>
  http.patch<Group>(`/groups/${gid}/members/${mid}/byte-limit`, { maxBytes });
export const toggleGroupPool = (gid: string, poolId: string) =>
  http.put<Group>(`/groups/${gid}/access/pools/${poolId}`);
export const toggleGroupServer = (gid: string, serverId: string) =>
  http.put<Group>(`/groups/${gid}/access/servers/${serverId}`);
export const toggleGroupServerVpn = (gid: string, serverId: string, type: string) =>
  http.put<Group>(`/groups/${gid}/access/servers/${serverId}/vpns/${type}`);

// member
export const listAvailable = () => http.get<AvailableServer[]>("/me/available");
export const listDevices = () => http.get<Device[]>("/me/devices");
export const deviceLimit = () => http.get<DeviceLimit>("/me/devices/limit");
export const myUsage = () => http.get<MyUsage[]>("/me/usage");
export const addDevice = (b: { name: string; platform: string }) => http.post<Device>("/me/devices", b);
export const removeDevice = (id: string) => http.del(`/me/devices/${id}`);
// peek=true: только список протоколов/приложений для выбора, БЕЗ провижининга конфига на сервере
export const genConfig = (b: {
  serverId: string;
  vpn: string;
  deviceId?: string;
  proto?: string;
  bundle?: boolean; // amnezia: true — склеить awg/awg_legacy/xray в один vpn://; false — только proto
  peek?: boolean;
}) => http.post<ConfigResult>("/configs", b);
export const installConfig = (b: {
  serverId: string;
  vpn: string;
  deviceId: string;
  proto?: string;
  bundle?: boolean;
}) => http.post<{ ok: boolean }>("/configs/install", b);
// отозвать свой конфиг: снимает клиента на сервере (SSH) и удаляет запись (симметрично generate)
export const removeConfig = (b: { serverId: string; vpn: string; deviceId: string; proto?: string | null }) =>
  http.post<{ ok: boolean }>("/configs/remove", b);

// events (аудит-лог): admin — все события, owner — только свои ресурсы/действия
export const listEvents = (params?: { type?: string; since?: number; until?: number; limit?: number }) => {
  const sp = new URLSearchParams();
  if (params?.type) sp.set("type", params.type);
  if (params?.since != null) sp.set("since", String(params.since));
  if (params?.until != null) sp.set("until", String(params.until));
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString();
  return http.get<AuditEvent[]>(`/events${qs ? `?${qs}` : ""}`);
};

// admin
export const adminUsers = () => http.get<AdminUser[]>("/admin/users");
export const adminUpdateUser = (id: string, b: Record<string, unknown>) =>
  http.patch<AdminUser>(`/admin/users/${id}`, b);
export const adminDeleteUser = (id: string) => http.del(`/admin/users/${id}`);
export const adminSystem = () => http.get<SystemInfo>("/admin/system");
// админ: развёртывание + дисковое использование (папки, тома, размер БД по таблицам)
export const adminSystemStorage = () => http.get<SystemStorage>("/admin/system/storage");
// admin-дашборд здоровья инстанса (health самой панели, не VPN-трафик клиентов)
export const adminMetrics = (period: string) =>
  http.get<MetricsOverview>(`/admin/metrics?period=${encodeURIComponent(period)}`);
export const adminCheckUpdates = () => http.post<UpdateCheck>("/admin/system/check-updates");
export const adminUpgrade = () => http.post<UpgradeResult>("/admin/system/upgrade");
// поллится во время применения обновления: смена version = успех, state=failed = ошибка
export const adminUpgradeStatus = () => http.get<UpgradeStatus>("/admin/system/upgrade/status");
export const adminCreateBackup = () => http.post<{ ok: boolean; id: string }>("/admin/system/backups");
export const adminDeleteBackup = (id: string) => http.del(`/admin/system/backups/${encodeURIComponent(id)}`);
export const adminDownloadBackupUrl = (id: string) =>
  `${API_BASE}/admin/system/backups/${encodeURIComponent(id)}/download`;
export const adminImportBackup = (file: File, key: string) => {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("key", key);
  return http.upload<{ ok: boolean }>("/admin/system/backups/import", fd);
};
export const adminSetBackupSettings = (b: { frequency?: string; key?: string }) =>
  http.put<{ ok: boolean }>("/admin/system/backup-settings", b);
export const adminSetDeviceLimit = (defaultDevicesPerUser: number) =>
  http.put<{ ok: boolean }>("/admin/system/device-limit", { defaultDevicesPerUser });
export const adminSetUserByteLimit = (defaultUserBytes: number | null) =>
  http.put<{ ok: boolean }>("/admin/system/user-byte-limit", { defaultUserBytes });
export const adminSetMetricsRetention = (rawRetentionDays: number | null, sizeCapGb: number) =>
  http.put<{ ok: boolean }>("/admin/system/metrics-retention", { rawRetentionDays, sizeCapGb });

// admin: providers catalog (YAML-backed)
export const adminCreateProvider = (b: Record<string, unknown>) => http.post<Provider>("/admin/providers", b);
export const adminUpdateProvider = (id: string, b: Record<string, unknown>) =>
  http.put<Provider>(`/admin/providers/${id}`, b);
export const adminDeleteProvider = (id: string) => http.del(`/admin/providers/${id}`);
