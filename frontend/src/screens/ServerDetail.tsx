import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { type ChartLine, LineChart } from "../components/chart";
import { Btn, Field, Icon, Modal, ScreenHeader, Spinner, StatusBadge } from "../components/ui";
import * as q from "../lib/queries";
import type { MonitoringClient, Protocol, Server, ServerMetricSample, Vpn, VpnType } from "../lib/types";
import { PROTO_STATE_LABEL, VENDOR_PROTOCOLS, VPN_DESC, VPN_ICON, VPN_LABEL } from "../lib/types";
import { vpnLogo } from "../lib/vpnLogos";
import { useNav } from "../nav";
import { copyText, useStore } from "../store";
import { ServerAccessSections } from "./ServerAccess";
import { VpnAdvancedModal } from "./VpnAdvanced";

const VPN_TYPES: VpnType[] = ["amnezia", "openvpn", "outline", "hysteria2"];

// установлен ли на сервере запущенный tcp-Reality Xray (условие мультихопа для entry/exit)
const hasRunningXray = (s: Server): boolean =>
  (s.protocols ?? []).some((p) => p.proto === "xray" && p.installed && p.running);

// человекочитаемые размеры/время для карточки ресурсов
const fmtBytes = (n: number | null): string => {
  if (n == null) return "—";
  const u = ["Б", "КБ", "МБ", "ГБ", "ТБ"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
};
const fmtUptime = (s: number | null): string => {
  if (s == null) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}д ${h}ч`;
  if (h > 0) return `${h}ч ${m}м`;
  return `${m}м`;
};
const pct = (used: number | null, total: number | null): number | null =>
  used != null && total != null && total > 0 ? Math.round((used / total) * 100) : null;

// плитка-показатель (значение + подпись + опциональный процент)
function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px", minWidth: 0 }}>
      <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, lineHeight: 1.1 }}>{value}</div>
      {sub && (
        <div className="muted-3" style={{ fontSize: 11.5, marginTop: 3 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

const PROTO_ONLINE_LABEL: Record<string, string> = {
  awg: "AmneziaWG",
  awg_legacy: "AWG Legacy",
  xray: "Xray",
  xray_xhttp: "Xray XHTTP",
  hysteria2: "Hysteria2",
  openvpn: "OpenVPN",
  outline: "Outline",
};
// подсказка, ПОЧЕМУ online неизвестен (—) для протокола
const ONLINE_NA_HINT: Record<string, string> = {
  outline: "Shadowsocks не поддерживает счётчик онлайн-сессий",
  openvpn: "Онлайн для OpenVPN пока не поддержан",
};
// протоколы, для которых точную статистику можно включить (Xray Stats API / Hysteria2 trafficStats)
const STATS_ENABLABLE = ["xray", "xray_xhttp", "hysteria2"];

// Карточка «Ресурсы сервера»: текущие CPU/RAM/диск/load/uptime/TCP + честный online по протоколам + мини-графики.
// Сбор — в monitor-тике по SSH (best-effort); поллинг здесь — как и остальной ServerDetail.
function ServerMetricsCard({ serverId, online }: { serverId: string; online: boolean }) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const mq = useQuery({
    queryKey: ["serverMetrics", serverId],
    queryFn: () => q.serverMetrics(serverId),
    enabled: !!serverId,
    refetchInterval: 60000, // как страховочный поллинг всего ServerDetail
  });
  const enableStatsMut = useMutation({
    mutationFn: () => q.enableServerStats(serverId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["serverMetrics", serverId] });
      toast("Точная онлайн-статистика включена — цифры появятся после ближайшего цикла мониторинга");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось включить статистику"),
  });

  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const cur = mq.data?.current ?? null;
  const samples: ServerMetricSample[] = mq.data?.samples ?? [];

  const line = (pick: (s: ServerMetricSample) => number | null, color: string, name: string): ChartLine => ({
    color,
    label: name,
    points: samples.filter((s) => pick(s) != null).map((s) => ({ at: s.at, value: pick(s) as number })),
  });

  const memPct = cur ? pct(cur.memUsed, cur.memTotal) : null;
  const diskPct = cur ? pct(cur.diskUsed, cur.diskTotal) : null;

  return (
    <div className="card stack">
      <div className="muted-3" style={label}>
        Ресурсы сервера
      </div>

      {mq.isLoading ? (
        <Spinner />
      ) : !cur ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {online
            ? "Метрики появятся после ближайшего цикла мониторинга (собираются по SSH)."
            : "Сервер офлайн — метрики ресурсов не собираются."}
        </p>
      ) : (
        <>
          <div className="grid">
            <Metric label="CPU" value={cur.cpuPct != null ? `${cur.cpuPct}%` : "—"} sub={`load ${cur.load1 ?? "—"}`} />
            <Metric
              label="Память"
              value={memPct != null ? `${memPct}%` : "—"}
              sub={`${fmtBytes(cur.memUsed)} / ${fmtBytes(cur.memTotal)}`}
            />
            <Metric
              label="Диск /"
              value={diskPct != null ? `${diskPct}%` : "—"}
              sub={`${fmtBytes(cur.diskUsed)} / ${fmtBytes(cur.diskTotal)}`}
            />
            <Metric label="Аптайм" value={fmtUptime(cur.uptimeS)} />
            <Metric label="TCP-соединения" value={cur.tcpEstab != null ? String(cur.tcpEstab) : "—"} />
            {cur.onlineClients != null && (
              <Metric label="Онлайн-клиенты" value={String(cur.onlineClients)} sub="всего по протоколам" />
            )}
          </div>

          {/* Честный online по протоколам: число — точное; «—» = неизвестно (stats не включён / нет счётчика) */}
          <div className="stack" style={{ gap: 8 }}>
            <div style={{ fontSize: 12.5, color: "var(--text-2)" }}>Онлайн по протоколам</div>
            <div className="rowflex" style={{ gap: 6, flexWrap: "wrap" }}>
              {Object.entries(cur.onlineByProto ?? {}).map(([proto, n]) => (
                <span
                  key={proto}
                  className={`badge ${n == null ? "" : "ok"}`}
                  title={
                    n == null ? (ONLINE_NA_HINT[proto] ?? "Точная статистика не включена — нажмите «Включить»") : ""
                  }
                >
                  {PROTO_ONLINE_LABEL[proto] ?? proto}: {n == null ? "—" : n}
                </span>
              ))}
              {Object.keys(cur.onlineByProto ?? {}).length === 0 && (
                <span className="muted-3" style={{ fontSize: 12.5 }}>
                  нет данных
                </span>
              )}
            </div>
            {Object.entries(cur.onlineByProto ?? {}).some(([p, n]) => STATS_ENABLABLE.includes(p) && n == null) && (
              <Btn
                variant="ghost"
                sm
                disabled={enableStatsMut.isPending}
                title="Включит Xray Stats API / Hysteria2 trafficStats. Контейнеры xray/hysteria2 будут перезапущены (короткий обрыв сессий)."
                onClick={() => enableStatsMut.mutate()}
              >
                {enableStatsMut.isPending ? <Spinner /> : "Включить точную онлайн-статистику"}
              </Btn>
            )}
          </div>

          {samples.length > 1 && (
            <div className="stack" style={{ gap: 14, marginTop: 4 }}>
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 6 }}>CPU / память (%)</div>
                <LineChart
                  height={130}
                  lines={[
                    line((s) => s.cpuPct, "#3b82f6", "CPU %"),
                    line((s) => pct(s.memUsed, s.memTotal), "#a855f7", "Память %"),
                  ]}
                />
              </div>
              <div>
                <div style={{ fontSize: 12.5, color: "var(--text-2)", marginBottom: 6 }}>TCP-соединения</div>
                <LineChart height={130} lines={[line((s) => s.tcpEstab, "#22c55e", "TCP established")]} />
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const PROTO_TRAFFIC_LABEL: Record<string, string> = {
  awg: "AmneziaWG",
  awg_legacy: "AWG Legacy",
  xray: "Xray",
  xray_xhttp: "Xray XHTTP",
  hysteria2: "Hysteria2",
  openvpn: "OpenVPN",
  outline: "Outline",
};
const clientLabel = (c: MonitoringClient): string =>
  c.userName || c.deviceName
    ? [c.userName, c.deviceName].filter(Boolean).join(" · ")
    : c.external
      ? "Внешний клиент"
      : (c.clientId ?? "—");
const fmtSpeed = (bps: number): string => (bps > 0 ? `${fmtBytes(bps)}/с` : "—");

// Карточка «Клиенты сервера»: per-client трафик+онлайн этого сервера (переиспользует global
// overview через per-server endpoint /servers/{id}/traffic). Онлайн — точка, трафик — за 24ч.
function ServerClientsCard({ serverId, online }: { serverId: string; online: boolean }) {
  const tq = useQuery({
    queryKey: ["serverTraffic", serverId],
    queryFn: () => q.serverTraffic(serverId, "24h"),
    enabled: !!serverId,
    refetchInterval: 60000,
  });
  const label = { fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" as const };
  const clients: MonitoringClient[] = [...(tq.data?.clients ?? [])].sort(
    (a, b) => Number(b.online) - Number(a.online) || b.rxTotal + b.txTotal - (a.rxTotal + a.txTotal),
  );
  const th: React.CSSProperties = {
    textAlign: "left",
    padding: "7px 9px",
    fontSize: 11.5,
    color: "var(--text-3)",
    whiteSpace: "nowrap",
    borderBottom: "1px solid var(--border)",
  };
  const td: React.CSSProperties = { padding: "8px 9px", fontSize: 13, borderBottom: "1px solid var(--border)" };
  const num: React.CSSProperties = {
    ...td,
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
    whiteSpace: "nowrap",
  };

  return (
    <div className="card stack">
      <div className="muted-3" style={label}>
        Клиенты сервера · трафик за 24ч
      </div>
      {tq.isLoading ? (
        <Spinner />
      ) : clients.length === 0 ? (
        <p className="muted" style={{ fontSize: 13 }}>
          {online
            ? "Данных о клиентах ещё нет — статистика собирается в фоне. Для Xray/Hysteria2 включите точную статистику выше."
            : "Сервер офлайн — статистика клиентов не собирается."}
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>Клиент</th>
                <th style={th}>Протокол</th>
                <th style={{ ...th, textAlign: "center" }}>Онлайн</th>
                <th style={{ ...th, textAlign: "right" }}>Скачал</th>
                <th style={{ ...th, textAlign: "right" }}>Отдал</th>
                <th style={{ ...th, textAlign: "right" }}>Скорость ↓/↑</th>
              </tr>
            </thead>
            <tbody>
              {clients.map((c) => (
                <tr key={`${c.proto}:${c.clientId}`}>
                  <td style={td}>
                    <div style={{ fontWeight: 600 }}>{clientLabel(c)}</div>
                    {c.external && (
                      <div className="muted-3" style={{ fontSize: 11 }}>
                        вне панели
                      </div>
                    )}
                  </td>
                  <td style={td}>
                    <span className="badge">{PROTO_TRAFFIC_LABEL[c.proto] ?? c.proto}</span>
                  </td>
                  <td style={{ ...td, textAlign: "center" }}>
                    <span
                      title={c.online ? "онлайн" : "офлайн"}
                      style={{
                        display: "inline-block",
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: c.online ? "#22c55e" : "var(--border-strong, #9ca3af)",
                      }}
                    />
                  </td>
                  <td style={num}>{fmtBytes(c.txTotal)}</td>
                  <td style={num}>{fmtBytes(c.rxTotal)}</td>
                  <td style={num}>{c.online ? `${fmtSpeed(c.txSpeed)} / ${fmtSpeed(c.rxSpeed)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Секция «Цепочка (мультихоп)»: трафик клиентов этого (entry) сервера выходит в интернет через
// другой (exit) сервер. Реализация — Xray outbound chaining: entry становится vless-клиентом exit.
function ChainSection({ server }: { server: Server }) {
  const toast = useStore((s) => s.toast);
  const qc = useQueryClient();
  const [exitId, setExitId] = useState("");

  const chainsQ = useQuery({
    queryKey: ["chains", server.id],
    queryFn: () => q.listChains(server.id),
    enabled: hasRunningXray(server),
  });
  const serversQ = useQuery({ queryKey: ["servers"], queryFn: () => q.listServers() });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["chains", server.id] });

  const createMut = useMutation({
    mutationFn: () => q.createChain(server.id, exitId),
    onSuccess: () => {
      setExitId("");
      invalidate();
      toast("Цепочка Xray создана — трафик Xray пойдёт через выходной сервер");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось создать цепочку"),
  });
  const deleteMut = useMutation({
    mutationFn: (chainId: string) => q.deleteChain(server.id, chainId),
    onSuccess: () => {
      invalidate();
      toast("Цепочка удалена");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось удалить цепочку"),
  });

  // мультихоп работает только для tcp-Reality Xray — прячем секцию, если на entry его нет
  if (!hasRunningXray(server)) return null;

  const chains = chainsQ.data ?? [];
  // кандидаты в exit: чужие серверы владельца, онлайн, с запущенным Xray
  const candidates = (serversQ.data ?? []).filter(
    (s) => s.id !== server.id && s.status === "online" && hasRunningXray(s),
  );

  return (
    <div className="card stack">
      <div
        className="muted-3"
        style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
      >
        Мультихоп Xray → Xray
      </div>
      <p className="muted" style={{ fontSize: 13 }}>
        Только для протокола <strong>Xray</strong> (VLESS + Reality): клиенты Xray этого сервера входят здесь, а в
        интернет выходят через Xray другого вашего сервера. Полезно, когда нужен вход с локальным IP, а выход — в другой
        стране. Клиенты остальных протоколов этого сервера (AmneziaWG, OpenVPN, Outline, Hysteria2) не затрагиваются.
      </p>

      {chains.length > 0 ? (
        <div className="stack" style={{ gap: 8 }}>
          {chains.map((ch) => (
            <div
              key={ch.id}
              className="rowflex"
              style={{
                justifyContent: "space-between",
                gap: 8,
                flexWrap: "nowrap",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 12px",
              }}
            >
              <span className="rowflex" style={{ gap: 8, minWidth: 0 }}>
                <Icon name="refresh" size={15} />
                <span style={{ fontSize: 13.5 }}>
                  Xray → выход через <strong>{ch.exitServerName || ch.exitServerId}</strong> (Xray)
                </span>
                <span className={`badge ${ch.state === "linked" ? "ok" : "warn"}`}>{ch.state}</span>
              </span>
              <Btn
                variant="ghost"
                sm
                disabled={deleteMut.isPending}
                title="Удалить цепочку"
                onClick={() => deleteMut.mutate(ch.id)}
              >
                <Icon name="trash" size={14} />
              </Btn>
            </div>
          ))}
        </div>
      ) : candidates.length > 0 ? (
        <div className="rowflex" style={{ gap: 8, flexWrap: "nowrap" }}>
          <select className="input" value={exitId} onChange={(e) => setExitId(e.target.value)} style={{ flex: 1 }}>
            <option value="">Выберите выходной сервер (Xray)…</option>
            {candidates.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · {s.location || s.ip}
              </option>
            ))}
          </select>
          <Btn variant="primary" disabled={!exitId || createMut.isPending} onClick={() => createMut.mutate()}>
            {createMut.isPending ? <Spinner /> : "Создать"}
          </Btn>
        </div>
      ) : (
        <p className="muted-3" style={{ fontSize: 12.5 }}>
          Нет подходящих выходных серверов: нужен другой ваш сервер онлайн с установленным и запущенным Xray.
        </p>
      )}
    </div>
  );
}

