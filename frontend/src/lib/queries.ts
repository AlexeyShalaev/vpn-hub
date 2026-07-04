// Обёртки над REST-эндпоинтами + ключи react-query.
import { API_BASE, http } from "./api";
import type {
  AdminUser,
  AvailableServer,
  ConfigResult,
  Device,
  Group,
  InvitePeek,
  Me,
  Pool,
  Provider,
  Server,
  ServerAccess,
  Session,
  SystemInfo,
  UpdateCheck,
  UpgradeResult,
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
export const listProviders = () => http.get<Provider[]>("/providers");

// server access overview (владелец: пулы/группы/пользователи+конфиги этого сервера)
export const serverAccess = (sid: string) => http.get<ServerAccess>(`/servers/${sid}/access`);
export const renameServerClient = (sid: string, cid: string, name: string) =>
  http.patch<{ ok: boolean }>(`/servers/${sid}/clients/${cid}`, { name });
export const revokeServerClient = (sid: string, cid: string) =>
  http.del<{ ok: boolean }>(`/servers/${sid}/clients/${cid}`);
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
export const toggleGroupPool = (gid: string, poolId: string) =>
  http.put<Group>(`/groups/${gid}/access/pools/${poolId}`);
export const toggleGroupServer = (gid: string, serverId: string) =>
  http.put<Group>(`/groups/${gid}/access/servers/${serverId}`);
export const toggleGroupServerVpn = (gid: string, serverId: string, type: string) =>
  http.put<Group>(`/groups/${gid}/access/servers/${serverId}/vpns/${type}`);

// member
export const listAvailable = () => http.get<AvailableServer[]>("/me/available");
export const listDevices = () => http.get<Device[]>("/me/devices");
export const addDevice = (b: { name: string; platform: string }) => http.post<Device>("/me/devices", b);
export const removeDevice = (id: string) => http.del(`/me/devices/${id}`);
export const genConfig = (b: { serverId: string; vpn: string; deviceId?: string; proto?: string }) =>
  http.post<ConfigResult>("/configs", b);
export const installConfig = (b: { serverId: string; vpn: string; deviceId: string; proto?: string }) =>
  http.post<{ ok: boolean }>("/configs/install", b);

// admin
export const adminUsers = () => http.get<AdminUser[]>("/admin/users");
export const adminUpdateUser = (id: string, b: Record<string, unknown>) =>
  http.patch<AdminUser>(`/admin/users/${id}`, b);
export const adminDeleteUser = (id: string) => http.del(`/admin/users/${id}`);
export const adminSystem = () => http.get<SystemInfo>("/admin/system");
export const adminCheckUpdates = () => http.post<UpdateCheck>("/admin/system/check-updates");
export const adminUpgrade = () => http.post<UpgradeResult>("/admin/system/upgrade");
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

// admin: providers catalog (YAML-backed)
export const adminCreateProvider = (b: Record<string, unknown>) => http.post<Provider>("/admin/providers", b);
export const adminUpdateProvider = (id: string, b: Record<string, unknown>) =>
  http.put<Provider>(`/admin/providers/${id}`, b);
export const adminDeleteProvider = (id: string) => http.del(`/admin/providers/${id}`);