export function ServerDetailScreen() {
  const serverId = useNav((s) => s.params.serverId) || "";
  const go = useNav((s) => s.go);
  const toast = useStore((s) => s.toast);
  const theme = useStore((s) => s.theme);
  const qc = useQueryClient();

  const [reveal, setReveal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // мастер «Мигрировать на новый VPS»: новые SSH-реквизиты; secret пустой → оставить текущий
  const [migrateForm, setMigrateForm] = useState<{
    ip: string;
    sshUser: string;
    sshPort: string;
    auth: string;
    secret: string;
  } | null>(null);
  const [advancedVpn, setAdvancedVpn] = useState<VpnType | null>(null);
  // подтверждение сноса всего вендора (все его протоколы + доступы разом)
  const [confirmRemoveVpn, setConfirmRemoveVpn] = useState<VpnType | null>(null);
  // модалка выбора протоколов для установки/докачки: активный вендор + отмеченные id
  const [addProtoVendor, setAddProtoVendor] = useState<VpnType | null>(null);
  const [checkedProtos, setCheckedProtos] = useState<Set<string>>(new Set());
  // подтверждение удаления одного протокола (сносит контейнер + отзывает его конфиги)
  const [confirmRemoveProto, setConfirmRemoveProto] = useState<{
    vendor: VpnType;
    proto: string;
    label: string;
  } | null>(null);

  const serverQ = useQuery({
    queryKey: ["server", serverId],
    queryFn: () => q.getServer(serverId),
    enabled: !!serverId,
    // прогресс/статус приходят пушем по SSE (см. lib/events); поллинг оставлен СТРАХОВКОЙ
    // на случай тихого обрыва SSE (буферизация прокси / потеря сети) — частоты снижены.
    refetchInterval: (query) => {
      const s = query.state.data as Server | undefined;
      // свежесозданный сервер (ещё не проверен) — ждём авто-пинг/синк, опрашиваем чуть чаще
      if (s?.status === "unknown") return 10000;
      return s?.protocols?.some((p) => p.state === "installing") ? 10000 : 60000;
    },
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["server", serverId] });
    qc.invalidateQueries({ queryKey: ["servers"] });
  };

  const checkMut = useMutation({
    mutationFn: () => q.checkServer(serverId),
    onSuccess: (s) => {
      invalidate();
      toast(s.status === "online" ? `Сервер онлайн · ${s.latency ?? "—"}` : "Сервер недоступен");
    },
    onError: () => toast("Не удалось проверить сервер"),
  });

  const syncMut = useMutation({
    mutationFn: () => q.syncServer(serverId),
    onSuccess: () => {
      invalidate();
      toast("Состояние сервера синхронизировано");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось синхронизировать"),
  });

  const opMut = useMutation({
    mutationFn: ({ type, op, protos }: { type: VpnType; op: string; protos?: string[] }) =>
      q.vpnOp(serverId, type, op, protos),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      const label = VPN_LABEL[vars.type];
      const msg =
        vars.op === "install"
          ? // установка идёт в фоне (mark_installing + schedule_install),
            // ответ приходит мгновенно — сообщаем о старте, а не о завершении
            `${label}: установка запущена — займёт пару минут`
          : vars.op === "remove"
            ? `${label} удалён`
            : vars.op === "start"
              ? `${label} запущен`
              : `${label} остановлен`;
      toast(msg);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка операции"),
  });

  const removeProtoMut = useMutation({
    mutationFn: ({ proto }: { proto: string; label: string }) => q.removeProtocol(serverId, proto),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(`${vars.label} удалён — связанные конфиги отозваны`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось удалить протокол"),
  });

  // свитчер отдельного протокола: временно остановить / снова запустить его контейнер
  const protoOpMut = useMutation({
    mutationFn: ({ proto, op }: { proto: string; label: string; op: string }) => q.protocolOp(serverId, proto, op),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(`${vars.label} ${vars.op === "start" ? "запущен" : "остановлен"}`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Ошибка операции"),
  });

  // обновление серверного компонента протокола (xray/hysteria2) до эталонной версии релиза панели
  const updateProtoMut = useMutation({
    mutationFn: ({ proto }: { proto: string; label: string }) => q.updateProtocol(serverId, proto),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      toast(`${vars.label}: обновление запущено — займёт пару минут`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось запустить обновление"),
  });

  const fixMut = useMutation({
    mutationFn: ({ type }: { type: VpnType }) => q.vpnFix(serverId, type),
    onSuccess: (_s, vars) => {
      qc.invalidateQueries({ queryKey: ["server", serverId] });
      // фикс устраняет причину и запускает переустановку в фоне — сообщаем о старте
      toast(`${VPN_LABEL[vars.type]}: исправление запущено — займёт пару минут`);
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось запустить исправление"),
  });

  // миграция на новый VPS: реквизиты меняются сразу, протоколы переустанавливаются в фоне
  // (прогресс виден через state=installing, как обычная установка); конфиги — к перевыдаче
  const migrateMut = useMutation({
    mutationFn: (b: { ip: string; sshPort?: string; sshUser?: string; auth?: string; secret?: string }) =>
      q.migrateServer(serverId, b),
    onSuccess: (r) => {
      setMigrateForm(null);
      invalidate();
      const protoCount = Object.values(r.reinstall).reduce((n, ids) => n + ids.length, 0);
      toast(
        protoCount
          ? `Миграция запущена: переустановка ${protoCount} протокол(ов), конфигов к перевыдаче: ${r.configsRevoked}`
          : "Реквизиты обновлены — установленных протоколов для переноса нет",
      );
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось запустить миграцию"),
  });

  const deleteMut = useMutation({
    mutationFn: () => q.deleteServer(serverId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["servers"] });
      toast("Сервер удалён");
      go("servers");
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Не удалось удалить сервер"),
  });

  if (serverQ.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
        <Spinner />
      </div>
    );
  }
  if (serverQ.isError || !serverQ.data) {
    return (
      <div className="stack">
        <ScreenHeader title="Сервер" onBack={() => go("servers")} />
        <div className="card muted">Сервер не найден.</div>
      </div>
    );
  }

  const server: Server = serverQ.data;
  const checking = checkMut.isPending;
  const online = server.status === "online";
  const authLabel = server.auth === "key" ? "SSH-ключ" : "Пароль";
  const secretShown = reveal ? server.secret : "•".repeat(Math.max(6, server.secret.length || 6));

  const vpnByType = (t: VpnType): Vpn =>
    server.vpns.find((v) => v.type === t) ?? { type: t, installed: false, running: false, port: "" };
  const protosByVendor = (t: VpnType): Protocol[] => (server.protocols ?? []).filter((p) => p.vendor === t);
  const syncing = syncMut.isPending;

  return (
    <div className="stack">
      <ScreenHeader
        title={server.name}
        sub={`${server.provider} · ${server.location}`}
        onBack={() => go("servers")}
        action={
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => go("serverForm", { serverId })}>
              <Icon name="edit" size={16} />
              Изменить
            </Btn>
            <Btn variant="danger" sm onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" size={16} />
            </Btn>
          </div>
        }
      />

      {/* Статус */}
      <div className="card">
        <div className="rowflex" style={{ justifyContent: "space-between" }}>
          <div className="rowflex">
            <StatusBadge status={server.status} />
            {server.latency && (
              <span className="muted" style={{ fontSize: 13 }}>
                {server.latency}
              </span>
            )}
            <span className="muted-3" style={{ fontSize: 13 }}>
              проверен: {server.lastCheck || "ещё не проверялся"}
            </span>
          </div>
          <div className="rowflex" style={{ flexWrap: "nowrap" }}>
            <Btn sm onClick={() => syncMut.mutate()} disabled={syncing}>
              {syncing ? <Spinner /> : <Icon name="refresh" size={16} />}
              {syncing ? "Синк…" : "Синхронизировать"}
            </Btn>
            <Btn sm onClick={() => checkMut.mutate()} disabled={checking}>
              {checking ? <Spinner /> : <Icon name="refresh" size={16} />}
              {checking ? "Проверка…" : "Проверить"}
            </Btn>
          </div>
        </div>
      </div>

      {/* SSH */}
      <div className="card stack">
        <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
          <div
            className="muted-3"
            style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
          >
            Подключение SSH
          </div>
          <Btn
            sm
            onClick={() =>
              setMigrateForm({
                ip: "",
                sshUser: server.sshUser,
                sshPort: server.sshPort,
                auth: server.auth,
                secret: "",
              })
            }
          >
            <Icon name="refresh" size={15} />
            Мигрировать на новый VPS
          </Btn>
        </div>
        <div className="grid">
          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              IP-адрес
            </div>
            <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <span className="mono" style={{ fontSize: 13.5 }}>
                {server.ip}
              </span>
              <Btn variant="ghost" sm onClick={() => copyText(server.ip, toast, "IP скопирован")}>
                <Icon name="copy" size={15} />
              </Btn>
            </div>
          </div>

          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              Пользователь · порт
            </div>
            <span className="mono" style={{ fontSize: 13.5 }}>
              {server.sshUser} : {server.sshPort}
            </span>
          </div>

          <div style={{ background: "var(--surface-2)", borderRadius: 11, padding: "11px 13px" }}>
            <div className="muted-3" style={{ fontSize: 11.5, marginBottom: 4 }}>
              {authLabel}
            </div>
            <div className="rowflex" style={{ justifyContent: "space-between", flexWrap: "nowrap" }}>
              <span className="mono" style={{ fontSize: 13.5, minWidth: 0, wordBreak: "break-all" }}>
                {secretShown}
              </span>
              <Btn variant="ghost" sm onClick={() => setReveal((r) => !r)}>
                <Icon name="eye" size={15} />
                {reveal ? "Скрыть" : "Показать"}
              </Btn>
            </div>
          </div>
        </div>
      </div>

      {/* VPN ПО */}
      <div className="card stack">
        <div
          className="muted-3"
          style={{ fontSize: 12, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase" }}
        >
          VPN ПО на сервере
        </div>
        <div className="stack" style={{ gap: 10 }}>
          {VPN_TYPES.map((type) => {
            const v = vpnByType(type);
            const protos = protosByVendor(type);
            const catalog = VENDOR_PROTOCOLS[type]; // все протоколы вендора (для выбора/докачки)
            const notInstalled = catalog.filter((pr) => !protos.find((x) => x.proto === pr.id)?.installed);
            const installing = protos.some((p) => p.state === "installing");
            const errored = protos.find((p) => p.state === "error");
            const rem = errored?.remediation ?? null;
            const busy =
              (opMut.isPending && opMut.variables?.type === type) ||
              (fixMut.isPending && fixMut.variables?.type === type);
            const runLabel = installing
              ? "устанавливается…"
              : !v.installed
                ? "не установлен"
                : v.running
                  ? "работает"
                  : "остановлен";
            const runClass = installing ? "neutral" : v.installed && v.running ? "ok" : "neutral";
            return (
              <div
                key={type}
                className="stack"
                style={{
                  border: `1px solid ${errored ? "var(--danger)" : "var(--border)"}`,
                  borderRadius: 13,
                  padding: 13,
                  gap: 12,
                }}
              >
                {/* Шапка: иконка + имя вендора + агрегатный статус (клик — расширенные настройки) */}
                <div className="rowflex" style={{ gap: 12, flexWrap: "nowrap", alignItems: "flex-start" }}>
                  <div
                    style={{
                      width: 38,
                      height: 38,
                      borderRadius: 10,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flex: "none",
                      background: "var(--surface-2)",
                      color: `var(--${type})`,
                    }}
                  >
                    {vpnLogo(type, theme) ? (
                      <img
                        src={vpnLogo(type, theme)}
                        alt={VPN_LABEL[type]}
                        width={26}
                        height={26}
                        style={{ objectFit: "contain", display: "block" }}
                      />
                    ) : (
                      <Icon name={VPN_ICON[type]} size={20} />
                    )}
                  </div>
                  <div
                    style={{ flex: 1, minWidth: 0, cursor: v.installed ? "pointer" : "default" }}
                    onClick={v.installed ? () => setAdvancedVpn(type) : undefined}
                  >
                    <div className="rowflex" style={{ gap: 8 }}>
                      <span style={{ fontWeight: 700, fontSize: 15 }}>{VPN_LABEL[type]}</span>
                      <span className={`badge ${runClass}`}>{runLabel}</span>
                      {v.installed && (
                        <span className="muted-3" style={{ display: "inline-flex" }} title="Расширенные настройки">
                          <Icon name="chevron" size={14} />
                        </span>
                      )}
                    </div>
                    <div className="muted-3" style={{ fontSize: 12.5, marginTop: 2 }}>
                      {VPN_DESC[type]}
                    </div>
                  </div>
                </div>

                {/* Протоколы: ровный список со статус-точкой и пер-протокольными действиями */}
                {(v.installed || installing) && (
                  <div
                    className="stack"
                    style={{ gap: 2, borderTop: "1px solid var(--border)", paddingTop: 10 }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div
                      className="muted-3"
                      style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".04em", textTransform: "uppercase" }}
                    >
                      Протоколы
                    </div>
                    {catalog.map((pr) => {
                      const p = protos.find((x) => x.proto === pr.id);
                      const st = p?.state ?? "absent";
                      const inst = p?.installed ?? false;
                      const running = p?.running ?? false;
                      const ext = p?.externalClients ?? 0;
                      // у установленного показываем работает/остановлен, иначе — состояние установки
                      const stateText = inst ? (running ? "работает" : "остановлен") : (PROTO_STATE_LABEL[st] ?? st);
                      const dotColor =
                        st === "installing"
                          ? "var(--warn)"
                          : inst && running
                            ? "var(--ok)"
                            : inst
                              ? "var(--warn)"
                              : "var(--border-strong)";
                      return (
                        <div
                          key={pr.id}
                          className="rowflex"
                          style={{
                            justifyContent: "space-between",
                            gap: 8,
                            flexWrap: "nowrap",
                            minHeight: 34,
                            opacity: inst || st === "installing" ? 1 : 0.55,
                          }}
                        >
                          <span className="rowflex" style={{ gap: 8, minWidth: 0, flexWrap: "nowrap" }}>
                            <span
                              style={{
                                width: 7,
                                height: 7,
                                borderRadius: 999,
                                flex: "none",
                                background: dotColor,
                              }}
                            />
                            <span
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                whiteSpace: "nowrap",
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                            >
                              {pr.label}
                            </span>
                            <span className="muted-3" style={{ fontSize: 11.5, whiteSpace: "nowrap", flex: "none" }}>
                              {stateText}
                              {ext > 0 ? ` · +${ext} внешн.` : ""}
                            </span>
                            {p?.updateAvailable && (
                              <span
                                className="badge warn"
                                title={`Доступно обновление: ${p.imageVersion ?? "?"} → ${p.latestVersion ?? "?"}`}
                                style={{ flex: "none" }}
                              >
                                обновление
                              </span>
                            )}
                          </span>
                          {inst && (
                            <div className="rowflex" style={{ flexWrap: "nowrap", gap: 6, flex: "none" }}>
                              {p?.updateAvailable && (
                                <Btn
                                  variant="primary"
                                  sm
                                  disabled={!online || updateProtoMut.isPending}
                                  title={`Обновить до ${p.latestVersion ?? ""}`}
                                  onClick={() => updateProtoMut.mutate({ proto: pr.id, label: pr.label })}
                                >
                                  Обновить
                                </Btn>
                              )}
                              <Btn
                                sm
                                disabled={!online || protoOpMut.isPending}
                                onClick={() =>
                                  protoOpMut.mutate({ proto: pr.id, label: pr.label, op: running ? "stop" : "start" })
                                }
                              >
                                {running ? "Стоп" : "Запустить"}
                              </Btn>
                              <Btn
                                variant="ghost"
                                sm
                                title={`Удалить протокол ${pr.label}`}
                                disabled={removeProtoMut.isPending}
                                onClick={() => setConfirmRemoveProto({ vendor: type, proto: pr.id, label: pr.label })}
                              >
                                <Icon name="trash" size={13} />
                              </Btn>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Диагностика ошибки установки/сбоя протокола */}
                {errored && (
                  <div onClick={(e) => e.stopPropagation()}>
                    {rem ? (
                      <div className="stack" style={{ gap: 3 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--danger)" }}>{rem.title}</div>
                        <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                          {rem.explanation}
                        </div>
                        {rem.manualSteps.length > 0 && (
                          <ol
                            className="muted-3"
                            style={{ fontSize: 11.5, margin: "2px 0 0", paddingLeft: 16, lineHeight: 1.5 }}
                          >
                            {rem.manualSteps.map((step, i) => (
                              <li key={i} style={{ wordBreak: "break-word" }}>
                                {step}
                              </li>
                            ))}
                          </ol>
                        )}
                      </div>
                    ) : (
                      errored.error && (
                        <div className="muted-3" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                          Ошибка: {errored.error}
                        </div>
                      )
                    )}
                  </div>
                )}

                {/* Действия по вендору: докачать / остановить всё / удалить ПО целиком */}
                <div
                  className="rowflex"
                  style={{ gap: 8, borderTop: "1px solid var(--border)", paddingTop: 11 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {installing ? (
                    <span className="rowflex" style={{ gap: 8 }}>
                      <Spinner />
                      <span className="muted-3" style={{ fontSize: 12.5 }}>
                        Устанавливается…
                      </span>
                    </span>
                  ) : busy ? (
                    <Spinner />
                  ) : (
                    <>
                      {/* fix доступен и в installed-состоянии (частичный сбой: один протокол упал) */}
                      {rem?.canAutoFix && (
                        <Btn variant="primary" sm onClick={() => fixMut.mutate({ type })}>
                          {rem.fixLabel ?? "Исправить"}
                        </Btn>
                      )}
                      {notInstalled.length > 0 && (
                        <Btn
                          variant={v.installed || rem?.canAutoFix ? "ghost" : "primary"}
                          sm
                          onClick={() => {
                            setCheckedProtos(new Set(notInstalled.map((p) => p.id)));
                            setAddProtoVendor(type);
                          }}
                        >
                          {v.installed ? "+ Протоколы" : "Установить"}
                        </Btn>
                      )}
                      {v.installed && (
                        <Btn
                          sm
                          disabled={!online}
                          onClick={() => opMut.mutate({ type, op: v.running ? "stop" : "start" })}
                        >
                          {v.running ? "Остановить всё" : "Запустить всё"}
                        </Btn>
                      )}
                      {v.installed && (
                        <Btn
                          variant="ghost"
                          sm
                          title={`Удалить ${VPN_LABEL[type]} целиком`}
                          style={{ marginLeft: "auto" }}
                          onClick={() => setConfirmRemoveVpn(type)}
                        >
                          <Icon name="trash" size={15} />
                        </Btn>
                      )}
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <ServerMetricsCard serverId={serverId} online={online} />

      <ServerClientsCard serverId={serverId} online={online} />

      <ChainSection server={server} />

      <ServerAccessSections serverId={serverId} />

      {advancedVpn && <VpnAdvancedModal serverId={serverId} vtype={advancedVpn} onClose={() => setAdvancedVpn(null)} />}

      {confirmDelete && (
        <Modal
          title="Удалить сервер?"
          onClose={() => setConfirmDelete(false)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmDelete(false)}>
                Отмена
              </Btn>
              <Btn variant="danger" disabled={deleteMut.isPending} onClick={() => deleteMut.mutate()}>
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">Сервер пропадёт из пулов и групповых доступов. Действие необратимо.</p>
        </Modal>
      )}

      {/* Миграция на новый VPS: новые SSH-реквизиты + переустановка протоколов в фоне */}
      {migrateForm && (
        <Modal
          title="Мигрировать на новый VPS"
          onClose={() => setMigrateForm(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setMigrateForm(null)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                disabled={migrateMut.isPending || !migrateForm.ip.trim()}
                onClick={() =>
                  migrateMut.mutate({
                    ip: migrateForm.ip.trim(),
                    sshPort: migrateForm.sshPort.trim() || undefined,
                    sshUser: migrateForm.sshUser.trim() || undefined,
                    auth: migrateForm.auth || undefined,
                    secret: migrateForm.secret || undefined,
                  })
                }
              >
                {migrateMut.isPending ? <Spinner /> : "Мигрировать"}
              </Btn>
            </>
          }
        >
          <div className="stack" style={{ gap: 10 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              Старый сервер считается недоступным: панель переключится на новые реквизиты и переустановит все
              установленные протоколы на новом хосте (в фоне). Серверные ключи будут сгенерированы заново, поэтому все
              выданные конфиги будут помечены отозванными — участникам нужно перевыпустить их (в конфигах в любом случае
              зашит старый IP).
            </p>
            <Field label="IP нового сервера">
              <input
                className="input mono"
                value={migrateForm.ip}
                onChange={(e) => setMigrateForm({ ...migrateForm, ip: e.target.value })}
                placeholder="203.0.113.10"
              />
            </Field>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
              <Field label="Пользователь">
                <input
                  className="input mono"
                  value={migrateForm.sshUser}
                  onChange={(e) => setMigrateForm({ ...migrateForm, sshUser: e.target.value })}
                  placeholder="root"
                />
              </Field>
              <Field label="Порт">
                <input
                  className="input mono"
                  value={migrateForm.sshPort}
                  onChange={(e) => setMigrateForm({ ...migrateForm, sshPort: e.target.value })}
                  placeholder="22"
                />
              </Field>
            </div>
            <Field label="Способ авторизации">
              <div style={{ display: "flex", gap: 8 }}>
                {(["key", "password"] as const).map((a) => (
                  <button
                    key={a}
                    type="button"
                    className={`chip${migrateForm.auth === a ? " selected" : ""}`}
                    style={{ flex: 1, height: 40, justifyContent: "center", cursor: "pointer", fontSize: 13.5 }}
                    onClick={() => setMigrateForm({ ...migrateForm, auth: a })}
                  >
                    {a === "key" ? "SSH-ключ" : "Пароль"}
                  </button>
                ))}
              </div>
            </Field>
            <Field label={migrateForm.auth === "password" ? "Пароль" : "Приватный SSH-ключ"}>
              <input
                className="input mono"
                type={migrateForm.auth === "password" ? "password" : "text"}
                value={migrateForm.secret}
                onChange={(e) => setMigrateForm({ ...migrateForm, secret: e.target.value })}
                placeholder="пусто — использовать текущий секрет"
              />
            </Field>
          </div>
        </Modal>
      )}

      {/* Выбор протоколов для установки/докачки (галочки) */}
      {addProtoVendor && (
        <Modal
          title={`${VPN_LABEL[addProtoVendor]}: установить протоколы`}
          onClose={() => setAddProtoVendor(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setAddProtoVendor(null)}>
                Отмена
              </Btn>
              <Btn
                variant="primary"
                disabled={checkedProtos.size === 0 || opMut.isPending}
                onClick={() => {
                  const type = addProtoVendor;
                  const protos = [...checkedProtos];
                  setAddProtoVendor(null);
                  opMut.mutate({ type, op: "install", protos });
                }}
              >
                Установить{checkedProtos.size ? ` (${checkedProtos.size})` : ""}
              </Btn>
            </>
          }
        >
          <div className="stack" style={{ gap: 8 }}>
            <p className="muted" style={{ fontSize: 13 }}>
              Отметьте протоколы для установки — каждый развернётся в своём контейнере. Уже установленные протоколы
              здесь не показаны.
            </p>
            {VENDOR_PROTOCOLS[addProtoVendor]
              .filter((pr) => !protosByVendor(addProtoVendor).find((x) => x.proto === pr.id)?.installed)
              .map((pr) => {
                const on = checkedProtos.has(pr.id);
                return (
                  <label
                    key={pr.id}
                    className="rowflex"
                    style={{
                      gap: 11,
                      cursor: "pointer",
                      padding: "11px 13px",
                      border: `1px solid ${on ? "var(--accent)" : "var(--border)"}`,
                      borderRadius: 10,
                      background: on ? "var(--accent-soft)" : "var(--surface)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() =>
                        setCheckedProtos((prev) => {
                          const next = new Set(prev);
                          if (on) next.delete(pr.id);
                          else next.add(pr.id);
                          return next;
                        })
                      }
                    />
                    <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>{pr.label}</span>
                  </label>
                );
              })}
          </div>
        </Modal>
      )}

      {/* Удаление одного протокола (сносит контейнер + отзывает его конфиги) */}
      {confirmRemoveProto && (
        <Modal
          title={`Удалить ${confirmRemoveProto.label}?`}
          onClose={() => setConfirmRemoveProto(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveProto(null)}>
                Отмена
              </Btn>
              <Btn
                variant="danger"
                disabled={removeProtoMut.isPending}
                onClick={() => {
                  const { proto, label } = confirmRemoveProto;
                  setConfirmRemoveProto(null);
                  removeProtoMut.mutate({ proto, label });
                }}
              >
                Удалить
              </Btn>
            </>
          }
        >
          <p className="muted">
            Контейнер протокола будет снесён, а выданные по нему конфиги — отозваны. Другие протоколы этого VPN не
            затрагиваются.
          </p>
        </Modal>
      )}

      {/* Снос всего вендора: все его протоколы + групповые доступы разом */}
      {confirmRemoveVpn && (
        <Modal
          title={`Удалить ${VPN_LABEL[confirmRemoveVpn]} целиком?`}
          onClose={() => setConfirmRemoveVpn(null)}
          footer={
            <>
              <Btn variant="ghost" onClick={() => setConfirmRemoveVpn(null)}>
                Отмена
              </Btn>
              <Btn
                variant="danger"
                disabled={opMut.isPending}
                onClick={() => {
                  const type = confirmRemoveVpn;
                  setConfirmRemoveVpn(null);
                  opMut.mutate({ type, op: "remove" });
                }}
              >
                Удалить всё
              </Btn>
            </>
          }
        >
          <p className="muted">
            Будут снесены все протоколы этого VPN, а связанные конфиги и групповые доступы к нему — отозваны.
          </p>
        </Modal>
      )}
    </div>
  );
}
